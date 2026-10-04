"""Numerical reference checks; run in the pinned vLLM/PyTorch environment."""
import math
import asyncio
import sys
import threading
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
try:
    import torch
except ImportError:
    torch=None
from sft.analysis.vllm_capture import token_counts, entropy, paged_attention_row, image_mapping, collect, _write


@unittest.skipIf(torch is None,'Run with the pinned vLLM PyTorch environment')
class KernelTests(unittest.TestCase):
    def test_reused_logsoftmax_and_tensor_buffer_preserve_values(self):
        from sft.analysis.attention_store import append_row
        devices = ['cpu'] + (['cuda'] if torch.cuda.is_available() else [])
        for device in devices:
            for dtype in (torch.float32, torch.bfloat16, torch.float16):
                logits = torch.linspace(-20, 20, 4096, device=device, dtype=dtype)
                logits[0] = -float('inf')
                lp = torch.log_softmax(logits.float(), dim=-1)
                expected = entropy(logits)
                with patch.object(torch, 'log_softmax', side_effect=AssertionError('recomputed')):
                    self.assertTrue(torch.equal(expected, entropy(logits, logp=lp)))
                weights = torch.softmax(logits.float(), dim=-1)
                with tempfile.TemporaryDirectory() as tmp:
                    old, new = Path(tmp)/'old.attn', Path(tmp)/'new.attn'
                    self.assertEqual(append_row(old, weights.tolist()),
                                     append_row(new, weights.detach().cpu().numpy()))
                    self.assertEqual(old.read_bytes(), new.read_bytes())

    def test_paged_gqa_row_matches_dense_attention_and_sdpa_output(self):
        torch.manual_seed(12)
        keys=torch.randn(19,2,8);values=torch.randn(19,2,8);queries=torch.randn(4,8)
        cache=torch.zeros(5,2,8,2,8)
        block_ids=torch.tensor([3,1,4])
        for i in range(19):
            cache[block_ids[i//8],0,i%8]=keys[i]
            cache[block_ids[i//8],1,i%8]=values[i]
        for head in range(4):
            got=paged_attention_row(queries[head],cache,block_ids,19,head//2,1/math.sqrt(8))
            ref=torch.softmax((queries[head]@keys[:,head//2].T)/math.sqrt(8),dim=-1)
            torch.testing.assert_close(got,ref,rtol=1e-5,atol=1e-7)
            sdpa=torch.nn.functional.scaled_dot_product_attention(queries[head][None,None,None,:],
                keys[:,head//2][None,None,:,:],values[:,head//2][None,None,:,:])
            torch.testing.assert_close(got@values[:,head//2],sdpa.flatten(),rtol=1e-5,atol=1e-6)
            self.assertAlmostEqual(got.sum().item(),1,places=6)
        # Prefix limit prevents the row predicting token q+1 from seeing later keys.
        a=paged_attention_row(queries[0],cache,block_ids,9,0,1/math.sqrt(8))
        cache[block_ids[2],0]=10000
        b=paged_attention_row(queries[0],cache,block_ids,9,0,1/math.sqrt(8))
        torch.testing.assert_close(a,b)
        # Same logical shape with non-contiguous physical strides.
        physical=cache.permute(0,1,3,2,4).contiguous().permute(0,1,3,2,4)
        torch.testing.assert_close(a,paged_attention_row(queries[0],physical,block_ids,9,0,1/math.sqrt(8)))

    def test_entropy_uses_full_vocabulary(self):
        self.assertAlmostEqual(entropy(torch.zeros(8)).item(),math.log(8),places=6)
        self.assertLess(entropy(torch.tensor([100.,-100.])).item(),1e-6)
        self.assertGreater(entropy(torch.tensor([2.,1.,0.,0.,0.])).item(),entropy(torch.tensor([2.,1.])).item())

    def test_actual_processor_spans_grid_and_merge(self):
        feature=SimpleNamespace(modality='image',mm_position=SimpleNamespace(extract_embeds_range=lambda:[(7,10),(13,16)]),
            data={'image_grid_thw':SimpleNamespace(data=torch.tensor([1,4,8]))},mm_hash='processor-hash')
        images=image_mapping([feature,feature],SimpleNamespace(spatial_merge_size=2,patch_size=16))
        self.assertEqual(images[0]['key_indices'],[7,8,9,10,13,14,15,16])
        self.assertEqual(images[0]['patch_boxes'][-1],[.75,.5,1.,1.])
        self.assertNotEqual(images[0]['id'],images[1]['id'])
        feature.data=None
        with self.assertRaises(ValueError):image_mapping([feature],SimpleNamespace(spatial_merge_size=2,patch_size=16))

    def test_response_rank_mapping_and_request_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rank in [0,1]:_write(tmp,'chatcmpl-test-0',rank,dict(type='metadata',prompt_token_ids=[1,2],images=[]))
            _write(tmp,'chatcmpl-test-0',0,dict(type='attention',weights=[.5,.5]))
            _write(tmp,'chatcmpl-other-0',0,dict(type='attention',weights=[1.]))
            self.assertEqual(len(collect(tmp,'chatcmpl-test')['attention']),1)
            self.assertIsNone(collect(tmp,'not-found'))
            _write(tmp,'chatcmpl-api-abc04cdd',0,dict(type='metadata',prompt_token_ids=[3],images=[]))
            self.assertEqual(collect(tmp,'chatcmpl-api')['prompt_token_ids'],[3])


class TokenCountTests(unittest.TestCase):
    def test_reasoning_delimiters_use_engine_ids(self):
        tokenizer=SimpleNamespace(encode=lambda text,**kw:[1] if text=='<think>' else [2],all_special_ids=[1,2,3])
        counts,phases=token_counts([10,1],[5,6,2,7,3],tokenizer)
        self.assertEqual(phases,['reasoning','reasoning','control','content','control'])
        self.assertEqual(counts['reasoning']['value'],2)
        self.assertEqual(counts['output']['value'],5)
        counts,_=token_counts([1,2],[7,3],tokenizer)
        self.assertEqual(counts['reasoning']['value'],0)


class ResponseConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_does_not_block_api_loop_or_mix_requests(self):
        from sft.analysis import vllm_capture as capture
        started, release = threading.Event(), threading.Event()
        original_collect = capture.collect
        def slow_collect(directory, response_id):
            if response_id == 'slow':
                started.set()
                if not release.wait(3):
                    raise TimeoutError('test release not received')
            return original_collect(directory, response_id)
        class Server:
            renderer = SimpleNamespace(tokenizer=None)
            async def create_chat_completion(self, request, *args, **kwargs):
                return SimpleNamespace(id=request.id, choices=[SimpleNamespace(token_ids=None)],
                                       prompt_token_ids=request.ids, __pydantic_extra__=None)
        module = SimpleNamespace(OpenAIServingChat=Server)
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, 'slow', 0, dict(type='metadata', prompt_token_ids=[1], images=[]))
            _write(tmp, 'fast', 0, dict(type='metadata', prompt_token_ids=[2], images=[]))
            expected_slow, expected_fast = collect(tmp, 'slow'), collect(tmp, 'fast')
            with patch.dict(sys.modules, {'vllm.entrypoints.openai.chat_completion.serving': module}), \
                    patch.object(capture, 'collect', side_effect=slow_collect):
                capture._install_response_merge(tmp)
                server = Server()
                slow = asyncio.create_task(server.create_chat_completion(SimpleNamespace(id='slow', ids=[1])))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    fast = await asyncio.wait_for(server.create_chat_completion(SimpleNamespace(id='fast', ids=[2])), .5)
                    self.assertFalse(slow.done())
                    self.assertEqual(fast.__pydantic_extra__['cua_signals'], {**expected_fast, 'output_token_ids': None})
                finally:
                    release.set()
                    result = await slow
                self.assertEqual(result.__pydantic_extra__['cua_signals'], {**expected_slow, 'output_token_ids': None})
                with patch.object(capture, 'collect', side_effect=OSError('read interrupted')), \
                        self.assertLogs('cua.vllm_capture', level='ERROR'):
                    failed = await server.create_chat_completion(SimpleNamespace(id='fast', ids=[2]))
                self.assertEqual(failed.id, 'fast')
                self.assertEqual(failed.__pydantic_extra__['cua_signals']['capture_errors'],
                                 [{'stage':'response_merge', 'message':'read interrupted'}])


if __name__=='__main__':unittest.main()
