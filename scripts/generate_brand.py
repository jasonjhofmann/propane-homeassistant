#!/usr/bin/env python3
"""Generate brand assets (original artwork, no third-party logos).

Produces custom_components/neevo/brand/{icon,logo,dark_logo} per the
home-assistant/brands spec: icon 256x256 (+@2x 512), logo landscape (+@2x),
dark_* variants for dark backgrounds. HA 2026.3+ serves these via the local
brands proxy. The glyph is an original propane-tank silhouette on a rounded
tile — NOT any Nee-Vo, Otodata, or supplier logo.

Usage: python3 scripts/generate_brand.py   (requires Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "custom_components" / "neevo" / "brand"

TEAL = (0, 121, 107, 255)  # tile + wordmark accent
FLAME = (255, 138, 0, 255)  # gauge needle / flame accent
DARK_TEXT = (26, 26, 46, 255)
WHITE = (255, 255, 255, 255)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_glyph(size: int) -> Image.Image:
    """A horizontal propane tank with a dial gauge, on a rounded teal tile."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 512  # design at 512

    d.rounded_rectangle([16 * s, 16 * s, 496 * s, 496 * s], radius=96 * s, fill=TEAL)

    # Horizontal tank body: a rounded capsule.
    body = [110 * s, 200 * s, 402 * s, 360 * s]
    d.rounded_rectangle(body, radius=80 * s, fill=WHITE)

    # Two support feet under the tank.
    for fx in (170, 342):
        d.rounded_rectangle(
            [(fx - 18) * s, 350 * s, (fx + 18) * s, 392 * s],
            radius=8 * s,
            fill=WHITE,
        )

    # Dial gauge on top: white ring with a flame-colored needle.
    cx, cy, r = 256 * s, 188 * s, 56 * s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    d.ellipse(
        [cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72],
        fill=TEAL,
    )
    # Needle pointing up-right (~three-quarters full).
    d.line(
        [(cx, cy), (cx + r * 0.5, cy - r * 0.45)],
        fill=FLAME,
        width=int(12 * s),
    )
    d.ellipse(
        [cx - 7 * s, cy - 7 * s, cx + 7 * s, cy + 7 * s],
        fill=FLAME,
    )
    return img


def draw_logo(height: int, dark: bool) -> Image.Image:
    glyph = draw_glyph(height)
    font = _font(int(height * 0.42))
    text = "Nee-Vo"
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = int(probe.textlength(text, font=font))
    pad = int(height * 0.18)
    img = Image.new("RGBA", (height + pad + tw + pad, height), (0, 0, 0, 0))
    img.paste(glyph, (0, 0), glyph)
    d = ImageDraw.Draw(img)
    d.text(
        (height + pad, height // 2),
        text,
        font=font,
        fill=WHITE if dark else DARK_TEXT,
        anchor="lm",
    )
    return img


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    draw_glyph(512).save(BRAND / "icon@2x.png")
    draw_glyph(512).resize((256, 256), Image.LANCZOS).save(BRAND / "icon.png")
    for name, dark in [("logo", False), ("dark_logo", True)]:
        big = draw_logo(256, dark)
        big.save(BRAND / f"{name}@2x.png")
        big.resize((big.width // 2, 128), Image.LANCZOS).save(BRAND / f"{name}.png")
    for f in sorted(BRAND.iterdir()):
        print(f.name, Image.open(f).size)


if __name__ == "__main__":
    main()
