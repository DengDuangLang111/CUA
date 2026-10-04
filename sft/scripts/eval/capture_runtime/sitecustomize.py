"""Enable the shared recorder/callback in native benchmark processes and workers."""
import os
if os.environ.get('CUA_INSPECTION_CONFIG'):
    try:
        if os.environ.get('CUA_TASK_ATTEMPT'):
            from docker.models.containers import ContainerCollection
            from functools import wraps
            if not getattr(ContainerCollection.run, '_cua_labelled', False):
                original_run = ContainerCollection.run
                @wraps(original_run)
                def labelled_run(self, *args, **kwargs):
                    labels = dict(kwargs.get('labels') or {})
                    labels.update({'org.cua.run': os.environ['CUA_RUN_ID'],
                                   'org.cua.attempt': os.environ['CUA_TASK_ATTEMPT']})
                    kwargs['labels'] = labels
                    return original_run(self, *args, **kwargs)
                labelled_run._cua_labelled = True
                ContainerCollection.run = labelled_run
        import lib_run_single
        from sft.scripts.eval.after_task import wrap_task
        lib_run_single.run_single_example = wrap_task(lib_run_single.run_single_example)
    except Exception:
        import traceback
        traceback.print_exc()
        os._exit(78)
