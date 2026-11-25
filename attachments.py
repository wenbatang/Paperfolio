"""Live attachment list for the library inspector."""

from datetime import datetime
import tkinter as tk
from tkinter import ttk


def describe(label):
    parts = label.split(" · ")
    kind, details = parts[0], parts[1:]
    created = None
    if details:
        try:
            created = datetime.fromisoformat(details[-1])
            details.pop()
        except ValueError:
            pass
    names = {"zh-CN": "简体中文", "en": "英文", "ja": "日文", "排版": "保留排版", "段落": "段落对照"}
    subtitle = " · ".join(names.get(value, value) for value in details) or "PDF 文档"
    return kind, subtitle, created


class AttachmentPanel(ttk.Frame):
    def __init__(self, parent, app, paper):
        super().__init__(parent, padding=(10, 8))
        self.app, self.paper = app, paper
        self.rows = {}
        self.cards = {}
        self.selected = None
        self.signature = None
        self.timer = None
        self.count = tk.StringVar(self)

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, textvariable=self.count, style="Section.TLabel").pack(side="left")
        ttk.Button(head, text="刷新", image=app.icons.get("refresh", size=14), compound="left",
                   style="Quiet.TButton", command=self.refresh).pack(side="right")

        actions = ttk.Frame(self)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        self.read = ttk.Button(actions, text="阅读附件", image=app.icons.get("book", "white"),
                               compound="left", style="Accent.TButton", command=self.open)
        self.read.pack(side="left", fill="x", expand=True)
        self.export = ttk.Button(actions, text="另存为…", command=self.save)
        self.export.pack(side="left", padx=(6, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, width=1, height=110, bg="#f7f8f4", bd=0,
                                highlightthickness=0, takefocus=True)
        self.scroll = ttk.Scrollbar(body, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.set_scroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.listing = tk.Frame(self.canvas, bg="#f7f8f4")
        self.content = self.canvas.create_window(0, 0, anchor="nw", window=self.listing)
        self.canvas.bind("<Configure>", self.resize)
        self.listing.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Return>", lambda _: self.open())
        self.canvas.bind("<Up>", lambda _: self.move(-1))
        self.canvas.bind("<Down>", lambda _: self.move(1))
        self.canvas.bind("<F5>", lambda _: self.refresh())
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.listing.bind("<MouseWheel>", self.wheel)
        self.bind("<Map>", self.watch)
        self.bind("<Unmap>", self.stop_watch)

    def watch(self, _=None):
        self.stop_watch()
        if self.winfo_ismapped():
            self.refresh()
            self.timer = self.after(1800, self.watch)

    def stop_watch(self, _=None):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def destroy(self):
        self.stop_watch()
        super().destroy()

    def resize(self, event):
        self.canvas.itemconfigure(self.content, width=event.width)
        for _, _, subtitle in self.cards.values():
            subtitle.configure(wraplength=max(75, event.width - 78))

    def set_scroll(self, first, last):
        self.scroll.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.scroll.grid_remove()
        else:
            self.scroll.grid()

    def wheel(self, event):
        if self.canvas.yview() != (0.0, 1.0) and event.delta:
            step = max(1, abs(event.delta) // 120)
            self.canvas.yview_scroll(-step if event.delta > 0 else step, "units")
        return "break"

    def refresh(self):
        rows = self.app.library.files(self.paper["id"])
        signature = [(r["id"], r["label"], r["pages"]) for r in rows]
        if signature == self.signature:
            return
        self.signature = signature
        old_y = self.canvas.yview()[0]
        for child in self.listing.winfo_children():
            child.destroy()
        self.cards.clear()
        self.rows.clear()
        self.count.set(f"{len(rows)} 个文件")
        entries = [(r, *describe(r["label"])) for r in rows]
        entries.sort(key=lambda item: (item[1] == "原文", item[3].isoformat() if item[3] else ""), reverse=True)
        last_date = None
        for row, kind, subtitle, date in entries:
            if date and date != last_date:
                group = tk.Label(self.listing, text=date.strftime("%Y/%m/%d   %H:%M:%S"), anchor="w",
                                 bg="#f7f8f4", fg="#52675e", font=("Microsoft YaHei UI", 9))
                group.pack(fill="x", pady=(5, 4))
                group.bind("<MouseWheel>", self.wheel)
            last_date = date
            self.rows[row["id"]] = row
            self.add_card(row, kind, subtitle)
        if not rows:
            ttk.Label(self.listing, text="暂无本地 PDF", style="Section.TLabel").pack(pady=(28, 4))
            ttk.Label(self.listing, text="可重新导入原文，或将附件放回原位置。", wraplength=210,
                      style="Muted.TLabel").pack(padx=8)
        self.select(self.selected if self.selected in self.rows else next(iter(self.rows), None))
        for button in (self.read, self.export):
            button.state(["!disabled" if rows else "disabled"])
        self.canvas.yview_moveto(old_y)

    def add_card(self, row, kind, subtitle):
        styles = {"原文": ("file", "#326350", "#e3efe8"),
                  "译文": ("language", "#3c6489", "#e7eff7"),
                  "双语": ("dual", "#705387", "#f0eaf6")}
        icon, ink, tint = styles.get(kind, styles["原文"])
        card = tk.Frame(self.listing, bg="white", highlightthickness=1, highlightbackground="#d6e0d9",
                        padx=8, pady=7, cursor="hand2")
        card.pack(fill="x", pady=(0, 5), padx=1)
        card.columnconfigure(1, weight=1)
        badge = tk.Label(card, image=self.app.icons.get(icon, ink, 20), bg=tint, padx=6, pady=6)
        badge.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        title = {"原文": "原文 PDF", "双语": "双语对照"}.get(kind, kind)
        heading = tk.Label(card, text=title, anchor="w", bg="white", fg="#203c32",
                           font=("Microsoft YaHei UI", 11, "bold"))
        heading.grid(row=0, column=1, sticky="ew")
        pages = tk.Label(card, text=f"{row['pages']} 页", bg="white", fg="#5f7069",
                         font=("Microsoft YaHei UI", 9))
        pages.grid(row=0, column=2, sticky="e")
        detail = tk.Label(card, text=subtitle, justify="left", anchor="w", fg="#546b60", bg="white",
                          wraplength=max(75, self.canvas.winfo_width()-78), font=("Microsoft YaHei UI", 9))
        detail.grid(row=1, column=1, columnspan=2, sticky="ew")
        fid = row["id"]
        self.cards[fid] = card, (heading, pages, detail), detail
        for widget in (card, badge, heading, pages, detail):
            widget.bind("<Button-1>", lambda _, n=fid: self.select(n, focus=True))
            widget.bind("<Double-1>", lambda _, n=fid: self.open(n))
            widget.bind("<MouseWheel>", self.wheel)

    def select(self, fid, focus=False):
        self.selected = fid
        if focus:
            self.canvas.focus_set()
        for key, (card, labels, _) in self.cards.items():
            bg, border = ("#eaf4ef", "#63977e") if key == fid else ("white", "#d6e0d9")
            card.configure(bg=bg, highlightbackground=border)
            for widget in labels:
                widget.configure(bg=bg)

    def move(self, offset):
        if self.selected in self.rows:
            ids = list(self.rows)
            fid = ids[max(0, min(len(ids) - 1, ids.index(self.selected) + offset))]
            self.select(fid)
            card = self.cards[fid][0]
            top, bottom = card.winfo_y(), card.winfo_y() + card.winfo_height()
            view = self.canvas.canvasy(0)
            height = self.canvas.winfo_height()
            if top < view or bottom > view + height:
                target = top if top < view else bottom - height
                self.canvas.yview_moveto(target / max(1, self.listing.winfo_height()))
        return "break"

    def open(self, fid=None):
        fid = self.selected if fid is None else fid
        self.refresh()
        if fid in self.rows:
            self.app.workspace.open_pdf(self.paper, fid)

    def save(self):
        fid = self.selected
        self.refresh()
        if fid in self.rows:
            self.app.export_pdf(self.rows[fid])
