"""Run once to generate tray icons: python assets/generate_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).parent

ICONS = {
    "icon_idle":       {"top": (68, 88, 120), "bottom": (34, 48, 72), "accent": (218, 227, 239)},
    "icon_recording":  {"top": (196, 47, 47), "bottom": (126, 19, 19), "accent": (255, 225, 225)},
    "icon_processing": {"top": (198, 141, 18), "bottom": (126, 90, 10), "accent": (255, 239, 195)},
    "icon_error":      {"top": (150, 28, 34), "bottom": (88, 12, 16), "accent": (255, 226, 226)},
}

SIZE = 64


def _gradient_bg(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = round(top[0] * (1 - t) + bottom[0] * t)
        g = round(top[1] * (1 - t) + bottom[1] * t)
        b = round(top[2] * (1 - t) + bottom[2] * t)
        for x in range(SIZE):
            px[x, y] = (r, g, b, 255)
    return img


def _draw_shadow(canvas: Image.Image) -> None:
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle([8, 9, SIZE - 8, SIZE - 8], radius=15, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(3.5))
    canvas.alpha_composite(shadow)


def _draw_bubble(draw: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    bubble_fill = (247, 250, 252, 240)
    bubble_outline = (*accent, 220)
    draw.rounded_rectangle([13, 14, 49, 42], radius=11, fill=bubble_fill, outline=bubble_outline, width=2)
    draw.polygon([(23, 42), (27, 49), (31, 42)], fill=bubble_fill, outline=bubble_outline)


def _draw_waveform(draw: ImageDraw.ImageDraw, color: tuple[int, int, int], mode: str) -> None:
    if mode == "error":
        draw.line([(31, 19), (31, 31)], fill=color, width=4)
        draw.ellipse([29, 34, 33, 38], fill=color)
        return

    if mode == "processing":
        dots = [(23, 28), (31, 23), (39, 28)]
        for x, y in dots:
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color)
        return

    points = {
        "idle": [(18, 31), (22, 27), (26, 34), (31, 24), (36, 34), (40, 28), (44, 31)],
        "recording": [(18, 31), (22, 22), (26, 38), (31, 18), (36, 38), (40, 24), (44, 31)],
    }[mode]
    draw.line(points, fill=color, width=4, joint="curve")
    if mode == "recording":
        draw.ellipse([41, 16, 48, 23], fill=(255, 84, 84, 255))


def make_icon(colors: dict[str, tuple[int, int, int]], mode: str) -> Image.Image:
    img = _gradient_bg(colors["top"], colors["bottom"])
    _draw_shadow(img)
    draw = ImageDraw.Draw(img)
    _draw_bubble(draw, colors["accent"])
    symbol = {
        "idle": (32, 30, 224),
        "recording": (255, 74, 74),
        "processing": (255, 246, 228),
        "error": (255, 235, 235),
    }[mode]
    _draw_waveform(draw, symbol, mode)
    return img


for name, colors in ICONS.items():
    mode = name.replace("icon_", "")
    img = make_icon(colors, mode)
    img.save(ASSETS / f"{name}.png")
    img.save(ASSETS / f"{name}.ico", format="ICO", sizes=[(32, 32), (16, 16)])
    print(f"Generated {name}.png and {name}.ico")
