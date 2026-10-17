# Builds docs/banner.png, the wide header image at the top of README.md, from
# the splash artwork (Resources/splash/SplashArt.jpg). No version number on it,
# so it doesn't need remaking for each release:
#   python3 tools/make_banner.py
# Needs Pillow and the Inter font (OFL).
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = "/usr/share/fonts/opentype/inter/"
ART = os.path.join(HERE, "Resources", "splash", "SplashArt.jpg")
ICON = os.path.join(HERE, "Resources", "icons", "app", "MechFlow-256.png")
S = 2
W, H = 880 * S, 300 * S
blue, orange = (95, 168, 232), (255, 184, 77)


def font(name, px):
    return ImageFont.truetype(FONTS + name, int(px * S))


# the render, fitted to the height and pushed to the right
art = Image.open(ART).convert("RGBA")
sc = H / art.height * 1.08
art = art.resize((round(art.width * sc), round(art.height * sc)), Image.LANCZOS)
im = Image.new("RGBA", (W, H), (9, 15, 26, 255))
ax = W - art.width + int(40 * S)
im.alpha_composite(art, (ax, (H - art.height) // 2))

# navy wash under the type, fading across the picture
wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
wd = ImageDraw.Draw(wash)
for x in range(W):
    t = (x - ax) / (W - ax) if x > ax else 0.0
    a = 255 if x < ax else (0 if t > 0.6 else int(255 * (1 - t / 0.6) ** 1.3))
    wd.line([(x, 0), (x, H)], fill=(9, 15, 26, a))
im.alpha_composite(wash)

# rounded card
r = 16 * S
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), r, fill=255)
out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
out.paste(im, (0, 0), mask)
d = ImageDraw.Draw(out)
d.rounded_rectangle((0, 0, W - 1, H - 1), r, outline=(255, 255, 255, 30), width=S)

x0, y0 = 44 * S, 52 * S
icon = Image.open(ICON).convert("RGBA").resize((56 * S, 56 * S), Image.LANCZOS)
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
glow.paste(Image.new("RGBA", icon.size, (95, 168, 232, 90)), (x0, y0 + 4 * S), icon.split()[3])
out.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10 * S)))
out.alpha_composite(icon, (x0, y0 + 4 * S))
d.text((x0 + 70 * S, y0 - 4 * S), "MechFlow", font=font("InterDisplay-Bold.otf", 50), fill=(255, 255, 255))
d.text((x0 + 2 * S, y0 + 84 * S), "Mechanical design, the way you already work.",
       font=font("Inter-Medium.otf", 17), fill=(200, 216, 236))
d.text((x0 + 2 * S, y0 + 112 * S), "A SOLIDWORKS-style workflow for FreeCAD",
       font=font("Inter-Regular.otf", 13.5), fill=(150, 172, 200))

ly = y0 + 150 * S
lw = 300 * S
for x in range(lw):
    t = x / lw
    c = tuple(int(a + (b - a) * t) for a, b in zip(blue, orange))
    d.line([(x0 + x, ly), (x0 + x, ly + S)], fill=c + (int(255 * min(1, (1 - t) * 3)),))
f = font("Inter-Regular.otf", 12)
for i, t in enumerate(["Parts  ·  Sketches  ·  Drawings  ·  Assemblies  ·  Weldments",
                       "Sheet Metal  ·  Routing  ·  Stress Check  ·  Motion Study"]):
    d.text((x0 + 2 * S, ly + (14 + 19 * i) * S), t, font=f, fill=(165, 184, 208))

os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
out.save(os.path.join(HERE, "docs", "banner.png"), optimize=True)
print("docs/banner.png", out.size)
