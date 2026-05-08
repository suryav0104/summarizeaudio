"""Run once to generate tray icons: python assets/generate_icons.py"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).parent
SIZE = 64
SCALE = 4


@dataclass(frozen=True)
class Style:
    name: str
    stroke: tuple[int, int, int]
    detail: tuple[int, int, int]
    fill: tuple[int, int, int, int]
    background: tuple[int, int, int]
    halo: tuple[int, int, int] | None = None


STYLES = (
    Style("carbon", (42, 47, 55), (72, 80, 92), (0, 0, 0, 0), (250, 250, 250)),
    Style("steel", (73, 87, 106), (106, 126, 148), (0, 0, 0, 0), (250, 250, 250)),
    Style("contrast", (250, 252, 255), (250, 252, 255), (0, 0, 0, 0), (250, 250, 250), (24, 28, 35)),
)

ACTIVE_STYLE = STYLES[2]

RECORD = (239, 62, 62)
PROCESS = (247, 162, 28)
ERROR = (218, 52, 65)
WHITE = (255, 255, 255)


def _s(value: int) -> int:
    return value * SCALE


def _scaled_canvas(size: int = SIZE) -> Image.Image:
    return Image.new("RGBA", (_s(size), _s(size)), (0, 0, 0, 0))


def _scaled_draw(img: Image.Image) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(img)


def _rounded(draw: ImageDraw.ImageDraw, box: list[int], radius: int, *, fill=None, outline=None, width: int = 1) -> None:
    scaled_box = [_s(v) for v in box]
    draw.rounded_rectangle(scaled_box, radius=_s(radius), fill=fill, outline=outline, width=_s(width))


def _line(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color: tuple[int, int, int], width: int) -> None:
    draw.line([(_s(x), _s(y)) for x, y in points], fill=color, width=_s(width), joint="curve")


def _ellipse(draw: ImageDraw.ImageDraw, box: list[int], fill: tuple[int, int, int]) -> None:
    draw.ellipse([_s(v) for v in box], fill=fill)


def _finalize(img: Image.Image, size: int = SIZE) -> Image.Image:
    return img.resize((size, size), Image.Resampling.LANCZOS)


def _draw_mic(draw: ImageDraw.ImageDraw, style: Style) -> None:
    # Bold standalone microphone, tuned for tiny tray rendering.
    if style.halo:
        _rounded(draw, [18, 7, 46, 39], 14, outline=style.halo, width=6)
        _line(draw, [(32, 39), (32, 49)], style.halo, 7)
        _line(draw, [(23, 49), (41, 49)], style.halo, 7)
        for x, top, bottom, width in (
            (23, 22, 30, 2),
            (28, 18, 34, 2),
            (32, 14, 37, 3),
            (36, 18, 34, 2),
            (41, 22, 30, 2),
        ):
            _rounded(draw, [x - width - 1, top - 1, x + width + 1, bottom + 1], width + 1, fill=style.halo)

    _rounded(draw, [18, 7, 46, 39], 14, fill=style.fill if style.fill[3] else None, outline=style.stroke, width=3)

    # Inner contour keeps the filled style from becoming a solid blob.
    if style.fill[3]:
        _rounded(draw, [21, 10, 43, 36], 11, outline=style.stroke, width=1)

    _line(draw, [(32, 39), (32, 49)], style.stroke, 4)
    _line(draw, [(23, 49), (41, 49)], style.stroke, 4)

    for x, top, bottom, width in (
        (23, 22, 30, 2),
        (28, 18, 34, 2),
        (32, 14, 37, 3),
        (36, 18, 34, 2),
        (41, 22, 30, 2),
    ):
        _rounded(draw, [x - width, top, x + width, bottom], width, fill=style.detail)


def _draw_badge(draw: ImageDraw.ImageDraw, mode: str) -> None:
    if mode == "idle":
        return
    if mode == "recording":
        _ellipse(draw, [43, 9, 56, 22], RECORD)
        _ellipse(draw, [47, 13, 52, 18], WHITE)
        return
    if mode == "processing":
        _rounded(draw, [41, 10, 57, 23], 6, fill=PROCESS)
        for x in (45, 49, 53):
            _ellipse(draw, [x - 1, 15, x + 1, 17], WHITE)
        return
    if mode == "error":
        _rounded(draw, [42, 9, 57, 24], 6, fill=ERROR)
        _line(draw, [(49, 13), (49, 18)], WHITE, 3)
        _ellipse(draw, [48, 20, 50, 22], WHITE)


def make_icon(mode: str, style: Style) -> Image.Image:
    img = _scaled_canvas()
    draw = _scaled_draw(img)
    _draw_mic(draw, style)
    _draw_badge(draw, mode)
    return _finalize(img)


def _card(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle([18, 22, size - 18, size - 14], radius=24, fill=(0, 0, 0, 18))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, size - 5, size - 5], radius=26, fill=(250, 250, 250, 255), outline=(223, 226, 231, 255), width=2)
    return img


def _thumb_card(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([1, 1, size - 2, size - 2], radius=12, fill=(250, 250, 250, 255), outline=(228, 231, 236, 255), width=1)
    return img


def _make_preview() -> None:
    card_size = 168
    gap = 48
    thumb_size = 34
    thumb_gap = 10
    width = card_size * 3 + gap * 2
    height = 308
    sheet = Image.new("RGBA", (width, height), (248, 249, 251, 255))

    for index, style in enumerate(STYLES):
        x = index * (card_size + gap)
        sheet.alpha_composite(_card(card_size), (x, 20))
        hero = make_icon("idle", style).resize((122, 122), Image.Resampling.LANCZOS)
        sheet.alpha_composite(hero, (x + 23, 42))

        modes = ("idle", "recording", "processing", "error")
        row_width = thumb_size * len(modes) + thumb_gap * (len(modes) - 1)
        start_x = x + (card_size - row_width) // 2
        for offset, mode in enumerate(modes):
            px = start_x + offset * (thumb_size + thumb_gap)
            sheet.alpha_composite(_thumb_card(thumb_size), (px, 220))
            thumb = make_icon(mode, style).resize((28, 28), Image.Resampling.LANCZOS)
            sheet.alpha_composite(thumb, (px + 3, 223))

    sheet.save(ASSETS / "icon_variants.png")


for mode in ("idle", "recording", "processing", "error"):
    icon = make_icon(mode, ACTIVE_STYLE)
    icon.save(ASSETS / f"icon_{mode}.png")
    icon.save(ASSETS / f"icon_{mode}.ico", format="ICO", sizes=[(32, 32), (16, 16)])
    print(f"Generated icon_{mode}.png and icon_{mode}.ico")

_make_preview()
print("Generated icon_variants.png")
