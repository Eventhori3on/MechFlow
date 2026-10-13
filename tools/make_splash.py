# Regenerates Resources/splash/MechFlowSplash(@2x).png.
# Needs Pillow and the Inter font (OFL). The part picture is a FreeCAD render
# saved with a transparent background (ActiveView.saveImage(..., "Transparent")).
# Update the VERSION text for each release.
from PIL import Image, ImageDraw, ImageFont, ImageFilter
S = 2                                    # draw at 2x
W, H = 680 * S, 400 * S
F = "/usr/share/fonts/opentype/inter/"
def font(name, px): return ImageFont.truetype(F + name, px * S)
navy, blue, mid, light, orange, grey = (22, 44, 74), (47, 111, 176), (31, 79, 128), (95, 168, 232), (255, 184, 77), (96, 110, 128)

im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
card = (0, 30 * S, 560 * S, 380 * S)
r = 16 * S
# soft shadow under the card
sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle((card[0] + 6, card[1] + 10, card[2] - 6, card[3] + 8), r, fill=(10, 25, 45, 70))
im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9 * S)))
# card: light gradient + faint CAD grid
cw, ch = card[2] - card[0], card[3] - card[1]
grad = Image.new("RGBA", (cw, ch))
gd = ImageDraw.Draw(grad)
for y in range(ch):
    t = y / ch
    c = tuple(int(a + (b - a) * t) for a, b in zip((252, 253, 255), (226, 233, 242))) + (255,)
    gd.line([(0, y), (cw, y)], fill=c)
for x in range(0, cw, 20 * S):
    gd.line([(x, 0), (x, ch)], fill=(205, 215, 228, 255) if (x // (20 * S)) % 5 == 0 else (220, 228, 238, 255), width=1)
for y in range(0, ch, 20 * S):
    gd.line([(0, y), (cw, y)], fill=(205, 215, 228, 255) if (y // (20 * S)) % 5 == 0 else (220, 228, 238, 255), width=1)
mask = Image.new("L", (cw, ch), 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), r, fill=255)
im.paste(grad, card[:2], mask)
d = ImageDraw.Draw(im)
d.rounded_rectangle(card, r, outline=(196, 207, 221, 255), width=S)
# blue band along the bottom of the card
band = Image.new("RGBA", (cw, 58 * S), (0, 0, 0, 0))
bd = ImageDraw.Draw(band)
for x in range(cw):
    t = x / cw
    c = tuple(int(a + (b - a) * t) for a, b in zip(mid, blue)) + (255,)
    bd.line([(x, 0), (x, 58 * S)], fill=c)
bmask = Image.new("L", (cw, 58 * S), 0); ImageDraw.Draw(bmask).rounded_rectangle((0, -r, cw - 1, 58 * S - 1), r, fill=255)
im.paste(band, (card[0], card[3] - 58 * S), bmask)
# the part, overlapping the card's right edge, with a shadow
part = Image.open("/tmp/claude-0/shots/bracket.png").convert("RGBA")
part = part.crop(part.getbbox())
pw = 268 * S; part = part.resize((pw, int(part.height * pw / part.width)), Image.LANCZOS)
px, py = W - pw - 6 * S, 78 * S
psh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
alpha = part.split()[3].point(lambda a: int(a * 0.35))
psh.paste(Image.new("RGBA", part.size, (10, 25, 45, 255)), (px + 10 * S, py + 16 * S), alpha)
im.alpha_composite(psh.filter(ImageFilter.GaussianBlur(10 * S)))
im.alpha_composite(part, (px, py))
# flow arrow accent (from the icon) sweeping under the part
d = ImageDraw.Draw(im)
# logo + name
icon = Image.open("/tmp/claude-0/shots/icon256.png").convert("RGBA").resize((64 * S, 64 * S), Image.LANCZOS)
im.alpha_composite(icon, (34 * S, 62 * S))
d.text((108 * S, 58 * S), "MechFlow", font=font("InterDisplay-Bold.otf", 50), fill=navy)
d.text((110 * S, 120 * S), "Mechanical design, the way you", font=font("Inter-Medium.otf", 17), fill=grey)
d.text((110 * S, 142 * S), "already work.", font=font("Inter-Medium.otf", 17), fill=grey)
d.text((36 * S, 228 * S), "VERSION 0.18.2", font=font("Inter-SemiBold.otf", 12), fill=blue)
d.text((36 * S, 248 * S), "Part  ·  Sketch  ·  Drawing  ·  Assembly", font=font("Inter-Regular.otf", 13), fill=grey)
# footer in the blue band
d.text((36 * S, (380 - 40) * S), "Built on FreeCAD", font=font("Inter-SemiBold.otf", 14), fill=(255, 255, 255))
d.text((36 * S + d.textlength("Built on FreeCAD", font=font("Inter-SemiBold.otf", 14)) + 10 * S, (380 - 39) * S),
       "·  Free and open source", font=font("Inter-Regular.otf", 13), fill=(200, 222, 245))
# status line area left blank on the band's right for FreeCAD's loading messages
im.save("/home/claude/MechFlow/Resources/splash/MechFlowSplash@2x.png")
im.resize((W // 2, H // 2), Image.LANCZOS).save("/home/claude/MechFlow/Resources/splash/MechFlowSplash.png")
prev = Image.new("RGBA", (W, H), (40, 40, 40, 255)); prev.alpha_composite(im); prev.convert("RGB").resize((W // 2, H // 2)).save("/tmp/claude-0/shots/splash_preview.png")
print("ok")
