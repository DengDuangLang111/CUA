"""Image-only storage preserves visual values/statistics and declares omitted text keys."""
from array import array
import copy
import math
from pathlib import Path
import tempfile
import unittest
from sft.analysis.attention_store import append_row
from sft.analysis.visual_signals import attention_analysis
try:
    import torch
except ImportError:
    torch=None


class ImageOnlyTests(unittest.TestCase):
    def test_visual_stats_and_averages_identical_and_bad_mapping_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            images=[dict(id='a',key_indices=[0,3],token_count=2),dict(id='b',key_indices=[5],token_count=1)]
            full=dict(images=images,output_token_ids=[10,11],attention=[])
            compact=copy.deepcopy(full)
            for index,values in enumerate(([.1,.2,.1,.3,.1,.2],[.2,.1,.1,.2,.3,.1])):
                values=array('f',values)
                common=dict(layer=31,head=0,query=5,output_index=index,key_count=6)
                ref=append_row(root/'full.attn',values)
                full['attention'].append(dict(common,weights_ref=dict(ref,path='full.attn')))
                ref=append_row(root/'compact.attn',array('f',[values[0],values[3],values[5]]))
                compact['attention'].append(dict(common,weights_ref=dict(ref,path='compact.attn'),
                    weights_scope='image_keys',stored_key_count=3,weights_sum=math.fsum(values)))
            a,am=attention_analysis(full,root);b,bm=attention_analysis(compact,root)
            self.assertEqual(am,bm)
            for x,y in zip(a,b):
                for key in ['weights_sum','image_mass','frames','image_entropy_nats','image_entropy_normalized']:
                    self.assertEqual(x[key],y[key])
            compact['attention'][0]['stored_key_count']=2
            with self.assertRaises(ValueError):attention_analysis(compact,root)

    @unittest.skipIf(torch is None,'Requires the serving Torch environment')
    def test_gpu_projection_keeps_original_softmax_and_text_summaries(self):
        from sft.analysis.vllm_capture import image_projection
        for device in ['cpu']+(['cuda'] if torch.cuda.is_available() else []):
            weights=torch.softmax(torch.linspace(-8,2,64000,device=device),dim=0)
            indices=torch.arange(0,20400,device=device)
            visual,meta=image_projection(weights,indices)
            self.assertTrue((visual==weights[:20400].cpu().numpy()).all())
            values=weights.tolist();mass=math.fsum(values);other=math.fsum(values[20400:])
            self.assertAlmostEqual(meta['weights_sum'],mass,places=12)
            self.assertAlmostEqual(meta['non_image_mass'],other,places=12)
            expected=-sum(v/other*math.log(v/other) for v in values[20400:])
            self.assertAlmostEqual(meta['non_image_entropy_nats'],expected,places=10)
            self.assertLess(float(visual.sum()),.01)  # Would become one if incorrectly renormalized.


if __name__=='__main__':unittest.main()
