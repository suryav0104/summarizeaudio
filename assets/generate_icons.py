"""Run once to generate tray icons: python assets/generate_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw

ASSETS = Path(__file__).parent

ICONS = {
    "icon_idle":       (180, 180, 180),   # grey
    "icon_recording":  (220, 50,  50),    # red
    "icon_processing": (220, 160, 0),     # amber
    "icon_error":      (180, 0,   0),     # dark red
}

SIZE = 64


def make_icon(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, SIZE - 4, SIZE - 4], fill=(*color, 255))
    return img


for name, color in ICONS.items():
    img = make_icon(color)
    img.save(ASSETS / f"{name}.png")
    img.save(ASSETS / f"{name}.ico", format="ICO", sizes=[(32, 32), (16, 16)])
    print(f"Generated {name}.png and {name}.ico")
