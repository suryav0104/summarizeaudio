from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit a SummarizeAudio prompt.")
    parser.add_argument("--title", default="SummarizeAudio", help="Window title")
    parser.add_argument("--mode", choices=("prompt", "name"), default="prompt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    initial_text = sys.stdin.read()

    import tkinter as tk
    import tkinter.ttk as ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.withdraw()
    root.title(args.title)
    root.geometry("920x640")
    root.minsize(700, 480)
    root.resizable(True, True)
    root.configure(bg="#f5f7fb")

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

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Prompt.TFrame", background="#f5f7fb")
    style.configure("PromptCard.TFrame", background="white")
    style.configure("PromptTitle.TLabel", background="#f5f7fb", foreground="#162033", font=("Helvetica Neue", 22, "bold"))
    style.configure("PromptSub.TLabel", background="#f5f7fb", foreground="#52607a", font=("Helvetica Neue", 12))

    frame.configure(style="Prompt.TFrame")
    card = ttk.Frame(frame, style="PromptCard.TFrame", padding=24)
    card.pack(fill="both", expand=True)

    result = {"value": None}

    if args.mode == "prompt":
        ttk.Label(card, text="Edit Summarization Prompt", style="PromptTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text="Keep {transcript} in the prompt. It will be replaced with the transcript before summarization.",
            style="PromptSub.TLabel",
            wraplength=860,
        ).pack(anchor="w", pady=(4, 10))

        text = ScrolledText(
            card,
            width=110,
            height=28,
            wrap="word",
            undo=True,
            bg="white",
            fg="#162033",
            insertbackground="#162033",
            font=("Helvetica Neue", 14),
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#d4dce8",
            highlightcolor="#2e72ff",
        )
        text.pack(fill="both", expand=True)
        text.insert("1.0", initial_text)
        text.focus_set()

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

        buttons = ttk.Frame(card)
        buttons.pack(fill="x", pady=(12, 0))
        tk.Button(buttons, text="Skip", command=cancel, bg="#edf2f9", fg="#000000", activeforeground="#000000", relief="flat", bd=0, padx=16, pady=10, font=("Helvetica Neue", 13, "bold")).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="Summarize", command=confirm, bg="#2e72ff", fg="#000000", activeforeground="#000000", relief="flat", bd=0, padx=16, pady=10, font=("Helvetica Neue", 13, "bold")).pack(side="right")

    else:
        ttk.Label(card, text="Name Output File", style="PromptTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text="Choose the final file name. This name will be applied to the audio, transcript, and summary outputs.",
            style="PromptSub.TLabel",
            wraplength=860,
        ).pack(anchor="w", pady=(4, 10))

        name_var = tk.StringVar(value=initial_text.strip())
        entry = tk.Entry(
            card,
            textvariable=name_var,
            bg="white",
            fg="#162033",
            insertbackground="#162033",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#d4dce8",
            highlightcolor="#2e72ff",
            font=("Helvetica Neue", 14),
        )
        entry.pack(fill="x", pady=(0, 8))
        entry.focus_set()

        def confirm() -> None:
            value = name_var.get().strip()
            result["value"] = value or None
            root.quit()
            root.destroy()

        def cancel() -> None:
            result["value"] = None
            root.quit()
            root.destroy()

        buttons = ttk.Frame(card)
        buttons.pack(fill="x", pady=(12, 0))
        tk.Button(buttons, text="Cancel", command=cancel, bg="#edf2f9", fg="#000000", activeforeground="#000000", relief="flat", bd=0, padx=16, pady=10, font=("Helvetica Neue", 13, "bold")).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="Save", command=confirm, bg="#2e72ff", fg="#000000", activeforeground="#000000", relief="flat", bd=0, padx=16, pady=10, font=("Helvetica Neue", 13, "bold")).pack(side="right")

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
