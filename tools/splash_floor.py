# Floor texture for the splash render: a studio vignette with the model's
# ground shadow baked in, from splash_render.py's top-down height map.
#   python3 tools/splash_floor.py height.npy floor.png
# Higher parts cast softer, lighter shadows; parts on the floor a tight,
# dark contact shadow.
import sys
import numpy as np
from PIL import Image, ImageFilter

h = np.load(sys.argv[1])[::-1]             # VTK rows run bottom-up; PNG rows top-down
N = h.shape[0]
HALF = 7000.0
px = 2 * HALF / N                          # mm per pixel


def blur(mask, mm):
    im = Image.fromarray((mask * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(max(0.5, mm / px))), dtype=np.float32) / 255


light = np.ones_like(h)
for lo, hi, soft, dark in ((-0.5, 60, 20, 0.85), (60, 400, 70, 0.65), (400, 1500, 220, 0.5),
                           (1500, 1e9, 450, 0.4)):
    m = ((h >= lo) & (h < hi)).astype(np.float32)
    if m.any():
        light *= 1 - dark * blur(m, soft)
# a broad, faint occlusion under the whole footprint
light *= 1 - 0.7 * blur((h >= 0).astype(np.float32), 600)
light *= 1 - 0.35 * blur((h >= 0).astype(np.float32), 1600)

# vignette: lighter in the middle, the edge colour at the rim
y, x = np.mgrid[0:N, 0:N]
r = np.hypot(x - N / 2 + N * 0.04, y - N / 2) / (N / 2)
t = np.clip((r - 0.12) / 0.85, 0, 1) ** 1.4
centre = np.array([0.42, 0.48, 0.58])
edge = np.array([0.07, 0.09, 0.13])
col = centre[None, None] * (1 - t[..., None]) + edge[None, None] * t[..., None]
col = col * light[..., None]
Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8)).save(sys.argv[2])
print("floor", sys.argv[2])
