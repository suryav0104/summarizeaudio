from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SummarizeAudio alert window.")
    parser.add_argument("--title", default="SummarizeAudio", help="Window title")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    message = sys.stdin.read().strip()

    import tkinter as tk
    import tkinter.ttk as ttk

    root = tk.Tk()
    root.withdraw()
    root.title(args.title)
    root.geometry("760x360")
    root.minsize(640, 300)
    root.resizable(False, False)
    root.configure(bg="#f5f7fb")

    frame = ttk.Frame(root, padding=14)
    frame.pack(fill="both", expand=True)

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Alert.TFrame", background="#f5f7fb")
    style.configure("AlertCard.TFrame", background="white")
    style.configure("AlertTitle.TLabel", background="#f5f7fb", foreground="#162033", font=("Helvetica Neue", 22, "bold"))
    style.configure("AlertSub.TLabel", background="#f5f7fb", foreground="#52607a", font=("Helvetica Neue", 12))
    style.configure("AlertBody.TLabel", background="white", foreground="#162033", font=("Helvetica Neue", 14))

    frame.configure(style="Alert.TFrame")
    card = ttk.Frame(frame, style="AlertCard.TFrame", padding=24)
    card.pack(fill="both", expand=True)

    ttk.Label(card, text=args.title, style="AlertTitle.TLabel").pack(anchor="w")
    ttk.Label(
        card,
        text="Review this message and close it when you're done.",
        style="AlertSub.TLabel",
        wraplength=700,
    ).pack(anchor="w", pady=(4, 10))

    body = ttk.Frame(card, style="AlertCard.TFrame")
    body.pack(fill="both", expand=True, pady=(4, 10))
    ttk.Label(
        body,
        text=message or "",
        style="AlertBody.TLabel",
        wraplength=680,
        justify="left",
    ).pack(anchor="w")

    def close() -> None:
        try:
            root.grab_release()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    actions = ttk.Frame(card, style="AlertCard.TFrame")
    actions.pack(fill="x")
    tk.Button(
        actions,
        text="Close",
        command=close,
        bg="#edf2f9",
        fg="#000000",
        activeforeground="#000000",
        relief="flat",
        bd=0,
        padx=16,
        pady=10,
        font=("Helvetica Neue", 13, "bold"),
    ).pack(side="left")

    root.protocol("WM_DELETE_WINDOW", close)
    root.deiconify()
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max((screen_w - 760) // 2, 0)
    y = max((screen_h - 360) // 2, 0)
    root.geometry(f"760x360+{x}+{y}")
    root.lift()
    root.attributes("-topmost", True)
    root.after(250, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.grab_set()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
