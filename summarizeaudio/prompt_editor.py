from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit a SummarizeAudio prompt.")
    parser.add_argument("--title", default="SummarizeAudio", help="Window title")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    prompt = sys.stdin.read()

    import tkinter as tk
    import tkinter.ttk as ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.withdraw()
    root.title(args.title)
    root.geometry("920x640")
    root.minsize(700, 480)
    root.resizable(True, True)

    try:
        if sys.platform == "darwin":
            from AppKit import NSApplication

            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass

    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    width = 920
    height = 640
    x = max((screen_w - width) // 2, 0)
    y = max((screen_h - height) // 2, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = ttk.Frame(root, padding=14)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Edit Summarization Prompt", font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Keep {transcript} in the prompt. It will be replaced with the transcript before summarization.",
        wraplength=860,
    ).pack(anchor="w", pady=(4, 10))

    text = ScrolledText(frame, width=110, height=28, wrap="word", undo=True)
    text.pack(fill="both", expand=True)
    text.insert("1.0", prompt)
    text.focus_set()

    result = {"value": None}

    def confirm() -> None:
        value = text.get("1.0", "end-1c")
        if "{transcript}" not in value:
            value = value.rstrip() + "\n\nTranscript:\n{transcript}\n"
        result["value"] = value
        root.quit()
        root.destroy()

    def cancel() -> None:
        result["value"] = None
        root.quit()
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="Skip", command=cancel).pack(side="right", padx=(8, 0))
    ttk.Button(buttons, text="Summarize", command=confirm).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", cancel)
    root.deiconify()
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    root.after(250, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.grab_set()
    root.mainloop()

    if result["value"] is None:
        return 1
    sys.stdout.write(result["value"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
