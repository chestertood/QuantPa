"""Draws the QuantPa app icon: a minimal geometric Q on a dark rounded tile.

Run it after changing the design; it rewrites every icon the app ships:
    backend\\.venv\\Scripts\\python.exe make_icon.py

One mark serves every size — it's bold enough to survive 16px. Everything is
drawn at 4x and downscaled — Pillow's shapes have no antialiasing of their
own, so the supersample is what keeps the edges clean.
"""

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
PUBLIC = ROOT / "frontend" / "public"

BG = "#0e1118"
GOLD = "#f5b73d"

S = 4          # supersample factor
BASE = 1024    # design grid
C = BASE // 2  # centre


def px(*v):
    return [x * S for x in v]


def round_line(d, x1, y1, x2, y2, width, fill):
    """A line with round caps (Pillow only draws butt ends)."""
    d.line(px(x1, y1, x2, y2), fill=fill, width=width * S)
    r = width / 2
    for x, y in ((x1, y1), (x2, y2)):
        d.ellipse(px(x - r, y - r, x + r, y + r), fill=fill)


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (BASE * S, BASE * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(px(0, 0, BASE - 1, BASE - 1), radius=232 * S, fill=BG)

    # Ring, nudged up-left so the tail has room and the whole mark sits centred.
    r, stroke, cx, cy = 260, 96, C - 24, C - 24
    d.ellipse(px(cx - r, cy - r, cx + r, cy + r), outline=GOLD, width=stroke * S)

    # Tail: a diagonal cutting across the ring from deep in the counter, exiting lower right.
    round_line(d, cx + 60, cy + 60, cx + 250, cy + 250, stroke, GOLD)

    return img.resize((BASE, BASE), Image.LANCZOS)


def main():
    icon = draw_icon()

    for path, size in (
        (PUBLIC / "icon-512.png", 512),
        (PUBLIC / "icon-192.png", 192),
        (PUBLIC / "apple-touch-icon.png", 180),
    ):
        icon.resize((size, size), Image.LANCZOS).save(path)
        assert path.stat().st_size > 0, path

    # The filename is part of Explorer's icon-cache key: rewriting an .ico in
    # place leaves the old picture on the Desktop no matter how the cache is
    # flushed. A new name is what actually forces a redraw — so bump it (and the
    # one in install.vbs) whenever the art changes, then re-run install.vbs.
    ico = ROOT / "quantpa-v3.ico"
    frames = [icon.resize((s, s), Image.LANCZOS) for s in (256, 128, 64, 48, 32, 16)]
    frames[0].save(ico, format="ICO", sizes=[f.size for f in frames], append_images=frames[1:])
    assert len(Image.open(ico).ico.entry) == len(frames)
    print("wrote quantpa-v3.ico + 3 pngs")


if __name__ == "__main__":
    main()
