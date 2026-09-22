"""Disable autograd only inside the fully frozen Qwen3.5 vision tower."""
import os
import torch

torch.backends.cuda.enable_cudnn_sdp(False)

if os.environ.get('FROZEN_VISION_NO_GRAD') == '1':
    from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5VisionModel

    original = Qwen3_5VisionModel.forward

    def frozen_forward(self, *args, **kwargs):
        assert not any(p.requires_grad for p in self.parameters()), 'Vision tower must be fully frozen'
        x = args[0] if args else kwargs.get('hidden_states')
        assert isinstance(x, torch.Tensor) and not x.requires_grad, 'Input gradient would be cut'
        if not getattr(self, '_nograd_logged', False):
            print(f'[frozen-vision-no-grad]; input_requires_grad={getattr(x, "requires_grad", None)} '
                  f'grad_enabled={torch.is_grad_enabled()}', flush=True)
            self._nograd_logged = True
        with torch.no_grad():
            return original(self, *args, **kwargs)

    Qwen3_5VisionModel.forward = frozen_forward
