"""Library preferences and the small bookplate used in the navigation rail."""

import os
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

THEMES = {
    "纸白": ("#f7f8f4", "#f1f5f0"),
    "暖杏": ("#faf0df", "#faf4e9"),
    "鼠尾草": ("#e4eee3", "#edf4ed"),
    "雾蓝": ("#e5edf4", "#edf3f8"),
}


def bookplate(parent):
    """A book stack and a pressed sprig, in the colours of the library rail."""
    c = tk.Canvas(parent, width=150, height=66, bg=parent["bg"], highlightthickness=0,
                  borderwidth=0, takefocus=False)
    c.create_line(9, 57, 139, 57, fill="#537568")
    for x, y, width, colour in ((23, 49, 73, "#bdd0ad"), (29, 40, 62, "#d3a675"),
                                (19, 31, 78, "#91b5a2")):
        c.create_rectangle(x, y, x + width, y + 7, fill=colour, outline="")
        c.create_line(x + 6, y + 1, x + 6, y + 6, fill="#476758")
        c.create_line(x + 13, y + 4, x + width - 5, y + 4, fill="#587866")
    c.create_polygon(69, 30, 75, 30, 75, 40, 72, 37, 69, 40, fill="#e8bd7b")
    c.create_line(96, 51, 107, 38, 115, 20, 126, 7, smooth=True, width=2, fill="#92b39a")
    for points in ((106, 39, 95, 34, 94, 25, 103, 29), (113, 29, 126, 26, 131, 18, 120, 21),
                   (116, 20, 107, 16, 108, 8, 114, 12), (121, 13, 122, 5, 131, 3, 128, 9)):
        c.create_polygon(points, fill="#8fae94", smooth=True)
    return c


def open_book(parent):
    c = tk.Canvas(parent, width=150, height=71, bg=parent["bg"], highlightthickness=0, takefocus=False)
    c.create_oval(19, 54, 131, 64, fill="#eaf0e8", outline="")
    c.create_oval(86, 7, 115, 36, fill="#fae7bf", outline="")
    for offset, color in ((4, "#507364"), (0, "#d8e5d8")):
        c.create_polygon(21, 22+offset, 39, 19+offset, 74, 28+offset, 108, 19+offset,
                         129, 23+offset, 125, 52+offset, 103, 49+offset, 74, 58+offset,
                         46, 49+offset, 25, 52+offset, fill=color, smooth=False)
    c.create_line(74, 28, 74, 55, fill="#8da696")
    for dy in (0, 6, 12):
        c.create_line(32, 27+dy, 46, 26+dy, 65, 32+dy, smooth=True, fill="#a0b4a5")
        c.create_line(82, 32+dy, 102, 25+dy, 117, 27+dy, smooth=True, fill="#a0b4a5")
    c.create_polygon(101, 21, 107, 20, 106, 35, 103, 33, 99, 37, fill="#b77a4b")
    return c


class Preferences(simpledialog.Dialog):
    def __init__(self, app):
        self.library = app.library
        super().__init__(app, "文献书房设置")

    def body(self, frame):
        frame.columnconfigure(0, weight=1)
        self.paths = {}
        for index, (key, label, value) in enumerate((
            ("storage", "新附件保存位置", str(self.library.storage)),
            ("export", "默认下载与导出位置", self.library.export_dir),
        )):
            ttk.Label(frame, text=label, style="Section.TLabel").grid(row=index*2, column=0, sticky="w", pady=(10, 3))
            row = ttk.Frame(frame)
            row.grid(row=index*2+1, column=0, sticky="ew")
            var = self.paths[key] = tk.StringVar(self, value)
            ttk.Entry(row, textvariable=var, width=49).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="浏览…", command=lambda v=var: self.browse(v)).pack(side="left", padx=(5,0))
        ttk.Label(frame, text="新导入的原文和新生成的译本使用新位置。已有附件继续从原位置读取。",
                  wraplength=405, style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Label(frame, text="书房背景", style="Section.TLabel").grid(row=5, column=0, sticky="w", pady=(7, 4))
        colors = ttk.Frame(frame)
        colors.grid(row=6, column=0, sticky="w")
        self.theme = tk.StringVar(self, self.library.preference("theme", "纸白"))
        for name, (color, _) in THEMES.items():
            tk.Radiobutton(colors, text=name, variable=self.theme, value=name, bg=color,
                           activebackground=color, selectcolor=color, padx=4).pack(side="left", padx=2)

    def browse(self, var):
        path = filedialog.askdirectory(parent=self, initialdir=var.get() or str(Path.home()))
        if path:
            var.set(path)

    def buttonbox(self):
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="保存", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(bar, text="取消", command=self.cancel).pack(side="right", padx=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        try:
            values = {"theme": self.theme.get()}
            for key, var in self.paths.items():
                path = Path(os.path.expandvars(var.get().strip())).expanduser()
                if not path.is_absolute():
                    raise ValueError("请输入完整的文件夹路径。")
                path = path.resolve()
                path.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryFile(dir=path):
                    pass
                values[key] = "" if key == "storage" and path == self.library.root else str(path)
            self.library.save_preferences(values)
        except (OSError, ValueError, sqlite3.Error) as exc:
            messagebox.showerror("无法保存设置", str(exc), parent=self)
            return False
        return True

    def apply(self):
        self.result = True
