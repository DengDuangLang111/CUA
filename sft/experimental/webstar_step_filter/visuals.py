"""Create WebSTAR-style action overlays and local crops.

The implementation is original but follows the paper's published visual
interface: action labels, red target markers/arrows, and a 200px current-action
crop. Coordinates come from the actions actually executed by the harness.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw


POINT_RE = re.compile(
    r"pyautogui\.(click|rightClick|doubleClick|tripleClick|moveTo|dragTo)"
    r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)


def action_points(actions):
    points = []
    for action in actions:
        match = POINT_RE.search(str(action))
        if match:
            points.append({
                "kind": match.group(1),
                "x": int(float(match.group(2))),
                "y": int(float(match.group(3))),
                "raw": str(action),
            })
    return points


def _png_bytes(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def annotate_action(image_path, actions, crop_size=200):
    """Return `(annotated_png, crop_png_or_none)` for one proposed step."""
    image = Image.open(Path(image_path)).convert("RGB")
    draw = ImageDraw.Draw(image)
    action_list = [str(x) for x in actions]
    label = " | ".join(action_list)[:220] or "NO EXECUTED ACTION"
    box_w = min(image.width - 8, max(180, 7 * len(label) + 12))
    draw.rectangle((4, 4, 4 + box_w, 28), fill=(16, 110, 55))
    draw.text((9, 9), label, fill="white")

    points = action_points(action_list)
    previous = None
    for idx, point in enumerate(points, 1):
        x = max(0, min(image.width - 1, point["x"]))
        y = max(0, min(image.height - 1, point["y"]))
        radius = 12
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     outline=(255, 40, 40), width=4)
        draw.rectangle((x + 9, y - 20, x + 27, y - 3), fill=(18, 130, 65))
        draw.text((x + 14, y - 19), str(idx), fill="white")
        if previous is not None and point["kind"].lower() in {"moveto", "dragto"}:
            draw.line((previous[0], previous[1], x, y),
                      fill=(255, 40, 40), width=4)
        previous = (x, y)

    crop = None
    if points:
        current = points[-1]
        x = max(0, min(image.width - 1, current["x"]))
        y = max(0, min(image.height - 1, current["y"]))
        half = crop_size // 2
        left = max(0, min(image.width - crop_size, x - half))
        top = max(0, min(image.height - crop_size, y - half))
        right = min(image.width, left + crop_size)
        bottom = min(image.height, top + crop_size)
        crop_img = image.crop((left, top, right, bottom))
        if crop_img.size != (crop_size, crop_size):
            crop_img = crop_img.resize((crop_size, crop_size))
        crop = _png_bytes(crop_img)

    return _png_bytes(image), crop
