"""Large attention storage checks without a GPU or model calls."""
from array import array
import copy
import json
import re
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from sft.analysis.attention_store import append_row, read_row, file_hash
from sft.analysis.visual_signals import attention_rows, attention_overviews
from sft.analysis.trajectory_viewer import viewer_server


class StoreTests(unittest.TestCase):
    def test_float32_buffer_is_byte_identical_to_legacy_list_writer(self):
        import zlib
        with tempfile.TemporaryDirectory() as tmp:
            values = array('f', [0., -0., 1., 1e-40, .125, .33333333] * 100)
            old = Path(tmp) / 'old.attn'
            new = Path(tmp) / 'new.attn'
            for chunk in (values, memoryview(values)[::2]):
                old_ref = append_row(old, list(chunk))
                new_ref = append_row(new, chunk)
                self.assertEqual(old_ref, new_ref)
            self.assertEqual(old.read_bytes(), new.read_bytes())
            self.assertEqual(file_hash(old), file_hash(new))
            self.assertEqual(zlib.decompress(new.read_bytes()[:new_ref['offset']]), values.tobytes())

    def test_binary_export_keeps_task_html_small_and_loads_signals_per_decision(self):
        from sft.tests.test_visual_signals import fixture
        from sft.analysis.visual_signals import export_runs
        from sft.analysis.trajectory_viewer import add_graphs, task_html
        with tempfile.TemporaryDirectory() as tmp:
            root=fixture(Path(tmp)/'results');task=root/'fixture-run-a/chrome/fixture-task'
            path=task/'visual_signals.jsonl';record=json.loads(path.read_text());record['output_token_ids']=[7,8]
            blob=task/'capture/weights.attn';blob.parent.mkdir()
            for i,row in enumerate(record['attention']):
                row['output_index']=i
                row['weights_ref']=dict(append_row(blob,row.pop('weights')),path='capture/weights.attn')
            for row in record['attention']:row['weights_ref']['sha256']=file_hash(blob)
            path.write_text(json.dumps(record)+'\n')
            bundle=add_graphs(export_runs(root,['fixture-run-a'],'test','/assets'))
            self.assertEqual(bundle['trace_steps'][1]['signal_status'],'matched')
            output=Path(tmp)/'pages';output.mkdir();relative='tasks/'+'a'*32+'.json'
            original=copy.deepcopy(bundle);page=task_html(bundle,relative,output)
            payload=json.loads(re.search(r'id="trajectory-data">(.*?)</script>',page,re.S)[1])
            frame=payload['episodes'][0]['frames'][1]
            self.assertIsNone(frame['signals'])
            saved=json.loads((output/frame['signals_url']).read_text())
            self.assertIn('/assets/',saved['attention'][0]['weights_ref']['src'])
            self.assertNotIn('weights',saved['attention'][0]['frames'][0])
            self.assertIn('weights',saved['attention_overviews'][0]['frames'][0])
            self.assertEqual(bundle,original)

    def test_float32_roundtrip_ranges_aggregation_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'weights.attn';rows=[]
            for index,weights in enumerate(([.2,.3,.5],[.4,.1,.3,.2])):
                ref=append_row(path,weights)
                rows.append(dict(layer=63,head=0,query=len(weights)-1,output_index=index,key_count=len(weights),
                                 weights_ref=dict(ref,path=path.name,sha256='source-hash')))
                self.assertEqual(read_row(rows[-1],root),array('f',weights))
            signal=dict(images=[dict(id='history',key_indices=[0],token_count=1),
                                dict(id='current',key_indices=[2],token_count=1)],attention=rows,output_token_ids=[7,8])
            original=copy.deepcopy(signal)
            summary=attention_rows(signal,root)
            self.assertNotIn('weights',summary[0])
            self.assertNotIn('weights',summary[0]['frames'][0])
            self.assertAlmostEqual(summary[0]['weights_sum'],1)
            average=attention_overviews(signal,root)[0]
            self.assertTrue(average['complete'])
            self.assertAlmostEqual(average['frames'][0]['weights'][0],.3)
            self.assertAlmostEqual(average['frames'][1]['weights'][0],.4)
            self.assertEqual(signal,original)
            self.assertGreater(rows[1]['weights_ref']['offset'],0)
            before=file_hash(path);data=bytearray(path.read_bytes());data[1]^=1;path.write_bytes(data)
            self.assertNotEqual(file_hash(path),before)
            with self.assertRaisesRegex(ValueError,'corrupt'):read_row(rows[0],root)
            bad=copy.deepcopy(rows[1]);bad['weights_ref']['path']='../outside.attn'
            with self.assertRaisesRegex(ValueError,'path'):read_row(bad,root)

    def test_allowlisted_http_range_serves_only_requested_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'pages';output.mkdir();path=root/'weights.attn'
            append_row(path,[.1,.9]);ref=append_row(path,[.2,.3,.5])
            (output/'manifest.json').write_text(json.dumps({'root':str(root),'assets':{'weights.attn':str(path)}}))
            server=viewer_server(output,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/assets/weights.attn',
                    headers={'Range':f"bytes={ref['offset']}-{ref['offset']+ref['length']-1}"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status,206)
                    self.assertEqual(response.read(),path.read_bytes()[ref['offset']:ref['offset']+ref['length']])
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
