# histcomp: graduated history-image resolution (route B, monkeypatch).
#
# Idea: with img10/fold1 every history frame is encoded at native ~2040 tokens
# (10 frames = 20,400 vision tokens). Older frames are context, not where the
# action happens, so we down-res them by age. The CURRENT frame stays full
# resolution -> no grounding/coordinate impact.
#
# Schedule by age (0 = newest frame in the sample; index into inputs.images is
# oldest-first, so age = M-1-index):
#   age 0-1 : full 2040 tok (max_pixels 2,088,960 = native 1920x1088)
#   age 2-4 : 1/2  1020 tok (1,044,480)
#   age 5-7 : 1/4   510 tok (  522,240)
#   age 8+  : 1/8   255 tok (  261,120)   <- oldest, user set 1/8
# img10 total = 2*2040 + 3*1020 + 3*510 + 2*255 = 9180 tok  (vs 20,400; -55%).
#
# Mechanism: qwen_vl_utils.fetch_image reads a per-image ele["max_pixels"]
# (vision_process.py:132), falling back to the global env var when absent. swift
# feeds one global max_pixels to every image (qwen.py replace_tag); we override
# replace_tag's image branch to inject a per-age max_pixels. 32 px/token in this
# pipeline (1920x1088 = 2040 tok, verified), so max_pixels = tokens * 32**2.
#
# Also keeps cuDNN SDPA disabled (2x4 topology crashes in the cuDNN attn kernel).
# PYTHONPATH=<this dir> makes Python import this sitecustomize at startup.
# On patch failure we RAISE (loud), never silently fall back to uniform res.
import sys

import torch
torch.backends.cuda.enable_cudnn_sdp(False)

_SCHED = [(1, 2088960), (4, 1044480), (7, 522240)]   # (max_age_inclusive, max_pixels)
_OLDEST = 261120                                     # age >= 8  -> 1/8

def _max_pixels_for_age(age):
    for thr, mp in _SCHED:
        if age <= thr:
            return mp
    return _OLDEST

_DBG = {'n': 0}

from swift.template.templates.qwen import Qwen2VLTemplate  # raises if unavailable -> loud
from qwen_vl_utils import fetch_image

_orig_replace_tag = Qwen2VLTemplate.replace_tag

def _patched_replace_tag(self, media_type, index, inputs):
    if media_type == 'image':
        kwargs = {'image_patch_size': self.processor.image_processor.patch_size} \
            if getattr(self, 'version', None) == 'v3' else {}
        if self.mode == 'vllm':
            inputs.mm_processor_kwargs['do_resize'] = False
        M = len(inputs.images)
        age = M - 1 - index
        mp = _max_pixels_for_age(age)
        ele = {'image': inputs.images[index], **inputs.chat_template_kwargs, 'max_pixels': mp}
        img = fetch_image(ele, **kwargs)
        inputs.images[index] = img
        if _DBG['n'] < 12:
            try:
                w, h = img.size
                print(f"[histcomp] index={index}/{M} age={age} max_pixels={mp} -> {w}x{h} = {(w // 32) * (h // 32)} tok",
                      flush=True)
            except Exception:
                pass
            _DBG['n'] += 1
        if self.mode == 'lmdeploy':
            return ['<|vision_start|>', [-100], '<|vision_end|>']
        return ['<|vision_start|><|image_pad|><|vision_end|>']
    return _orig_replace_tag(self, media_type, index, inputs)

Qwen2VLTemplate.replace_tag = _patched_replace_tag
print("[histcomp] Qwen2VLTemplate.replace_tag patched: graduated history resolution "
      "(age0-1 full / 2-4 half / 5-7 quarter / 8+ 1/8), cuDNN SDPA off", file=sys.stderr, flush=True)
