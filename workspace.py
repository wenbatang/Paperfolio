"""Main window tabs and commands shared by the library and its readers."""

import sqlite3
import tkinter as tk
from collections import deque
from tkinter import font, messagebox, ttk

from reader import Reader
from library import PaperEdit
from ornaments import MotifStrip, mix


class Workspace(ttk.Frame):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.closed = deque(maxlen=20)
        icon = app.icons.get
        header = self.header = tk.Frame(self, bg="#183d37", padx=15, pady=6)
        header.pack(fill="x")
        tk.Label(header, text="  Paperfolio", image=icon("brand", size=27), compound="left",
                 bg="#183d37", fg="#fbfcf7", font=("Georgia", 16, "bold")).pack(side="left")
        self.chooser = tk.Menu(header, tearoff=False)
        self.chooser.configure(postcommand=self.populate_tabs)
        def header_icon(name):
            return icon(name, "#d5eadd")
        switch = ttk.Menubutton(header, text="标签页", image=header_icon("tabs"), compound="left",
                                style="Header.TMenubutton", menu=self.chooser)
        switch.pack(side="right", padx=(4, 0))
        self.close_button = ttk.Button(header, text="关闭标签", image=header_icon("close"), compound="left", style="Header.TButton",
                                       command=self.close_tab)
        self.close_button.pack(side="right", padx=2)
        ttk.Button(header, text="快捷键", image=header_icon("keyboard"), compound="left", style="Header.TButton",
                   command=self.show_help).pack(side="right", padx=2)
        self.redo = ttk.Button(header, text="重做", image=header_icon("redo"), compound="left", style="Header.TButton",
                               command=lambda: self.step(True))
        self.undo = ttk.Button(header, text="撤销", image=header_icon("undo"), compound="left",
                               style="Header.TButton", command=self.step)
        for button in (self.redo,self.undo):
            button.pack(side="right", padx=2)
        self.header_motifs = MotifStrip(header, dark=True, offset=0)
        self.header_motifs.pack(side="left", fill="both", expand=True)
        self.tabs = ttk.Notebook(self, style="Workspace.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        self.catalog = ttk.Frame(self.tabs)
        self.tabs.add(self.catalog, text="文献库", image=icon("book"), compound="left")
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.tabs.bind("<Configure>", self.fit_titles)
        self.tabs.bind("<Button-2>", self.middle_close)
        self.tab_menu = tk.Menu(self.tabs, tearoff=False)
        self.tabs.bind("<Button-3>", self.tab_context)
        self.refresh_history()

    def recolor(self, palette):
        self.header_motifs.theme(self.app.ornament_style, self.app.density, palette.rail)
        self.header.configure(bg=palette.rail)
        for child in self.header.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(bg=palette.rail)
        style = ttk.Style(self)
        for key in ("Header.TButton", "Header.TMenubutton"):
            tone = mix(palette.rail, "white", .09)
            style.configure(key, background=tone, lightcolor=tone, darkcolor=tone)
            style.map(key, background=[("disabled", palette.rail), ("active", palette.accent)])
        for reader in self.readers():
            reader.canvas.configure(bg=palette.tint)

    def current(self):
        selected = self.tabs.select()
        if selected:
            widget = self.tabs.nametowidget(selected)
            return widget if isinstance(widget, Reader) else None

    def readers(self):
        return [self.tabs.nametowidget(path) for path in self.tabs.tabs() if path != str(self.catalog)]

    def tab_changed(self, _=None):
        r = self.current()
        self.close_button.state(["!disabled" if r else "disabled"])
        self.app.title((r.paper["title"] + "  ·  " if r else "") + "Paperfolio · 文献书房")
        if r:
            r.canvas.focus_set()

    def populate_tabs(self):
        self.chooser.delete(0, "end")
        self.chooser.add_command(label="文献库", command=lambda: self.tabs.select(self.catalog))
        for r in self.readers():
            self.chooser.add_command(label=r.paper["title"] + " · " + r.file["label"],
                                     command=lambda w=r: self.tabs.select(w))
        self.chooser.add_separator()
        self.chooser.add_command(label="重新打开关闭的标签", accelerator="Ctrl+Shift+T",
                                 state="normal" if self.closed else "disabled", command=self.reopen)

    def fit_titles(self, _=None):
        readers = self.readers()
        if not readers:
            return
        face = font.nametofont("TkDefaultFont")
        width = self.tabs.winfo_width()
        budget = min(200, max(32, (width - 110) // len(readers) - 50))
        for reader in readers:
            title = reader.paper["title"]
            suffix = "" if reader.file["label"] == "原文" else " · " + reader.file["label"].split(" · ")[0]
            short = title[:48]
            while short and face.measure(short + ("…" if short != title else "") + suffix) > budget:
                short = short[:-1]
            label = short + ("…" if short != title else "") + suffix
            if self.tabs.tab(reader, "text") != label:
                self.tabs.tab(reader, text=label)

    def open_pdf(self, paper, fid=None, page=None):
        files = self.app.library.files(paper["id"])
        if not files or (fid is not None and not any(f["id"] == fid for f in files)):
            messagebox.showinfo("附件不可用", "本地 PDF 已被移动或删除。将文件放回原位置后即可再次阅读。",
                                parent=self.app)
            return
        fid = files[0]["id"] if fid is None else fid
        r = next((r for r in self.readers() if r.file["id"] == fid), None)
        if r is None:
            r = Reader(self.tabs, self.app, paper, fid, page, files)
            if not r.winfo_exists():
                return
            self.tabs.add(r, image=self.app.icons.get("file"), compound="left")
            self.fit_titles()
            self.closed = deque((item for item in self.closed if item[1] != fid), maxlen=20)
        self.tabs.select(r)
        if page is not None:
            r.go(page)
        self.app.lift()
        r.canvas.focus_set()
        return r

    def close_tab(self, reader=None):
        reader = reader or self.current()
        if reader:
            self.closed.append((reader.paper, reader.file["id"], reader.pending_page or reader.page, reader.zoom))
            self.tabs.forget(reader)
            reader.destroy()
            self.fit_titles()

    def reopen(self):
        if self.closed:
            paper, fid, page, zoom = self.closed.pop()
            reader = self.open_pdf(paper, fid, page)
            if reader:
                reader.zoom = zoom
                reader.pending_page = page
                reader.layout()

    def tab_context(self, event):
        try:
            index = self.tabs.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        menu = self.tab_menu
        menu.delete(0, "end")
        if index:
            reader = self.tabs.nametowidget(self.tabs.tabs()[index])
            menu.add_command(label="关闭此标签", command=lambda: self.close_tab(reader))
        menu.add_command(label="重新打开关闭的标签", state="normal" if self.closed else "disabled",
                         command=self.reopen)
        menu.tk_popup(event.x_root, event.y_root)

    def middle_close(self, event):
        try:
            index = self.tabs.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        if index:
            self.close_tab(self.tabs.nametowidget(self.tabs.tabs()[index]))

    def cycle(self, delta):
        self.tabs.select((self.tabs.index("current") + delta) % len(self.tabs.tabs()))

    def refresh_history(self):
        for btn, stack in ((self.undo,self.app.library.undo_stack),(self.redo,self.app.library.redo_stack)):
            btn.state(["!disabled" if stack else "disabled"])

    def step(self, redo=False):
        try:
            edit = self.app.library.history_step(redo)
        except (sqlite3.Error, ValueError) as exc:
            messagebox.showerror("无法更改记录", str(exc), parent=self.app)
            return
        if not edit:
            return
        if isinstance(edit, PaperEdit):
            ids = self.app.selection()
            if not ids or not edit.previous.keys().isdisjoint(ids):
                ids = tuple(dict.fromkeys((*ids, *edit.previous)))
            self.app.refresh(ids)
            text = ("已重做 · " if redo else "已撤销 · ") + edit.label + f"（{len(edit.previous)} 篇）"
            self.app.status.set(text)
            if self.current():
                self.current().caption.configure(text=text)
            return
        row = edit.after or edit.before
        if edit.table == "notes":
            self.app.draw_detail()
        for reader in self.readers():
            if reader.file["id"] == row["file"]:
                if edit.table == "highlights":
                    reader.marks_changed(row["page"])
                elif edit.table == "bookmarks":
                    reader.refresh_navigation()
        text = ("已重做 · " if redo else "已撤销 · ") + edit.label + f"（第 {row['page']} 页）"
        self.app.status.set(text)
        if self.current():
            self.current().caption.configure(text=text)

    def bind_keys(self):
        app = self.app
        def shortcut(sequence, command, *, editing=True):
            def handle(event):
                if not editing and event.widget.winfo_class() in ("Text", "Entry", "TEntry", "TCombobox"):
                    return
                command()
                return "break"
            app.bind(sequence, handle)
        shortcut("<Control-o>", app.import_files)
        shortcut("<Control-f>", lambda: (self.current().search if self.current() else app.search).focus_set())
        shortcut("<Control-w>", self.close_tab)
        shortcut("<Control-Shift-T>", self.reopen)
        shortcut("<Control-Tab>", lambda: self.cycle(1))
        shortcut("<Control-Shift-Tab>", lambda: self.cycle(-1))
        shortcut("<Control-z>", self.step, editing=False)
        for key in ("<Control-y>", "<Control-Shift-Z>"):
            shortcut(key, lambda: self.step(True), editing=False)
        shortcut("<F1>", self.show_help)
        for key, command in (
            ("<Control-d>", lambda r: r.toggle_bookmark()), ("<Control-g>", lambda r: r.focus_page()),
            ("<Control-equal>", lambda r: r.scale(1.25)), ("<Control-plus>", lambda r: r.scale(1.25)),
            ("<Control-minus>", lambda r: r.scale(0.8)), ("<Control-0>", lambda r: r.scale(0)),
            ("<Control-Shift-N>", lambda r: r.note()), ("<Prior>", lambda r: r.canvas.yview_scroll(-1,"pages")),
            ("<Next>", lambda r: r.canvas.yview_scroll(1,"pages")),
        ):
            shortcut(key, lambda action=command: self.current() and action(self.current()), editing=False)

    def show_help(self):
        messagebox.showinfo("快捷键", "文献库与标签页\nCtrl+O　导入 PDF\nCtrl+Tab / Ctrl+Shift+Tab　切换标签\n"
            "Ctrl+W　关闭当前阅读标签\nCtrl+Shift+T　重新打开关闭的标签\nCtrl+F　搜索当前文献库或 PDF\n\n"
            "文献列表\nCtrl+A　全选当前结果\nShift+F10　所选文献菜单\nDelete　移入回收站\nEsc　清空选择\n\n"
            "阅读与整理\nCtrl+Z　撤销文献整理、笔记、高亮或书签操作\nCtrl+Y / Ctrl+Shift+Z　重做\n"
            "Ctrl+D　添加或移除本页书签\nCtrl+G　跳到页码框\nCtrl+Shift+N　记笔记\n"
            "Ctrl++ / Ctrl+−　缩放\nCtrl+0　适宽\nPage Up / Down　上下滚动", parent=self.app)
