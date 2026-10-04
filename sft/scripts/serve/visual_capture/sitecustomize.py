"""Opt-in startup for API server and vLLM's spawned workers."""
import os
if os.environ.get('CUA_VLLM_CAPTURE_CONFIG'):
    try:
        from sft.analysis.vllm_capture import install
        install()
    except Exception:
        import traceback
        traceback.print_exc()
        os._exit(78)  # Never serve a diagnostic endpoint after collector setup failed.
