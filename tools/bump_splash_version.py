# Changes the VERSION text on the existing splash images (when the part
# render make_splash.py needs isn't to hand): covers the old text with a
# patch of the card from further right (same gradient row, grid in step)
# and writes the new version.   python3 tools/bump_splash_version.py 0.26.0
import sys
from PIL import Image, ImageDraw, ImageFont
S = 2
ver = sys.argv[1]
src = "Resources/splash/MechFlowSplash@2x.png"
im = Image.open(src).convert("RGBA")
box = (34 * S, 226 * S, 154 * S, 245 * S)
shift = 200 * S                          # whole grid blocks, so the lines line up
patch = im.crop((box[0] + shift, box[1], box[2] + shift, box[3]))
im.paste(patch, box[:2])
f = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 12 * S)
ImageDraw.Draw(im).text((36 * S, 228 * S), f"VERSION {ver}", font=f, fill=(47, 111, 176))
im.save(src)
im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save("Resources/splash/MechFlowSplash.png")
print("ok")
