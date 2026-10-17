# Frames the gallery renders as cards for README.md: rounded corners, a
# hairline border and a title in the corner. Flat captures (the sketch and
# the drawing) float on the same studio backdrop as the renders.
#   python3 tools/gallery_cards.py <renders dir> <out dir>
# Needs Pillow and the Inter font (OFL); pdftoppm for the drawing.
import os, sys, json, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SRC, DST = sys.argv[1], sys.argv[2]
os.makedirs(DST, exist_ok=True)
FONTS = "/usr/share/fonts/opentype/inter/"
W, H = 1600, 1000
R = 26


def font(name, px):
    return ImageFont.truetype(FONTS + name, px)


def backdrop():
    """The renders' studio: a lit floor fading to navy."""
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        for x in range(W):
            dx, dy = (x - W * 0.5) / (W * 0.62), (y - H * 0.62) / (H * 0.75)
            t = min(1.0, (dx * dx + dy * dy) ** 0.5)
            t = t ** 1.3
            c0, c1 = (66, 78, 98), (10, 14, 22)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))
    return im


def floating(img, max_w, max_h, radius=14):
    """img scaled to fit, rounded, with a soft shadow, centred on the backdrop."""
    bg = backdrop().convert("RGBA")
    sc = min(max_w / img.width, max_h / img.height)
    img = img.convert("RGBA").resize((round(img.width * sc), round(img.height * sc)), Image.LANCZOS)
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    x, y = (W - img.width) // 2, (H - img.height) // 2 - 20
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x + 6, y + 18, x + img.width - 6, y + img.height + 14), radius,
                                         fill=(0, 0, 0, 150))
    bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    bg.paste(img, (x, y), m)
    LAST[:] = [x, y, img.width, img.height]
    return bg


LAST = [0, 0, 0, 0]          # where floating() put its picture: x, y, w, h


def info_box(bg, x, y, line1, line2, right=None):
    """A small white panel with a heading and a status line (right: its right edge)."""
    d = ImageDraw.Draw(bg)
    f1, f2 = font("Inter-SemiBold.otf", 24), font("Inter-Medium.otf", 20)
    w = int(max(d.textlength(line1, font=f1), d.textlength(line2, font=f2) + 24)) + 48
    if right is not None:
        x = right - w
    d.rounded_rectangle((x, y, x + w, y + 86), 14, fill=(255, 255, 255, 240),
                        outline=(205, 214, 226, 255), width=2)
    d.text((x + 22, y + 14), line1, font=f1, fill=(30, 40, 56))
    d.ellipse((x + 24, y + 54, x + 37, y + 67), fill=(20, 20, 20))
    d.text((x + 46, y + 48), line2, font=f2, fill=(60, 72, 90))


def card(img, title, sub, out, legend=None):
    img = img.convert("RGBA").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    # a soft dark band behind the title
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for i in range(240):
        a = int(170 * (i / 240) ** 1.6)
        bd.line([(0, H - 240 + i), (W, H - 240 + i)], fill=(6, 10, 18, a))
    img.alpha_composite(band)
    d = ImageDraw.Draw(img)
    d.text((56, H - 150), title, font=font("InterDisplay-Bold.otf", 68), fill=(255, 255, 255))
    d.text((58, H - 70), sub, font=font("Inter-Medium.otf", 36), fill=(200, 214, 234))
    if legend:
        lo, hi, unit = legend
        x0, y0, h = W - 110, 120, 420
        stops = [(26, 51, 217), (13, 191, 242), (51, 217, 77), (250, 217, 26), (235, 31, 20)]
        for i in range(h):
            t = 1 - i / (h - 1)
            k = t * (len(stops) - 1)
            j = min(int(k), len(stops) - 2)
            u = k - j
            c = tuple(int(a + (b - a) * u) for a, b in zip(stops[j], stops[j + 1]))
            d.line([(x0, y0 + i), (x0 + 26, y0 + i)], fill=c)
        d.rectangle((x0, y0, x0 + 26, y0 + h), outline=(255, 255, 255, 120), width=1)
        f = font("Inter-Medium.otf", 22)
        for val, yy in ((hi, y0), ((hi + lo) / 2, y0 + h / 2), (lo, y0 + h)):
            tx = f"{val:.0f}"
            d.text((x0 - 12 - d.textlength(tx, font=f), yy - 13), tx, font=f, fill=(225, 232, 242))
        d.text((x0 + 30 - d.textlength(unit, font=f), y0 - 40), unit, font=f, fill=(225, 232, 242))
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, W - 1, H - 1), R, fill=255)
    out_im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out_im.paste(img, (0, 0), m)
    ImageDraw.Draw(out_im).rounded_rectangle((0, 0, W - 1, H - 1), R, outline=(255, 255, 255, 40), width=2)
    out_im.resize((1280, 800), Image.LANCZOS).save(out, optimize=True)     # sharp on retina at 2 per row
    print("card", out)


