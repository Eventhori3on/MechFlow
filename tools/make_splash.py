# Builds Resources/splash/MechFlowSplash(@2x).png from the rendered artwork
# (Resources/splash/SplashArt.jpg - made by splash_scene.py + splash_render.py,
# see tools/README_splash.md) and the version number:
#   python3 tools/make_splash.py 0.27.0
# Needs Pillow and the Inter font (OFL).
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
S = 2                                    # drawn at 2x
W, H = 680 * S, 400 * S
FONTS = "/usr/share/fonts/opentype/inter/"
ART = os.path.join(HERE, "Resources", "splash", "SplashArt.jpg")
ICON = os.path.join(HERE, "Resources", "icons", "app", "MechFlow-256.png")


def font(name, px):
    return ImageFont.truetype(FONTS + name, int(px * S))


blue, orange = (95, 168, 232), (255, 184, 77)
im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
m = 6 * S
card = (m, m, W - m, H - m)
r = 14 * S
cw, ch = card[2] - card[0], card[3] - card[1]

# drop shadow
sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(sh).rounded_rectangle((card[0] + 4, card[1] + 8, card[2] - 4, card[3] + 4), r,
                                     fill=(0, 0, 0, 120))
im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5 * S)))

# the render, cover-fitted to the card
art = Image.open(ART).convert("RGBA")
sc = max(cw / art.width, ch / art.height)
art = art.resize((round(art.width * sc), round(art.height * sc)), Image.LANCZOS)
ox, oy = (art.width - cw) // 2, (art.height - ch) // 2
art = art.crop((ox, oy, ox + cw, oy + ch))

# left: a deep navy wash for the type, fading out across the picture
wash = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
wd = ImageDraw.Draw(wash)
for x in range(cw):
    t = x / cw
    a = 0 if t > 0.6 else int(238 * (1 - t / 0.6) ** 1.6)
    wd.line([(x, 0), (x, ch)], fill=(7, 13, 24, a))
art.alpha_composite(wash)
# a soft top vignette
top = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
td = ImageDraw.Draw(top)
for y in range(int(ch * 0.25)):
    td.line([(0, y), (cw, y)], fill=(5, 9, 16, int(120 * (1 - y / (ch * 0.25)) ** 2)))
art.alpha_composite(top)

mask = Image.new("L", (cw, ch), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), r, fill=255)
im.paste(art, card[:2], mask)
d = ImageDraw.Draw(im)
d.rounded_rectangle(card, r, outline=(255, 255, 255, 34), width=S)

# logo and name
x0 = card[0] + 30 * S
icon = Image.open(ICON).convert("RGBA").resize((52 * S, 52 * S), Image.LANCZOS)
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
glow.paste(Image.new("RGBA", icon.size, (95, 168, 232, 90)), (x0, card[1] + 38 * S), icon.split()[3])
im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10 * S)))
im.alpha_composite(icon, (x0, card[1] + 38 * S))
d.text((x0 + 64 * S, card[1] + 34 * S), "MechFlow", font=font("InterDisplay-Bold.otf", 46),
       fill=(255, 255, 255))
d.text((x0 + 66 * S, card[1] + 90 * S), "Mechanical design, the way", font=font("Inter-Medium.otf", 15),
       fill=(190, 208, 230))
d.text((x0 + 66 * S, card[1] + 110 * S), "you already work.", font=font("Inter-Medium.otf", 15),
       fill=(190, 208, 230))

# version and what's in it
d.text((x0 + 2 * S, card[1] + 176 * S), f"VERSION {VERSION}", font=font("Inter-SemiBold.otf", 12),
       fill=orange)
lines = ["Parts  ·  Sketches  ·  Drawings  ·  Assemblies",
         "Weldments  ·  Sheet Metal  ·  Routing  ·  Simulation"]
for i, t in enumerate(lines):
    d.text((x0 + 2 * S, card[1] + (198 + 19 * i) * S), t, font=font("Inter-Regular.otf", 12.5),
           fill=(165, 184, 208))

# accent line and footer
ly = card[3] - 46 * S
lw = 250 * S
for x in range(lw):
    t = x / lw
    c = tuple(int(a + (b - a) * t) for a, b in zip(blue, orange))
    al = int(255 * min(1, (1 - t) * 3))
    d.line([(x0 + x, ly), (x0 + x, ly + S)], fill=c + (al,))
f1 = font("Inter-SemiBold.otf", 12.5)
d.text((x0 + 2 * S, ly + 12 * S), "Built on FreeCAD", font=f1, fill=(255, 255, 255))
d.text((x0 + 2 * S + d.textlength("Built on FreeCAD", font=f1) + 8 * S, ly + 12 * S),
       "·  Free and open source", font=font("Inter-Regular.otf", 12.5), fill=(165, 184, 208))

out = os.path.join(HERE, "Resources", "splash")
im.save(os.path.join(out, "MechFlowSplash@2x.png"))
im.resize((W // 2, H // 2), Image.LANCZOS).save(os.path.join(out, "MechFlowSplash.png"))
prev = Image.new("RGBA", (W, H), (236, 238, 242, 255))
prev.alpha_composite(im)
prev.convert("RGB").save("/tmp/claude-0/splash_preview.png")
print("splash", VERSION)
