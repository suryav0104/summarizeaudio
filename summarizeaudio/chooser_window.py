from __future__ import annotations

import argparse
import os
import subprocess
import sys


def _osascript(script: str) -> tuple[int, str]:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _configure_macos_accessory_app() -> None:
    # Intentionally left as a no-op.
    # The accessory activation policy crashes Tk on this Python/Tk build.
    return


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

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        path_str = filedialog.askopenfilename(
            title=title,
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.ogg *.flac")],
        )
    finally:
        root.destroy()
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

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        path_str = filedialog.askopenfilename(
            title=title,
            filetypes=[("Text files", "*.txt *.md")],
        )
    finally:
        root.destroy()
    return path_str or None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SummarizeAudio chooser helper.")
    parser.add_argument("--kind", choices=("audio", "text"), default="audio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_macos_accessory_app()

    import tkinter as tk
    from tkinter import ttk

    title = "Select Audio File" if args.kind == "audio" else "Select Text File"
    message = (
        "Choose an audio file to transcribe and summarize."
        if args.kind == "audio"
        else "Choose a transcript file to summarize."
    )

    root = tk.Tk()
    root.withdraw()
    root.title(title)
    root.geometry("640x320")
    root.minsize(560, 300)
    root.resizable(False, False)
    root.configure(bg="#f5f7fb")

    canvas = tk.Canvas(root, width=640, height=320, highlightthickness=0, bg="#f5f7fb")
    canvas.pack(fill="both", expand=True)

    card = tk.Frame(canvas, bg="white", bd=0, highlightthickness=1, highlightbackground="#d7dde8")
    card.place(relx=0.5, rely=0.5, anchor="center", width=570, height=230)

    tk.Label(
        card,
        text=title,
        font=("Helvetica Neue", 18, "bold"),
        fg="#162033",
        bg="white",
    ).pack(anchor="w", padx=22, pady=(22, 6))
    tk.Label(
        card,
        text=message,
        font=("Helvetica Neue", 11),
        fg="#52607a",
        bg="white",
        wraplength=520,
        justify="left",
    ).pack(anchor="w", padx=22, pady=(0, 18))

    state = {"choose": False, "closed": False, "path": None}

    def close() -> None:
        if state["closed"]:
            return
        state["closed"] = True
        try:
            root.grab_release()
        except Exception:
            pass
        try:
            root.quit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    def choose() -> None:
        state["choose"] = True
        close()

    buttons = ttk.Frame(card)
    buttons.pack(fill="x", padx=22, pady=(0, 18))
    ttk.Button(buttons, text="Choose File", command=choose).pack(side="left")
    ttk.Button(buttons, text="Cancel", command=close).pack(side="left", padx=(8, 0))

    root.protocol("WM_DELETE_WINDOW", close)
    root.deiconify()
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max((screen_w - 640) // 2, 0)
    y = max((screen_h - 320) // 2, 0)
    root.geometry(f"640x320+{x}+{y}")
    root.lift()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.grab_set()
    root.mainloop()

    if not state["choose"]:
        return 1

    try:
        if args.kind == "audio":
            path = _native_audio_picker(title)
        else:
            path = _native_text_picker(title)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not path:
        return 1
    print(path, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