TILES = [
    ("housing", "Part modelling", "Extrudes, Hole Wizard, fillets and patterns"),
    ("sketch", "Sketching", "Fully defined sketches, relations and Smart Dimension"),
    ("weldment", "Weldments", "Structural members, corner cuts, gussets, cut list"),
    ("drawing", "Drawings", "Make Drawing: views, dimensions and title block"),
    ("routing", "Routing", "Pipe, elbows, flanged joints, valves and instruments"),
    ("toolbox", "Toolbox", "EN / ASME flanges, fittings, bearings and fasteners"),
    ("exploded", "Exploded View", "Parts slide out along the axis they sit on"),
    ("stress", "Stress Check", "Von Mises stress, factor of safety, deflection"),
]
for key, title, sub in TILES:
    out = os.path.join(DST, key + ".png")
    if key == "sketch":
        p = os.path.join(SRC, "gallery", "sketch", "view.png")
        if not os.path.exists(p):
            continue
        bg = floating(Image.open(p), 1240, 760)
        info = os.path.join(SRC, "gallery", "sketch", "info.json")
        if os.path.exists(info):
            # MechFlow's own sketch status, as its status bar shows it
            i = json.load(open(info))
            line1 = f"{i['name']}  \u00b7  {i['plane']}"
            line2 = f"{i['status']}  \u00b7  {i['relations']} relations  \u00b7  {i['dims']} dimensions"
            # on the dark band beside the title, clear of the sketch
            info_box(bg, 0, H - 128, line1, line2, right=W - 40)
        card(bg, title, sub, out)
    elif key == "drawing":
        pdf = os.path.join(SRC, "gallery", "drawing", "drawing.pdf")
        if not os.path.exists(pdf):
            continue
        base = os.path.join(SRC, "gallery", "drawing", "sheet")
        subprocess.run(["pdftoppm", "-r", "220", "-png", "-singlefile", pdf, base], check=True)
        bg = floating(Image.open(base + ".png"), 1300, 760, radius=6)
        info = os.path.join(SRC, "gallery", "drawing", "info.json")
        if os.path.exists(info):
            i = json.load(open(info))
            sx, sy, sw, shh = LAST
            info_box(bg, int(sx + 0.05 * sw), int(sy + 0.80 * shh),
                     f"{i['title']}  \u00b7  {i['sheet']}  \u00b7  {i['scale']}",
                     f"{i['views']} views  \u00b7  {i['dims']} dimensions  \u00b7  section, detail, notes")
        card(bg, title, sub, out)
    else:
        p = os.path.join(SRC, key + ".png")
        if not os.path.exists(p):
            continue
        legend = None
        if key == "stress":
            cam = json.load(open(os.path.join(SRC, "gallery", "stress", "camera.json")))
            legend = (0.0, cam["lim"], "MPa")
        card(Image.open(p), title, sub, out, legend)
