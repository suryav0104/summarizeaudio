from __future__ import annotations

import subprocess
import sys


def _osascript(script: str) -> tuple[int, str]:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _native_audio_picker(title: str) -> str | None:
    if sys.platform == "darwin":
        rc, path_str = _osascript(
            'set f to choose file with prompt "Select Audio File" '
            'of type {"mp3", "wav", "m4a", "ogg", "flac", "public.audio"}\n'
            'return POSIX path of f'
        )
        if rc != 0 or not path_str:
            return None
        return path_str

    from tkinter import filedialog
    path_str = filedialog.askopenfilename(
        title=title,
        filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.ogg *.flac")],
    )
    return path_str or None


def _native_text_picker(title: str) -> str | None:
    if sys.platform == "darwin":
        rc, path_str = _osascript(
            'set f to choose file with prompt "Select Text File"\n'
            'return POSIX path of f'
        )
        if rc != 0 or not path_str:
            return None
        return path_str

    from tkinter import filedialog
    path_str = filedialog.askopenfilename(
        title=title,
        filetypes=[("Text files", "*.txt *.md")],
    )
    return path_str or None
