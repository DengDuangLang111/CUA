"""Integration checks for the shared catalog and unmodified evidence routes."""
import hashlib
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sft.analysis.trajectory_catalog import catalog_server
from sft.analysis.trajectory_viewer import viewer_server, index_html
from sft.analysis.visual_signals import write_json
from sft.scripts.eval.after_task import render_task
from sft.tests.test_visual_signals import fixture


class CatalogTests(unittest.TestCase):
    def test_same_campaign_groups_host_shards_without_merging_protocols(self):
        name = 'model--verified--eval100-n100--20260917T111039Z-75ef6328f5ea'
        index = dict(runs={}, trajectories=[], sources=[])
        for host, count, full in [('windows', 2, 1), ('workstation', 11, 9)]:
            run_id = host + ':run-local'
            index['sources'].append(dict(id=host, label=host, collection='eval', online=True))
            index['runs'][run_id] = dict(canonical_name='9b-full-r5', checkpoint='/fixed/checkpoint',
                model_boundary={'model_id': 'fixed-model', 'precision': 'BF16'},
                args=dict(image_max=10, fold_size=1, base_url='http://' + host,
                          result_dir='/'+host, test_all_meta_path='/'+host+'/panel.json'))
            for n in range(count):
                index['trajectories'].append(dict(run_id=run_id, run='/'+host+'/'+name,
                    catalog_source=host, collection='eval', source=host, episode=0,
                    task_path=host+'/'+str(n), task_id=host+str(n), score=1 if n < full else 0,
                    html='/sources/'+host+'/task-'+str(n).zfill(32)+'.html'))
        def groups(data):
            text = index_html(data).split('const allGroups=(', 1)[1]
            return json.JSONDecoder().raw_decode(text)[0]
        merged = groups(index)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]['entries']), 13)
        self.assertEqual(sum(r['score'] for r in merged[0]['entries']), 10)
        self.assertEqual(set(merged[0]['member_run_ids']), set(index['runs']))
        self.assertEqual({r['source'] for r in merged[0]['entries']}, {'windows', 'workstation'})
        self.assertTrue(all(r['html'].startswith('/sources/'+r['source']+'/') for r in merged[0]['entries']))
        for change in ('protocol', 'checkpoint', 'campaign'):
            other = copy.deepcopy(index)
            if change == 'protocol':
                other['runs']['windows:run-local']['args'].update(image_max=20, fold_size=10)
            elif change == 'checkpoint':
                other['runs']['windows:run-local']['checkpoint'] = '/different/checkpoint'
            else:
                for row in other['trajectories']:
                    if row['source'] == 'windows':row['run'] += '-another-run'
            self.assertEqual(len(groups(other)), 2, change)

    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.raw = fixture(self.root / "results")
        self.config = dict(results_root=str(self.raw), output_dir=str(self.root / "pages"), source="fixture", collection="eval")
        self.run = self.raw / "fixture-run-a"
        render_task(self.run / "chrome/fixture-task", self.run, self.config)
        self.source = self.start(viewer_server(self.root / "pages", 0))
        self.catalog_file = self.root / "catalog.json"
        self.sources = [dict(id="workstation", label="Workstation", url=self.source, collection="test")]
        write_json(self.catalog_file, dict(sources=self.sources))
        self.server = catalog_server(self.catalog_file, 0)
        self.url = self.start(self.server)

    def get(self, path, headers=None):
        return urlopen(Request(self.url + path, headers=headers or {}), timeout=10)

    def test_live_merge_classification_images_ranges_and_navigation(self):
        index = json.load(self.get("/index.json"))
        self.assertEqual({r["collection"] for r in index["trajectories"]}, {"eval"})
        entry = index["trajectories"][0]
        self.assertTrue(entry["html"].startswith("/sources/workstation/"))
        page = self.get(entry["html"]).read().decode()
        self.assertIn('"collection": "eval"', page)
        self.assertIn('"prefix": "/sources/workstation"', page)
        self.assertIn('sourceUrl(src)', page)
        self.assertIn(entry["run_id"], page)
        self.assertIn("context.indexKey", page)
        self.assertEqual(json.load(self.get("/sources/workstation/index.json")), index)
        manifest = json.loads((self.root / "pages/manifest.json").read_text())
        asset, original = next(iter(manifest["assets"].items()))
        with self.get("/sources/workstation/assets/" + asset) as response:
            self.assertEqual(hashlib.sha256(response.read()).digest(), hashlib.sha256(Path(original).read_bytes()).digest())
        binary = self.raw / "weights.attn"
        binary.write_bytes(bytes(range(100)))
        manifest["assets"]["weights.attn"] = str(binary)
        write_json(self.root / "pages/manifest.json", manifest)
        with self.get("/sources/workstation/assets/weights.attn", {"Range": "bytes=10-19"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 10-19/100")
            self.assertEqual(response.read(), bytes(range(10, 20)))
        # Another completed run is collected without editing/restarting the catalog.
        run = self.raw / "fixture-run-b"
        render_task(run / "chrome/fixture-task", run, {**self.config, "collection": "test"})
        self.server.catalog.expires = 0
        later = json.load(self.get("/index.json"))
        self.assertEqual(len(later["trajectories"]), 2 * len(index["trajectories"]))
        self.assertEqual({r["collection"] for r in later["trajectories"]}, {"eval", "test"})
        html = self.get("/index.html?collection=test").read().decode()
        self.assertIn("测试 / 功能调试", html)
        self.assertIn("cua-trajectory-index-", html)

    def test_offline_cache_recovery_and_source_namespaces(self):
        initial = json.load(self.get("/index.json"))
        self.sources[0]["url"] = "http://127.0.0.1:1"
        write_json(self.catalog_file, dict(sources=self.sources))
        self.server.catalog.expires = 0
        offline = json.load(self.get("/index.json"))
        self.assertEqual(offline["trajectories"], initial["trajectories"])
        self.assertFalse(offline["sources"][0]["online"])
        self.assertTrue(offline["sources"][0]["cached"])
        self.sources[0]["url"] = self.source
        self.sources.append(dict(id="other", label="Other host", url=self.source, collection="eval"))
        write_json(self.catalog_file, dict(sources=self.sources))
        self.server.catalog.expires = 0
        restored = json.load(self.get("/index.json"))
        self.assertTrue(all(s["online"] for s in restored["sources"]))
        self.assertEqual(len(restored["runs"]), 2)
        self.assertEqual(len({r["html"] for r in restored["trajectories"]}), len(restored["trajectories"]))

    def test_whitelist_and_invalid_collection(self):
        for path in ("/sources/workstation/manifest.json", "/sources/workstation/assets/%2e%2e/secret", "/sources/unknown/index.json"):
            with self.assertRaises(HTTPError) as exc:
                self.get(path)
            self.assertEqual(exc.exception.code, 404)
        with self.assertRaisesRegex(ValueError, "collection"):
            render_task(self.run / "chrome/fixture-task", self.run, {**self.config, "collection": "typo"})


if __name__ == "__main__":
    unittest.main()
