"""A small Markdown renderer for the embedded tutorial.

This is intentionally not a general Markdown implementation.  It supports
headings, bullets, fenced code, block quotes and paragraphs so the tutorial
stays readable without adding a dependency.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from sentinel.gui.theme import ACCENT, CODE_BG, CODE_FG, MUTED, PANEL, TEXT, WARN


class MarkdownView(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, font_family: str = "Segoe UI") -> None:
        super().__init__(parent)
        self.font_family = font_family
        self.text = tk.Text(
            self,
            wrap="word",
            background=PANEL,
            foreground=TEXT,
            insertbackground=TEXT,
            borderwidth=0,
            padx=18,
            pady=16,
            font=(font_family, 10),
            spacing1=2,
            spacing3=4,
        )
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._configure_tags()
        self.text.configure(state="disabled")

    def _configure_tags(self) -> None:
        family = self.font_family
        self.text.tag_configure("h1", font=(family, 18, "bold"), foreground=TEXT, spacing1=10, spacing3=8)
        self.text.tag_configure("h2", font=(family, 14, "bold"), foreground=ACCENT, spacing1=12, spacing3=6)
        self.text.tag_configure("h3", font=(family, 12, "bold"), foreground=TEXT, spacing1=8, spacing3=4)
        self.text.tag_configure("body", font=(family, 10), foreground=TEXT, lmargin1=0, lmargin2=0)
        self.text.tag_configure("bullet", font=(family, 10), foreground=TEXT, lmargin1=18, lmargin2=30)
        self.text.tag_configure("code", font=("Consolas", 9), foreground=CODE_FG, background=CODE_BG, lmargin1=18, lmargin2=18)
        self.text.tag_configure("quote", font=(family, 10, "italic"), foreground=MUTED, lmargin1=18, lmargin2=18)
        self.text.tag_configure("warning", font=(family, 10, "bold"), foreground=WARN)

    def load_file(self, path: Path) -> bool:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.set_text(f"无法读取教程 {path}: {exc}")
            return False
        self.render(content)
        return True

    def set_text(self, content: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", content, "body")
        self.text.configure(state="disabled")

    def render(self, markdown: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        in_code = False
        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            if line.strip().startswith("```"):
                in_code = not in_code
                if not in_code:
                    self.text.insert("end", "\n")
                continue
            if in_code:
                self.text.insert("end", line + "\n", "code")
                continue
            if not line.strip():
                self.text.insert("end", "\n")
                continue
            if line.startswith("### "):
                self.text.insert("end", line[4:].strip() + "\n", "h3")
            elif line.startswith("## "):
                self.text.insert("end", line[3:].strip() + "\n", "h2")
            elif line.startswith("# "):
                self.text.insert("end", line[2:].strip() + "\n", "h1")
            elif line.lstrip().startswith(("- ", "* ")):
                self.text.insert("end", "• " + line.lstrip()[2:].strip() + "\n", "bullet")
            elif re.match(r"^\d+\.\s+", line.strip()):
                self.text.insert("end", line.strip() + "\n", "bullet")
            elif line.startswith(">"):
                self.text.insert("end", line.lstrip("> ").strip() + "\n", "quote")
            else:
                self.text.insert("end", line + "\n", "body")
        self.text.configure(state="disabled")
