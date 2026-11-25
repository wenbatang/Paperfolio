"""Library preferences and previews of the decorative icon sets."""

import os
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import ImageTk

from ornaments import DENSITIES, PAPER_COLORS, STYLES, preference, ribbon


class Preferences(simpledialog.Dialog):
    def __init__(self, app):
        self.library = app.library
        version = Path(__file__).with_name("VERSION").read_text(encoding="ascii").strip()
        super().__init__(app, f"文献书房设置 · {version}")

    def body(self, frame):
        pages = ttk.Notebook(frame)
        pages.pack(padx=5, pady=4, fill="both", expand=True)
        appearance = ttk.Frame(pages, padding=10)
        storage = ttk.Frame(pages, padding=12)
        pages.add(appearance, text="外观与装饰")
        pages.add(storage, text="文件位置")
        self.style_key = tk.StringVar(self, preference(self.library))
        self.density = tk.StringVar(self, self.library.preference("ornament_density", DENSITIES[0]))
        self.theme = tk.StringVar(self, self.library.preference("theme", "随风格"))
        self.cards = {}
        for i, (key, group) in enumerate(STYLES.items()):
            sample = ribbon(key, 236, 44, group.tint, "丰富")
            image = ImageTk.PhotoImage(sample, master=self)
            button = tk.Button(appearance, text=group.title, image=image, compound="top", bg=group.tint,
                               fg=group.rail, activebackground=group.tint, relief="flat", bd=0,
                               padx=2, pady=4, highlightthickness=2, cursor="hand2",
                               command=lambda k=key: self.choose(k))
            button.photo = image
            button.grid(row=i//2, column=i%2, padx=4, pady=4, sticky="ew")
            self.cards[key] = button
        self.choose(self.style_key.get())
        options = ttk.Frame(appearance)
        options.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=(10,3))
        for label, var, choices in (("装饰密度", self.density, DENSITIES),
                                    ("纸色", self.theme, ("随风格", *PAPER_COLORS))):
            ttk.Label(options, text=label).pack(side="left", padx=(0,4))
            ttk.Combobox(options, textvariable=var, values=choices, width=7,
                         state="readonly").pack(side="left", padx=(0,12))
        storage.columnconfigure(0, weight=1)
        self.paths = {}
        for index, (key, label, value) in enumerate((
            ("storage", "新附件保存位置", str(self.library.storage)),
            ("export", "默认下载与导出位置", self.library.export_dir),
        )):
            ttk.Label(storage, text=label, style="Section.TLabel").grid(row=index*2, column=0, sticky="w", pady=(10, 3))
            row = ttk.Frame(storage)
            row.grid(row=index*2+1, column=0, sticky="ew")
            var = self.paths[key] = tk.StringVar(self, value)
            ttk.Entry(row, textvariable=var, width=49).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="浏览…", command=lambda v=var: self.browse(v)).pack(side="left", padx=(5,0))
        ttk.Label(storage, text="新导入的原文和新生成的译本使用新位置。已有附件继续从原位置读取。",
                  wraplength=405, style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=8)

    def choose(self, key):
        self.style_key.set(key)
        for k, button in self.cards.items():
            group = STYLES[k]
            button.configure(text=("✓  " if k == key else "") + group.title,
                             highlightbackground=group.accent if k == key else group.tint,
                             highlightcolor=group.accent)

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
            values = {"theme": self.theme.get(), "ornament_style": self.style_key.get(),
                      "ornament_density": self.density.get()}
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
