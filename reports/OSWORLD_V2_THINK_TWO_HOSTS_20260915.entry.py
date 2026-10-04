"""Run the existing V2 runner with the existing post-task renderer attached in memory."""
from pathlib import Path
import hashlib
import inspect
import json
import os
import sys

root = Path(os.environ['OSWORLD_HARNESS_ROOT']).resolve()
tool = Path(os.environ['CUA_TRAJECTORY_TOOL']).resolve()
os.chdir(root)
sys.path[:0] = [str(root), str(root / 'scripts/python'), str(tool)]
from sft.scripts.eval import after_task
import lib_run_single
import run_multienv_qwen_internal_agent as runner

native_render = after_task.render_task

def render_v2(task_dir, run_dir, config, example=None, runtime_args=None):
    # Only normalize exported metadata; the evaluator receives the original task object.
    metadata = dict(example or {})
    metadata['evaluator'] = metadata.get('evaluator') or {}
    if example is not None and hasattr(example, 'to_dict'):
        source = Path(inspect.getfile(type(example)))
        metadata['_criteria_source'] = {'path': str(source),
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'provenance': 'Actual V2 task class read at completion'}
        if not metadata['evaluator']:
            metadata['evaluator'] = {'func': type(example).__name__ + '.evaluate',
                                     'task_class_source': source.read_text()}
    return native_render(task_dir, run_dir, config, metadata, runtime_args)

after_task.render_task = render_v2
lib_run_single.run_single_example = after_task.wrap_task(lib_run_single.run_single_example)

if __name__ == '__main__':
    print('Per-task trajectory callback enabled; agent/evaluator source files unchanged.', flush=True)
    raise SystemExit(runner.main())
