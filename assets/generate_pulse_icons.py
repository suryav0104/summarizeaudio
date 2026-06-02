"""Generate animated 'rising sweep' pulse frames for the menu-bar icon.

States:
  - recording  -> red color rising bottom->top (sawtooth pulse)
  - processing -> amber color rising bottom->top (sawtooth pulse)
  - error      -> static full red + white exclamation mark (persistent)

These frames are LITERAL-COLOR (non-template) images. Because a single PNG
cannot be both a theme-adaptive template AND carry a literal color fill
(``setTemplate_(True)`` strips all color), we render the silhouette base in two
variants so it matches the live idle template on whichever menu bar is active:

  - ``dark``  variant -> WHITE silhouette base (for a DARK menu bar)
  - ``light`` variant -> near-BLACK silhouette base (for a LIGHT menu bar)

The state color fills from the base up to a soft fill line on top of either
base. The tray picks the variant at runtime from ``NSApp.effectiveAppearance``.
Idle stays the existing template silhouette (not produced here). The error frame
is fully filled red, so its base is irrelevant — a single frame is emitted.

Run:  ./venv/bin/python assets/generate_pulse_icons.py
Writes frames to assets/ and a preview sheet to assets/pulse_preview.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).parent
sys.path.insert(0, str(ASSETS))
from draw_broadcast_vector import broadcast_vector  # noqa: E402  (sibling script)

SIZE = 64
WORK = 256                      # supersample for a smooth fill line
N_FRAMES = 12                   # frames per pulse cycle
MIN_FILL = 0.10                 # only the base foot stays colored at all times;
                                # the sweep rises from the neck up through the head

BASE_DARK = (248, 248, 248)     # silhouette on a DARK menu bar (matches white idle)
BASE_LIGHT = (28, 28, 30)       # silhouette on a LIGHT menu bar (matches black idle)
VARIANTS = {"dark": BASE_DARK, "light": BASE_LIGHT}
RED = (220, 38, 38)             # recording (#dc2626, crisp red, matches app)
GREEN = (34, 178, 84)           # processing (reads on light AND dark bars)
ERROR_RED = (220, 38, 38)       # persistent error (same red as recording)
WHITE = (252, 252, 252)


def _mask_work() -> Image.Image:
    """Silhouette alpha (the exact live idle shape) upscaled to WORK px."""
    base = broadcast_vector()                       # 64px black-on-transparent
    mask = base.split()[-1]                         # alpha = silhouette
    return mask.resize((WORK, WORK), Image.Resampling.LANCZOS)


def _fill_band(level: float, y_top: int, y_bot: int) -> Image.Image:
    """An 'L' mask: 255 below the fill line, soft-faded over a short band."""
    grad = Image.new("L", (WORK, WORK), 0)
    px = grad.load()
    fill_y = y_bot - level * (y_bot - y_top)
    band = WORK * 0.05                              # soft edge thickness
    for y in range(WORK):
        if y >= fill_y + band:
            v = 255
        elif y <= fill_y - band:
            v = 0
        else:
            v = int(255 * (y - (fill_y - band)) / (2 * band))
        for x in range(WORK):
            px[x, y] = v
    return grad


def _frame(mask: Image.Image, bbox, color, level: float, base: tuple) -> Image.Image:
    """`base`-colored silhouette with `color` filled from the base up to `level`."""
    _, y_top, _, y_bot = bbox
    out = Image.new("RGBA", (WORK, WORK), (0, 0, 0, 0))
    body = Image.new("RGBA", (WORK, WORK), (*base, 255))
    out = Image.composite(body, out, mask)
    band = _fill_band(level, y_top, y_bot)
    color_region = Image.composite(band, Image.new("L", (WORK, WORK), 0), mask)
    color_layer = Image.new("RGBA", (WORK, WORK), (*color, 255))
    out = Image.composite(color_layer, out, color_region)
    return out.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def _error_frame(mask: Image.Image, bbox) -> Image.Image:
    """Full red mic + a red exclamation mark in the right margin (beside the mic).

    The mic is a tall, narrow shape so the canvas has empty space on its right.
    Placing the mark there keeps it legible (overlaid on the red body it washed
    out). Drawn in the same red, which reads on both light and dark menu bars.
    """
    full = _frame(mask, bbox, ERROR_RED, 1.0, BASE_DARK).resize((WORK, WORK), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(full)
    x0, y0, x1, y1 = mask.getbbox()
    h = y1 - y0
    ex = int(x1 + (WORK - x1) * 0.45)          # horizontal center in right margin
    bw = max(2, int((WORK - x1) * 0.20))       # bar half-width
    bar_top = int(y0 + h * 0.18)
    bar_bot = int(y0 + h * 0.52)
    d.rounded_rectangle([ex - bw, bar_top, ex + bw, bar_bot], radius=bw, fill=ERROR_RED)
    dy = int(y0 + h * 0.64)
    d.ellipse([ex - bw, dy - bw, ex + bw, dy + bw], fill=ERROR_RED)
    return full.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def _levels() -> list[float]:
    """Fill levels from MIN_FILL (base anchor) up to full, for the rising sweep."""
    return [MIN_FILL + (1 - MIN_FILL) * i / (N_FRAMES - 1) for i in range(N_FRAMES)]


def _filmstrip(frames: list[Image.Image], bg, fs: int, gap: int) -> Image.Image:
    w = len(frames) * (fs + gap) + gap
    strip = Image.new("RGBA", (w, fs + 2 * gap), bg)
    for i, fr in enumerate(frames):
        small = fr.resize((fs, fs), Image.Resampling.LANCZOS)
        strip.alpha_composite(small, (gap + i * (fs + gap), gap))
    return strip


def main() -> None:
    mask = _mask_work()
    bbox = mask.getbbox()

    # variant -> {"recording": [...], "processing": [...]}
    sets: dict[str, dict[str, list[Image.Image]]] = {}
    for variant, base in VARIANTS.items():
        rec = [_frame(mask, bbox, RED, t, base) for t in _levels()]
        proc = [_frame(mask, bbox, GREEN, t, base) for t in _levels()]
        sets[variant] = {"recording": rec, "processing": proc}
        for i, fr in enumerate(rec):
            fr.save(ASSETS / f"pulse_recording_{variant}_{i:02d}.png")
        for i, fr in enumerate(proc):
            fr.save(ASSETS / f"pulse_processing_{variant}_{i:02d}.png")

    err = _error_frame(mask, bbox)
    err.save(ASSETS / "pulse_error.png")

    # Preview sheet: render each variant's filmstrip on its matching bar so we
    # can confirm the silhouette base reads like the idle template would.
    fs, gap = 36, 6
    light = (255, 255, 255, 255)
    dark = (28, 30, 34, 255)
    rows = [
        ("recording — dark variant on dark bar", _filmstrip(sets["dark"]["recording"], dark, fs, gap)),
        ("recording — light variant on light bar", _filmstrip(sets["light"]["recording"], light, fs, gap)),
        ("processing — dark variant on dark bar", _filmstrip(sets["dark"]["processing"], dark, fs, gap)),
        ("processing — light variant on light bar", _filmstrip(sets["light"]["processing"], light, fs, gap)),
    ]
    pad = 16
    label_h = 18
    strip_w = rows[0][1].width
    err_zoom = 96
    sheet_w = strip_w + pad * 2
    sheet_h = pad + sum(label_h + r.height + 8 for _, r in rows) + label_h + err_zoom + pad * 2
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (243, 244, 246, 255))
    draw = ImageDraw.Draw(sheet)
    y = pad
    for label, strip in rows:
        draw.text((pad, y), label, fill=(40, 44, 52, 255))
        y += label_h
        sheet.alpha_composite(strip, (pad, y))
        y += strip.height + 8
    draw.text((pad, y), "error (static, on light + dark)", fill=(40, 44, 52, 255))
    y += label_h
    el = Image.new("RGBA", (err_zoom, err_zoom), light)
    el.alpha_composite(err.resize((err_zoom, err_zoom), Image.Resampling.LANCZOS))
    ed = Image.new("RGBA", (err_zoom, err_zoom), dark)
    ed.alpha_composite(err.resize((err_zoom, err_zoom), Image.Resampling.LANCZOS))
    sheet.alpha_composite(el, (pad, y))
    sheet.alpha_composite(ed, (pad + err_zoom + 12, y))
    out = ASSETS / "pulse_preview.png"
    sheet.save(out)
    n = len(_levels())
    print(f"frames written: {n} recording + {n} processing per variant "
          f"({', '.join(VARIANTS)}) + 1 error")
    print("preview:", out)


if __name__ == "__main__":
    main()
