"""Offline deployment contract tests. No SSH, GPU allocation or model inference."""
import json
import base64
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

from sft.scripts.serve import prepare_model as prep


class PrepareModelTests(unittest.TestCase):
    def test_status_uses_recorded_ports_and_heterogeneous_capacities(self):
        base,_=prep.paths(self.config);base.mkdir(parents=True)
        prep.write(base/'deployment.json',dict(config=self.config))
        prep.write(base/'job.json',dict(services=[dict(job_id='1',port=9010,max_num_seqs=2),dict(job_id='2',port=9020,max_num_seqs=1)]))
        ports=[]
        def probe(config,record,port):
            ports.append(port);return dict(record,ready=True,eval_model=dict(max_parallel_requests=record['max_num_seqs']))
        with patch.object(prep,'probe_service',side_effect=probe):result=prep.service_status(self.config)
        self.assertEqual(ports,[9010,9020]);self.assertEqual(result['eval_model']['max_parallel_requests'],3)

    def test_held_allocation_is_owned_bounded_and_submitted_once(self):
        import os
        from types import SimpleNamespace
        self.config['allocation_job']='123'
        self.config['serving'].update(replicas=3,tensor_parallel=1)
        self.config['slurm']['cpus-per-task']=2
        base,model=prep.paths(self.config);model.mkdir(parents=True)
        prep.write(base/'capture.json',{})
        detail='JobState=RUNNING NumNodes=1 NumCPUs=6 UserId=test({}) AllocTRES=cpu=6,gres/gpu=3 '.format(os.getuid())
        with patch.object(prep,'command',return_value=detail),patch.object(prep.subprocess,'Popen',return_value=SimpleNamespace(pid=12345)) as call:
            first=prep.serve_held(self.config)
            self.assertEqual(first,prep.serve_held(self.config))
            self.assertEqual(call.call_count,1)
            self.assertIn('--ntasks=1',first['command'])
            self.assertIn('--cpus-per-task=6',first['command'])
            self.assertTrue(any(x.startswith('--gpus-per-node=') and x.endswith(':3') for x in first['command']))
        self.config['serving']['port']+=1
        with self.assertRaisesRegex(ValueError,'config changed'):prep.serve_held(self.config)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = prep.read(Path(prep.__file__).with_name('prepare_model.example.json'))
        for key in ('checkpoint', 'assets', 'destination_root', 'container', 'tool_root', 'key_file', 'ssh_socket'):
            self.config[key] = str(self.root / key)
        self.config['bind_root'] = str(self.root)
        source = Path(self.config['checkpoint'])
        source.mkdir()
        Path(self.config['assets']).mkdir()
        tensor = {'model.visual.weight': {'dtype': 'BF16', 'shape': [1], 'data_offsets': [0, 2]}}
        header = json.dumps(tensor).encode()
        (source / 'model.safetensors').write_bytes(struct.pack('<Q', len(header)) + header + b'\0\0')
        for name, value in {'config.json': {}, 'trainer_state.json': {'global_step': 306},
                            'tokenizer.json': {}, 'tokenizer_config.json': {'chat_template': 'test'},
                            'preprocessor_config.json': {}}.items():
            prep.write(source / name, value)
        (source / 'optimizer.pt').write_bytes(b'do not transfer')
        Path(self.config['container']).touch()
        key = Path(self.config['key_file'])
        key.write_text('fixture-key')
        key.chmod(0o600)
        for name in ('sft/scripts/serve/visual_capture/sitecustomize.py',
                     'sft/analysis/vllm_capture.py', 'sft/analysis/attention_store.py'):
            path = Path(self.config['tool_root']) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def stage(self):
        files, manifest = prep.bundle(self.config)
        state = prep.remote_operation(self.config, 'init', manifest)
        for name, path in files.items():
            shutil.copyfile(path, Path(state['destination']) / name)
        return manifest

    def test_explicit_step_assets_and_inference_only(self):
        prep.validate(self.config)
        source = Path(self.config['checkpoint'])
        assets = Path(self.config['assets'])
        (source / 'preprocessor_config.json').rename(assets / 'preprocessor_config.json')
        files, manifest = prep.bundle(self.config)
        self.assertEqual(files['preprocessor_config.json'].parent, assets)
        self.assertNotIn('optimizer.pt', manifest['files'])
        self.config['expected_step'] = 307
        with self.assertRaisesRegex(ValueError, 'step mismatch'):
            prep.bundle(self.config)

    def test_truncated_weights_and_bad_index_rejected(self):
        source = Path(self.config['checkpoint'])
        weights = source / 'model.safetensors'
        weights.write_bytes(weights.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'Incomplete shard'):
            prep.bundle(self.config)
        prep.write(source / 'model.safetensors.index.json', {'weight_map': {'x': '../bad.safetensors'}})
        with self.assertRaisesRegex(ValueError, 'Unsafe shard'):
            prep.bundle(self.config)

    def test_checksum_failure_cannot_publish_or_submit(self):
        manifest = self.stage()
        base, model = prep.paths(self.config)
        (base / 'upload' / 'model.safetensors').write_bytes(b'corrupt')
        with patch.object(prep, 'command') as call:
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                prep.remote_operation(self.config, 'publish', manifest)
        call.assert_not_called()
        self.assertFalse(model.exists())

    def test_submit_once_and_reject_rebinding(self):
        manifest = self.stage()
        with patch.object(prep, 'command', return_value='12345') as call:
            one = prep.remote_operation(self.config, 'publish', manifest)
            two = prep.remote_operation(self.config, 'publish', manifest)
        self.assertEqual(one, two)
        self.assertEqual(call.call_count, 1)
        self.assertTrue(prep.paths(self.config)[1].is_dir())
        manifest['files']['config.json']['sha256'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'already bound'):
            prep.remote_operation(self.config, 'init', manifest)

    def test_uncertain_submission_never_submits_again(self):
        manifest = self.stage()
        with patch.object(prep, 'command', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                prep.remote_operation(self.config, 'publish', manifest)
        with patch.object(prep, 'command') as call:
            with self.assertRaisesRegex(ValueError, 'outcome uncertain'):
                prep.remote_operation(self.config, 'publish', manifest)
        call.assert_not_called()

    def test_script_valid_capture_switch_and_no_secret(self):
        script = prep.serving_script(self.config)
        subprocess.run(['bash', '-n'], input=script, text=True, check=True)
        self.assertIn('--no-enable-prefix-caching', script)
        self.assertIn('APPTAINERENV_FLASHINFER_WORKSPACE_BASE', script)
        self.assertIn('APPTAINERENV_TRITON_CACHE_DIR', script)
        self.assertNotIn('fixture-key', script)
        self.assertNotIn('--api-key', script)
        self.config['capture'] = False
        script = prep.serving_script(self.config)
        self.assertNotIn('CUA_VLLM_CAPTURE_CONFIG', script)
        self.assertNotIn('--enforce-eager', script)

    def test_metadata_readiness_is_not_a_generation_test(self):
        manifest = self.stage()
        with patch.object(prep, 'command', return_value='12345'):
            prep.remote_operation(self.config, 'publish', manifest)
        with patch.object(prep, 'command', return_value='JobState=PENDING NodeList=(null)'), patch.object(prep, 'urlopen') as api:
            state = prep.service_status(self.config)
        self.assertFalse(state['ready'])
        api.assert_not_called()
        self.config['capture'] = False
        base, model = prep.paths(self.config)
        manifest['config'] = self.config
        prep.write(base / 'deployment.json', manifest)
        from io import BytesIO
        models = {'data': [{'id': self.config['model_id'], 'root': str(model), 'max_model_len': 262144}]}
        with patch.object(prep, 'command', side_effect=['JobState=RUNNING NodeList=g123', 'g123']), \
             patch.object(prep, 'urlopen', return_value=BytesIO(json.dumps(models).encode())) as api:
            state = prep.service_status(self.config)
        self.assertTrue(state['ready'])
        self.assertEqual(api.call_args[0][0].full_url, 'http://g123:8054/v1/models')

    def test_prepare_resumes_with_one_submission_and_no_retransfer(self):
        config_file = self.root / 'config.json'
        prep.write(config_file, self.config)
        calls = []
        def fake_command(args, **kwargs):
            calls.append(args)
            if args[0] == 'rsync':
                destination = prep.paths(self.config)[0] / 'upload'
                for name in kwargs['input'].splitlines():
                    shutil.copyfile(Path(args[-2]) / name, destination / name)
            return '12345' if args[0] == 'sbatch' else ''
        with patch.object(sys, 'argv', ['prepare_model.py', 'prepare', '--config', str(config_file)]), \
             patch.object(prep, 'command', side_effect=fake_command), \
             patch.object(prep, 'remote', side_effect=prep.remote_operation), patch('builtins.print'):
            prep.main()
            prep.main()
        self.assertEqual(sum(c[0] == 'sbatch' for c in calls), 1)
        transfers = [c for c in calls if c[0] == 'rsync']
        self.assertEqual(len(transfers), 1)
        self.assertIn('--partial', transfers[0])
        self.assertIn('--checksum', transfers[0])

    def test_remote_file_can_execute_from_ssh_stdin(self):
        _, manifest = prep.bundle(self.config)
        request = base64.b64encode(json.dumps({'config': self.config, 'payload': manifest}).encode()).decode()
        result = subprocess.run([sys.executable, '-', '_remote', 'init', request],
                                input=Path(prep.__file__).read_text(), text=True, capture_output=True, check=True)
        self.assertFalse(json.loads(result.stdout)['published'])

    def test_missing_master_fails_once_without_login(self):
        with patch.object(prep, 'command', side_effect=ValueError('no master')) as call:
            with self.assertRaisesRegex(ValueError, 'no master'):
                prep.remote(self.config, 'status')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args[0][0][-3:], ['-O', 'check', self.config['ssh_host']])

    def test_lazy_capture_route_uses_only_an_unregistered_model(self):
        from io import BytesIO
        from urllib.error import HTTPError
        manifest = self.stage()
        with patch.object(prep, 'command', return_value='12345'):
            prep.remote_operation(self.config, 'publish', manifest)
        model = prep.paths(self.config)[1]
        models = {'data': [{'id': self.config['model_id'], 'root': str(model), 'max_model_len': 262144}]}
        replies = [BytesIO(json.dumps(models).encode()), HTTPError('route', 404, '', {}, None),
                   HTTPError('chat', 404, '', {}, None), HTTPError('route', 405, '', {'Allow': 'GET'}, None)]
        with patch.object(prep, 'command', side_effect=['JobState=RUNNING NodeList=g123', 'g123']), \
             patch.object(prep, 'urlopen', side_effect=replies) as api:
            state = prep.service_status(self.config)
        self.assertTrue(state['ready'])
        self.assertEqual([c.args[0].get_method() for c in api.call_args_list], ['GET', 'OPTIONS', 'POST', 'OPTIONS'])
        self.assertNotEqual(json.loads(api.call_args_list[2].args[0].data)['model'], self.config['model_id'])

    def test_three_single_gpu_replicas_share_weights_and_submit_once_each(self):
        self.config['serving'].update(replicas=3, tensor_parallel=1, max_num_seqs=3)
        self.config['slurm']['gres'] = 'gpu:l40s:1'
        prep.validate(self.config)
        manifest = self.stage()
        with patch.object(prep, 'command', side_effect=['101', '102', '103']) as call:
            result = prep.remote_operation(self.config, 'publish', manifest)
            again = prep.remote_operation(self.config, 'publish', manifest)
        self.assertEqual(result, again)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(len({s['checkpoint'] for s in result['services']}), 1)
        base, model = prep.paths(self.config)
        for i in range(3):
            text = (base / f'serve-r{i+1}.sbatch').read_text()
            self.assertIn('#SBATCH --gres=gpu:l40s:1', text)
            self.assertIn(f'--port {8054+i}', text)
            self.assertIn('--tensor-parallel-size 1', text)
            self.assertIn('--max-num-seqs 3', text)
        with patch.object(prep, 'probe_service', side_effect=[
                {'ready': True, 'eval_model': {'max_parallel_requests': 3}},
                {'ready': False}, {'ready': True}]) as probe:
            state = prep.service_status(self.config)
        self.assertFalse(state['ready'])
        self.assertEqual(probe.call_count, 3)


if __name__ == '__main__':
    unittest.main()
