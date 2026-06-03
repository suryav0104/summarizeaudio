from __future__ import annotations

import argparse
import subprocess
import sys

from summarizeaudio.error_handler import LOG_PATH


def _split_log_path(text: str, log_path: str) -> tuple[str, str, str] | None:
    """Locate the log path inside a paragraph so it can be rendered as a
    clickable link. Returns (before, path, after) or None if not present."""
    idx = text.find(log_path)
    if idx == -1:
        return None
    return text[:idx], log_path, text[idx + len(log_path):]


def _open_path(path: str) -> None:
    """Open a file with the OS default handler (the log opens in Console/an
    editor). Failures are swallowed — the alert window must never crash."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform.startswith("win"):
            import os
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SummarizeAudio alert window.")
    parser.add_argument("--title", default="SummarizeAudio", help="Window title")
    return parser


def _message_parts(message: str) -> tuple[str, str]:
    paragraphs = [part.strip() for part in message.split("\n\n") if part.strip()]
    if not paragraphs:
        return "", ""

    component = None
    if paragraphs[0].lower().startswith("component:"):
        component = paragraphs.pop(0)

    primary = paragraphs.pop(0) if paragraphs else message.strip()
    technical = list(paragraphs)
    if component:
        technical.insert(0, component)
    return primary, "\n\n".join(technical)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    message = sys.stdin.read().strip()
    primary_message, supporting_message = _message_parts(message)

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
    style.configure("AlertTitle.TLabel", background="#f5f7fb", foreground="#162033", font=("Helvetica Neue", 20, "bold"))
    style.configure("AlertSub.TLabel", background="#f5f7fb", foreground="#52607a", font=("Helvetica Neue", 11))
    style.configure("AlertDetail.TLabel", background="white", foreground="#60708a", font=("Helvetica Neue", 11))

    frame.configure(style="Alert.TFrame")
    card = ttk.Frame(frame, style="AlertCard.TFrame", padding=24)
    card.pack(fill="both", expand=True)

    ttk.Label(card, text=args.title, style="AlertTitle.TLabel").pack(anchor="w")
    ttk.Label(
        card,
        text="Resolve this issue before continuing.",
        style="AlertSub.TLabel",
        wraplength=700,
    ).pack(anchor="w", pady=(4, 10))

    body = ttk.Frame(card, style="AlertCard.TFrame")
    body.pack(fill="both", expand=True, pady=(4, 10))

    primary = tk.Frame(body, bg="#fff5f5", highlightbackground="#f1b7b7", highlightthickness=1, padx=14, pady=12)
    primary.pack(fill="x", anchor="w")
    tk.Label(
        primary,
        text=primary_message or "",
        bg="#fff5f5",
        fg="#7f1d1d",
        font=("Helvetica Neue", 11),
        wraplength=640,
        justify="left",
        anchor="w",
    ).pack(anchor="w", fill="x")

    if supporting_message:
        log_path_str = str(LOG_PATH)
        for index, paragraph in enumerate(supporting_message.split("\n\n")):
            pady = (12 if index == 0 else 8, 0)
            split = _split_log_path(paragraph, log_path_str)
            if split is None:
                ttk.Label(
                    body,
                    text=paragraph,
                    style="AlertDetail.TLabel",
                    wraplength=680,
                    justify="left",
                    anchor="w",
                ).pack(anchor="w", fill="x", pady=pady)
                continue

            before, path, after = split
            row = tk.Frame(body, bg="white")
            row.pack(anchor="w", fill="x", pady=pady)
            if before:
                tk.Label(
                    row, text=before, bg="white", fg="#60708a",
                    font=("Helvetica Neue", 11), anchor="w",
                ).pack(side="left")
            link = tk.Label(
                row, text=path, bg="white", fg="#2563eb",
                font=("Helvetica Neue", 11, "underline"),
                cursor="pointinghand", anchor="w",
            )
            link.pack(side="left")
            link.bind("<Button-1>", lambda _e, p=path: _open_path(p))
            if after:
                tk.Label(
                    row, text=after, bg="white", fg="#60708a",
                    font=("Helvetica Neue", 11), anchor="w",
                ).pack(side="left")

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
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max((screen_w - 760) // 2, 0)
    y = max((screen_h - 360) // 2, 0)
    root.geometry(f"760x360+{x}+{y}")
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    root.after(750, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.grab_set()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
