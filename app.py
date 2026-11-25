"""Paperfolio · Windows local paper library and PDF reader."""

import shutil
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, simpledialog, ttk

from library import Library
from attachments import AttachmentPanel
from paper_actions import PaperActions
from icons import Icons
from workspace import Workspace
from translation_window import TranslationWindow
from study_window import StudyWindow
from ornaments import DENSITIES, PAPER_COLORS, STYLES, MotifStrip, mix, preference
from settings import Preferences

HERE = Path(__file__).resolve().parent
PAPER, INK, MUTED, PINE = "#f7f8f4", "#233c34", "#63746b", "#174b3e"
SIDEBAR, SIDE_TEXT = "#183c33", "#e6efe7"
FONT = "Microsoft YaHei UI"


class MetadataDialog(simpledialog.Dialog):
    def __init__(self, parent, paper, collections):
        self.paper, self.collections = paper, collections
        super().__init__(parent, "编辑文献信息")

    def body(self, frame):
        self.fields = {}
        for i, (key, name) in enumerate(
            (("title", "标题"), ("author", "作者"), ("year", "年份"), ("doi", "DOI"), ("tags", "标签"))
        ):
            ttk.Label(frame, text=name).grid(row=i, column=0, sticky="w", padx=8)
            entry = ttk.Entry(frame, width=52)
            entry.insert(0, self.paper[key])
            entry.grid(row=i, column=1, pady=4)
            self.fields[key] = entry
        ttk.Label(frame, text="分类").grid(row=5, column=0, sticky="w", padx=8)
        self.collection = ttk.Combobox(
            frame, values=["未分类"] + [r["name"] for r in self.collections], state="readonly", width=50
        )
        self.collection.current(
            next((i + 1 for i, r in enumerate(self.collections) if r["id"] == self.paper["collection"]), 0)
        )
        self.collection.grid(row=5, column=1, pady=4)
        return self.fields["title"]

    def validate(self):
        if self.fields["title"].get().strip():
            return True
        messagebox.showinfo("缺少标题", "请输入文献标题", parent=self)
        return False

    def apply(self):
        self.result = {k: v.get().strip() for k, v in self.fields.items()}
        i = self.collection.current()
        self.result["collection"] = self.collections[i - 1]["id"] if i else None


class App(tk.Tk):
    def __init__(self, root_dir=None):
        super().__init__()
        self.title("Paperfolio · 文献书房")
        self.geometry("1220x760")
        self.minsize(950, 610)
        self.library = Library(root_dir or HERE / "data")
        self.ornament_style = preference(self.library)
        self.palette = STYLES[self.ornament_style]
        self.density = self.library.preference("ornament_density", DENSITIES[0])
        self.view, self.pid = "all", None
        self.selected_ids = ()
        self.detail_index = 0
        self.multi = tk.BooleanVar(self, False)
        self.translation = None
        self.study = None
        self.order, self.desc = "added", True
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="本地文献库")
        self.setup_style()
        self.icons = Icons(self)
        self.iconphoto(True, self.icons.get("brand", size=32), self.icons.get("brand", size=16))
        self.workspace = Workspace(self)
        self.workspace.pack(fill="both", expand=True)
        self.library.on_history_change = self.workspace.refresh_history
        self.build_sidebar()
        self.paper_actions = PaperActions(self)
        main = ttk.Frame(self.workspace.catalog, padding=(22, 18, 22, 8))
        main.pack(side="left", fill="both", expand=True)
        head = ttk.Frame(main)
        head.pack(fill="x", pady=(0, 15))
        head.columnconfigure(0, weight=1)
        title_area = ttk.Frame(head)
        title_area.grid(row=0, column=0, rowspan=2, sticky="nsew")
        labels = ttk.Frame(title_area)
        labels.pack(side="left")
        self.heading = ttk.Label(labels, style="Title.TLabel")
        self.heading.pack(anchor="w")
        self.counter = ttk.Label(labels, style="Muted.TLabel")
        self.counter.pack(anchor="w")
        self.title_motifs = MotifStrip(title_area, offset=3)
        self.title_motifs.pack(side="left", fill="both", expand=True)
        ttk.Button(head, text="导入 PDF", image=self.icons.get("import","white"), compound="left",
                   style="Accent.TButton", command=self.import_files).grid(row=0, column=3, rowspan=2)
        self.multi_button = ttk.Checkbutton(head, text="多选", variable=self.multi, style="Select.Toolbutton",
                                            command=self.toggle_multi)
        self.multi_button.grid(row=0, column=1, rowspan=2)
        self.search_box = tk.Frame(head, bg="white", highlightthickness=1, highlightbackground="#cbd9d1",
                                   padx=7, pady=4)
        self.search_box.grid(row=0, column=2, rowspan=2, padx=10)
        glass = tk.Label(self.search_box, image=self.icons.get("search", "#62796d"), bg="white")
        glass.grid(row=0, column=0, padx=(0, 5))
        self.search = tk.Entry(self.search_box, textvariable=self.query, width=24, bd=0,
                               highlightthickness=0, fg=INK, bg="white", insertbackground=PINE)
        self.search.grid(row=0, column=1, sticky="ew", ipady=3)
        self.search_hint = tk.Label(self.search_box, text="搜索标题、作者或标签", fg="#65786d",
                                    bg="white", cursor="xterm", bd=0)
        for widget in (glass, self.search_hint):
            widget.bind("<Button-1>", lambda _: self.search.focus_set())
        self.clear_search = tk.Button(self.search_box, text="清除", fg=PINE, bg="white", bd=0,
                                      command=lambda: self.query.set(""))
        self.search_box.columnconfigure(2, minsize=32)
        self.clear_search.grid(row=0, column=2)
        self.search.bind("<FocusIn>", self.search_state)
        self.search.bind("<FocusOut>", self.search_state)
        body = ttk.Panedwindow(main, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.table_zone = ttk.Frame(body)
        body.add(self.table_zone, weight=3)
        self.table = ttk.Treeview(
            self.table_zone, columns=("title", "author", "year"), show="headings", selectmode="extended"
        )
        for key, label, width in (
            ("title", "文献标题", 310),
            ("author", "作者", 122),
            ("year", "年份", 60),
        ):
            self.table.heading(key, text=label, anchor="w", command=lambda k=key: self.sort(k))
            self.table.column(key, width=width, minwidth=45, stretch=key == "title")
        sy = ttk.Scrollbar(self.table_zone, command=self.table.yview)
        self.table.configure(yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.table.bind("<Button-1>", self.click_row)
        self.table.bind("<B1-Motion>", self.paper_actions.drag_motion)
        self.table.bind("<ButtonRelease-1>", self.paper_actions.release_row)
        self.table.bind("<Double-1>", self.double_click_row)
        self.table.bind("<Return>", lambda _: self.open_reader() if len(self.selection()) == 1 else None)
        self.table.bind("<Button-3>", self.paper_actions.context)
        self.table.bind("<Shift-F10>", self.paper_actions.keyboard_menu)
        self.table.bind("<Control-a>", self.select_all)
        self.table.bind("<Escape>", self.clear_selection)
        self.table.bind("<Delete>", lambda _: self.paper_actions.trash_shortcut())
        self.empty = tk.Frame(self.table_zone, bg="white")
        self.empty_title = tk.Label(self.empty, font=(FONT, 15, "bold"), bg="white", fg=INK)
        self.empty_title.pack(pady=8)
        self.empty_action = ttk.Button(self.empty, text="导入第一篇 PDF", command=self.import_files)
        self.inspector = ttk.Frame(body, padding=(16, 4, 0, 0), width=330)
        body.add(self.inspector, weight=1)
        ttk.Separator(main).pack(fill="x", pady=(12, 5))
        ttk.Label(main, textvariable=self.status, style="Muted.TLabel").pack(anchor="w")
        self.query.trace_add("write", lambda *_: self.refresh())
        self.workspace.bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme()
        self.refresh()

    def setup_style(self):
        font.nametofont("TkDefaultFont").configure(family=FONT, size=10)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=PAPER, foreground=INK)
        style.configure("Title.TLabel", font=(FONT, 22, "bold"))
        style.configure("Section.TLabel", font=(FONT, 12, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED, font=(FONT, 9))
        style.configure(
            "TButton",
            background="#eef2ec",
            borderwidth=1,
            bordercolor="#ccd8cd",
            lightcolor="#eef2ec",
            darkcolor="#eef2ec",
            padding=(8, 5),
        )
        style.map("TButton", background=[("active", "#dce8df")])
        style.configure("Select.Toolbutton", padding=(10, 5))
        style.map("Select.Toolbutton", background=[("selected", PINE), ("active", "#dce8df")],
                  foreground=[("selected", "white")])
        style.configure(
            "Accent.TButton",
            background=PINE,
            foreground="white",
            bordercolor=PINE,
            lightcolor=PINE,
            darkcolor=PINE,
            padding=(14, 7),
        )
        style.map("Accent.TButton", background=[("active", "#28614e"), ("disabled", "#75877c")])
        style.configure(
            "Treeview", rowheight=39, fieldbackground="white", background="white", borderwidth=0
        )
        style.configure("Treeview.Heading", background="#e7eee9", foreground="#40594a",
                        lightcolor="#e7eee9", darkcolor="#e7eee9", bordercolor="#d9e3dc",
                        relief="flat", font=(FONT, 9, "bold"), padding=(8, 7))
        style.map("Treeview", background=[("selected", "#ccdfd1")], foreground=[("selected", "#143e30")])
        style.configure("TNotebook", bordercolor="#cbd8cd", background=PAPER)
        style.configure("TNotebook.Tab", padding=(10, 6), background="#e8eee7")
        style.map("TNotebook.Tab", background=[("selected", "#f7f8f4")])
        style.configure("Inspector.TNotebook", borderwidth=0, background="#e7eee8")
        style.configure("Inspector.TNotebook.Tab", padding=(9, 6), borderwidth=0)
        style.map("Inspector.TNotebook.Tab", background=[("selected", "#daeae0"), ("active", "#eef4ef")],
                  foreground=[("selected", "#174b3e")])
        style.configure("Quiet.TButton", background=PAPER, borderwidth=0, padding=(5, 3), foreground=PINE)
        style.configure("Workspace.TNotebook", background="#dfebe4", borderwidth=0, tabmargins=(8,4,8,0))
        style.configure("Workspace.TNotebook.Tab", padding=(12,7), background="#dfebe4", borderwidth=0)
        style.map("Workspace.TNotebook.Tab", background=[("selected",PAPER),("active","#ebf1ed")],
                  foreground=[("selected",PINE)])
        for header_style in ("Header.TButton", "Header.TMenubutton"):
            style.configure(header_style, background="#285048", foreground="#eef6ef", borderwidth=0,
                            lightcolor="#285048", darkcolor="#285048", padding=(9,4), arrowsize=10)
            style.map(header_style, background=[("disabled","#203f39"),("active","#39675c")],
                      foreground=[("disabled","#91a59d"),("active","white")])
        style.configure("TEntry", bordercolor="#b9cabe", lightcolor="white", darkcolor="white")

    def build_sidebar(self):
        self.side = tk.Frame(self.workspace.catalog, bg=SIDEBAR, width=178)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        self.nav_buttons = {}
        for key, name in (("all", "全部文献"), ("unfiled", "未分类"), ("star", "已加星标"), ("trash", "回收站")):
            btn = self.side_button(self.side, name, lambda k=key: self.switch(k))
            btn.configure(image=self.icons.get({"all":"book", "unfiled":"tabs", "star":"star", "trash":"trash"}[key],
                                               "#d5eadd"), compound="left", text="  "+name)
            if key == "all":
                btn.pack_configure(pady=(18,1))
            self.nav_buttons[key] = btn
        section = tk.Frame(self.side, bg=SIDEBAR)
        section.pack(fill="x", padx=18, pady=(25, 5))
        tk.Label(section, text="我的分类", bg=SIDEBAR, fg="#abc4b5", font=(FONT, 9)).pack(side="left")
        tk.Button(
            section,
            text="＋",
            command=self.new_collection,
            bg=SIDEBAR,
            fg=SIDE_TEXT,
            bd=0,
            cursor="hand2",
            activebackground=PINE,
            activeforeground="white",
        ).pack(side="right")
        self.collection_space = tk.Frame(self.side, bg=SIDEBAR)
        self.collection_space.pack(fill="both", expand=True, padx=10, pady=4)
        self.collection_space.rowconfigure(0, weight=1)
        self.collection_space.columnconfigure(0, weight=1)
        self.collections = tk.Listbox(
            self.collection_space, height=1,
            bg=SIDEBAR,
            fg=SIDE_TEXT,
            bd=0,
            highlightthickness=0,
            activestyle="none",
            selectbackground="#365e50",
            selectforeground="white",
            exportselection=False,
            font=(FONT, 11),
        )
        self.collections.grid(row=0, column=0, sticky="nsew", padx=8)
        self.collections.bind("<<ListboxSelect>>", self.select_collection)
        self.side_motifs = MotifStrip(self.collection_space, dark=True, offset=2, cluster=True)
        self.side_motifs.grid(row=1, column=0, sticky="ew")
        self.collection_space.bind("<Configure>", self.fit_side_motifs)
        settings = self.side_button(self.side, "  设置", self.preferences)
        settings.configure(image=self.icons.get("settings", "#d5eadd"), compound="left")
        settings.pack_configure(side="bottom", before=self.collection_space, pady=(2, 8))
        self.reload_collections()

    def apply_theme(self):
        self.ornament_style = preference(self.library)
        self.palette = group = STYLES[self.ornament_style]
        self.density = self.library.preference("ornament_density", DENSITIES[0])
        name = self.library.preference("theme", "随风格")
        background, stripe = PAPER_COLORS.get(name, (group.paper, mix(group.tint, "white", .45)))
        self.paper_color = background
        style = ttk.Style(self)
        for key in (".", "TNotebook", "Quiet.TButton"):
            style.configure(key, background=background)
        style.map("TNotebook.Tab", background=[("selected", background)])
        self.table.tag_configure("alt", background=stripe)
        style.configure("Accent.TButton", background=group.accent, bordercolor=group.accent,
                        lightcolor=group.accent, darkcolor=group.accent)
        style.map("Accent.TButton", background=[("disabled", "#79827b"), ("active", group.rail)])
        style.configure("Treeview.Heading", background=group.tint, lightcolor=group.tint,
                        darkcolor=group.tint, bordercolor=group.tint, foreground=group.rail)
        style.map("Treeview", background=[("selected", mix(group.tint, group.accent, .16))],
                  foreground=[("selected", group.rail)])
        style.configure("Workspace.TNotebook", background=group.tint)
        style.configure("Workspace.TNotebook.Tab", background=group.tint)
        style.map("Workspace.TNotebook.Tab", background=[("selected", background), ("active", group.tint)],
                  foreground=[("selected", group.rail)])
        style.map("Inspector.TNotebook.Tab", background=[("selected", group.tint), ("active", background)],
                  foreground=[("selected", group.rail)])
        self.side.configure(bg=group.rail)
        for child in self.side.winfo_children():
            child.configure(bg=group.rail)
            if isinstance(child, tk.Button):
                child.configure(activebackground=self.nav_active)
            elif isinstance(child, tk.Frame):
                for item in child.winfo_children():
                    item.configure(bg=group.rail)
        self.collections.configure(selectbackground=self.nav_active)
        for key, btn in self.nav_buttons.items():
            btn.configure(bg=self.nav_active if key == self.view else group.rail)
        self.title_motifs.theme(self.ornament_style, self.density, background)
        self.side_motifs.theme(self.ornament_style, self.density, group.rail)
        self.workspace.recolor(group)
        self.fit_side_motifs()

    @property
    def nav_active(self):
        return mix(self.palette.rail, "white", .18)

    def fit_side_motifs(self, _=None):
        # The list gets its full height as soon as its rows need the space.
        bounds = self.collections.bbox(0) if self.collections.size() else None
        line = bounds[3] if bounds else font.Font(font=self.collections.cget("font")).metrics("linespace")
        spare = self.collection_space.winfo_height() - (line + 2)*self.collections.size() - 10
        if self.density == "关闭" or spare < 42:
            self.side_motifs.grid_remove()
        else:
            self.side_motifs.configure(height=min(spare, 112))
            self.side_motifs.grid()

    def preferences(self):
        if Preferences(self).result:
            self.apply_theme()
            self.draw_detail()
            self.status.set("已保存设置")

    def side_button(self, parent, label, command):
        button = tk.Button(
            parent,
            text=label,
            command=command,
            bg=SIDEBAR,
            fg=SIDE_TEXT,
            bd=0,
            anchor="w",
            padx=14,
            pady=7,
            activebackground="#365e50",
            activeforeground="white",
            cursor="hand2",
        )
        button.pack(fill="x", padx=9, pady=1)
        return button

    def reload_collections(self):
        self.groups = self.library.db.execute(
            "SELECT * FROM collections ORDER BY name COLLATE NOCASE"
        ).fetchall()
        self.collections.delete(0, "end")
        for g in self.groups:
            self.collections.insert("end", g["name"])
        self.fit_side_motifs()

    def new_collection(self):
        name = simpledialog.askstring("新建分类", "分类名称", parent=self)
        if name and name.strip():
            try:
                with self.library.db:
                    cid = self.library.db.execute(
                        "INSERT INTO collections(name) VALUES(?)", (name.strip(),)
                    ).lastrowid
                self.reload_collections()
                self.switch(cid)
            except sqlite3.IntegrityError:
                messagebox.showinfo("分类已存在", "请使用其他名称", parent=self)

    def select_collection(self, _):
        selected = self.collections.curselection()
        if selected:
            cid = self.groups[selected[0]]["id"]
            if self.view != cid:
                self.switch(cid)

    def switch(self, view):
        self.paper_actions.end_drag()
        self.view, self.pid = view, None
        self.multi.set(False)
        self.table.selection_remove(self.table.selection())
        self.query.set("")

    def sort(self, key):
        self.desc = not self.desc if self.order == key else False
        self.order = key
        self.refresh()
        if self.table.focus():
            self.table.see(self.table.focus())

    def search_state(self, _=None):
        focused = str(self.tk.call("focus")) == str(self.search)
        self.search_box.configure(highlightbackground="#54836a" if focused else "#cbd9d1")
        if self.query.get() or focused:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(in_=self.search, x=0, rely=0.5, anchor="w")
        if self.query.get():
            self.clear_search.grid()
        else:
            self.clear_search.grid_remove()

    def refresh(self, prefer=None):
        self.search_state()
        names = {"all": "全部文献", "unfiled": "未分类", "star": "已加星标", "trash": "回收站"}
        names.update({g["id"]: g["name"] for g in self.groups})
        self.heading.configure(text=names[self.view])
        for k, button in self.nav_buttons.items():
            button.configure(bg=self.nav_active if k == self.view else self.palette.rail)
        self.collections.selection_clear(0, "end")
        for i, g in enumerate(self.groups):
            if g["id"] == self.view:
                self.collections.selection_set(i)
        rows = self.library.papers(self.view, self.query.get())
        rows.sort(key=lambda r: r[self.order].casefold(), reverse=self.desc)
        wanted = self.selection() if prefer is None else ((prefer,) if isinstance(prefer, int) else prefer)
        focus = self.table.focus()
        view_top = self.table.yview()[0]
        self.table.delete(*self.table.get_children())
        self.rows = {r["id"]: r for r in rows}
        for i, r in enumerate(rows):
            self.table.insert(
                "",
                "end",
                iid=str(r["id"]),
                tags=("alt" if i % 2 else "base",),
                values=(("★  " if r["favorite"] else "") + r["title"], r["author"], r["year"]),
            )
        kept = [str(pid) for pid in wanted if pid in self.rows]
        if rows:
            self.empty.place_forget()
            if not kept and prefer is None and not self.multi.get() and len(wanted) < 2:
                kept = [str(rows[0]["id"])]
                view_top = 0
            self.table.selection_set(kept)
            self.table.focus(focus if focus in kept else kept[0] if kept else "")
            self.table.yview_moveto(view_top)
            if isinstance(prefer, int) and kept:
                self.table.see(kept[0])
        else:
            self.empty_action.pack_forget()
            if self.query.get():
                self.empty_title.configure(text="没有匹配的文献")
                self.empty_action.configure(text="清除搜索", command=self.clear_search.invoke)
                self.empty_action.pack(pady=5)
            else:
                titles = {
                    "all": "这里还没有文献", "unfiled": "没有待分类的文献",
                    "star": "还没有星标文献", "trash": "回收站是空的",
                }
                self.empty_title.configure(text=titles.get(self.view, "这个分类还没有文献"))
                if self.view not in ("star", "trash"):
                    label = "导入第一篇 PDF" if self.view == "all" else "导入 PDF"
                    self.empty_action.configure(text=label, command=self.import_files)
                    self.empty_action.pack(pady=5)
            self.empty.place(relx=0.5, rely=0.43, anchor="center")
        self.sync_selection(force=True)

    def selection(self):
        return tuple(map(int, self.table.selection()))

    def sync_selection(self, *, force=False):
        ids = self.selection()
        if force or ids != self.selected_ids:
            self.selected_ids = ids
            self.pid = ids[0] if len(ids) == 1 else None
            text = f"{len(self.rows)} 篇文献"
            if self.multi.get() or len(ids) > 1:
                text += f"  ·  已选 {len(ids)} 篇"
            self.counter.configure(text=text)
            self.draw_detail()

    def select(self, _=None):
        self.sync_selection()

    def select_all(self, _=None):
        self.table.selection_set(self.table.get_children())
        self.sync_selection()
        return "break"

    def clear_selection(self, _=None):
        self.paper_actions.end_drag()
        self.multi.set(False)
        self.deselect_all()
        return "break"

    def deselect_all(self):
        self.table.selection_remove(self.table.selection())
        self.sync_selection(force=True)
        self.table.focus_set()

    def toggle_multi(self):
        ids = self.table.selection()
        if self.multi.get() and len(ids) == 1:
            self.table.selection_remove(ids)
        elif not self.multi.get():
            focus = self.table.focus()
            self.table.selection_set([focus] if focus in ids else ids[:1])
        self.sync_selection(force=True)
        self.table.focus_set()

    def click_row(self, event):
        row = self.table.identify_row(event.y)
        region = self.table.identify_region(event.x, event.y)
        if not event.state & 0x0005:
            if row and region in ("tree", "cell"):
                return self.paper_actions.press_row(event, row)
            if not row and region == "nothing":
                self.deselect_all()
                return "break"

    def double_click_row(self, event):
        if self.multi.get() or len(self.table.selection()) > 1:
            return self.click_row(event)
        if self.table.identify_region(event.x, event.y) in ("tree", "cell"):
            row = self.table.identify_row(event.y)
            if row and not event.state & 0x0005:
                self.workspace.open_pdf(self.rows[int(row)])
            return "break"

    def import_files(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="导入论文", filetypes=[("PDF 文档", "*.pdf")]
        )
        if not paths:
            return
        added = existing = 0
        errors = []
        last = None
        for path in paths:
            try:
                last, fresh = self.library.import_pdf(
                    path, self.view if isinstance(self.view, int) else None
                )
                added += int(fresh)
                existing += int(not fresh)
            except Exception as e:
                errors.append(f"{Path(path).name}：{e}")
        if self.view in ("trash", "star") or (
            last and last not in [r["id"] for r in self.library.papers(self.view)]
        ):
            self.view = "all"
        self.query.set("")
        self.refresh(last)
        self.workspace.tabs.select(self.workspace.catalog)
        self.status.set(f"已导入 {added} 篇，复用已有记录 {existing} 篇")
        if errors:
            messagebox.showerror("部分文件无法导入", "\n".join(errors), parent=self)

    def draw_detail(self):
        if getattr(self, "detail_tabs", None) and self.detail_tabs.winfo_exists():
            self.detail_index = self.detail_tabs.index("current")
        for child in self.inspector.winfo_children():
            child.destroy()
        frame = self.inspector
        if len(self.selected_ids) > 1 or self.multi.get():
            self.paper_actions.draw(frame, self.selected_ids)
            return
        if not self.pid:
            ttk.Label(frame, text="文献详情", style="Section.TLabel").pack(anchor="w")
            ttk.Label(frame, text="选择文献后可查看附件和笔记。", style="Muted.TLabel").pack(
                anchor="w", pady=9
            )
            self.detail_motifs(frame)
            return
        r = self.rows[self.pid]
        ttk.Label(frame, text=r["title"], style="Section.TLabel", wraplength=280).pack(
            anchor="w", pady=(0, 6)
        )
        ttk.Label(frame, text=r["author"] or "作者未填写", wraplength=280, style="Muted.TLabel").pack(
            anchor="w"
        )
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=12)
        ttk.Button(actions, text="阅读", image=self.icons.get("book","white"), compound="left",
                   style="Accent.TButton", width=5, command=self.open_reader).pack(side="left")
        ttk.Button(actions, text="翻译原文", width=8, command=lambda: self.translate(r)).pack(side="left", padx=6)
        ttk.Button(
            actions,
            text="★" if r["favorite"] else "☆",
            width=3,
            command=lambda: self.update_flag("favorite"),
        ).pack(side="left")
        self.detail_tabs = book = ttk.Notebook(frame, style="Inspector.TNotebook")
        book.pack(fill="both", expand=True)
        info, notes = (ttk.Frame(book, padding=9) for _ in range(2))
        files = AttachmentPanel(book, self, r)
        for pane, name, icon in ((info, "条目信息", "outline"), (files, "附件", "clip"), (notes, "笔记", "note")):
            book.add(pane, text=name, image=self.icons.get(icon, size=14), compound="left")
        book.select(self.detail_index)
        collection = next((g["name"] for g in self.groups if g["id"] == r["collection"]), "未分类")
        details = ttk.Frame(info)
        details.pack(fill="x", pady=(4, 6))
        details.columnconfigure(1, weight=1)
        for label, value in (
            ("年份", r["year"]),
            ("DOI", r["doi"]),
            ("标签", r["tags"]),
            ("分类", collection),
            ("导入日期", r["added"][:10]),
        ):
            index = details.grid_size()[1]
            ttk.Label(details, text=label, style="Muted.TLabel").grid(row=index, column=0, sticky="nw", pady=5, padx=(0,10))
            ttk.Label(details, text=value or "—", wraplength=175).grid(row=index, column=1, sticky="w", pady=5)
        tools = ttk.Frame(info)
        tools.pack(anchor="w", pady=(10, 0))
        ttk.Button(tools, text="论文导读", style="Accent.TButton", command=lambda: self.open_study(r)).grid(
            row=0, column=0, sticky="ew", padx=(0, 4), pady=2
        )
        ttk.Button(tools, text="编辑信息与分类", command=self.edit).grid(
            row=0, column=1, sticky="ew", pady=2
        )
        self.detail_motifs(info)
        items = self.library.notes(self.pid)
        nlist = self.item_list(notes, items, lambda n: f"p. {n['page']}   {n['body'].splitlines()[0]}")
        preview = tk.Text(
            notes,
            height=6,
            width=20,
            wrap="word",
            bg=self.paper_color,
            fg=INK,
            bd=0,
            highlightthickness=0,
            state="disabled",
        )
        preview.pack(fill="both", expand=True, pady=5)

        def selected_note():
            return items[nlist.curselection()[0]] if nlist.curselection() else None

        def preview_note(_=None):
            note = selected_note()
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert(
                "1.0",
                f"{note['label']} · 第 {note['page']} 页\n\n{note['body']}"
                if note
                else "阅读时可选取文字并记笔记。",
            )
            preview.configure(state="disabled")

        def jump():
            if n := selected_note():
                self.open_reader(n["file"], n["page"])

        def delete_note():
            n = selected_note()
            if not n or not messagebox.askyesno(
                "删除笔记", f"删除第 {n['page']} 页的这条笔记？\n\n{n['body'][:90]}", parent=self
            ):
                return
            index = nlist.curselection()[0]
            self.library.delete_note(n["id"])
            items.pop(index)
            nlist.delete(index)
            if items:
                nlist.selection_set(min(index, len(items) - 1))
            preview_note()

        menu = tk.Menu(nlist, tearoff=False)
        menu.add_command(label="回到原文", command=jump)
        menu.add_command(label="删除笔记", command=delete_note)

        def note_menu(event):
            index = nlist.nearest(event.y)
            bounds = nlist.bbox(index) if items else None
            if bounds and bounds[1] <= event.y < bounds[1] + bounds[3]:
                nlist.focus_set()
                nlist.selection_clear(0, "end")
                nlist.selection_set(index)
                preview_note()
                menu.tk_popup(event.x_root, event.y_root)

        nlist.bind("<<ListboxSelect>>", preview_note)
        nlist.bind("<Double-1>", lambda _: jump())
        nlist.bind("<Button-3>", note_menu)
        nlist.bind("<Delete>", lambda _: delete_note())
        preview_note()
        note_actions = ttk.Frame(notes)
        note_actions.pack(side="bottom", before=nlist, fill="x", pady=3)
        ttk.Button(note_actions, text="回到笔记所在页", command=jump).pack(side="left")
        ttk.Button(note_actions, text="删除所选笔记", command=delete_note).pack(side="right")

    def detail_motifs(self, parent):
        if self.density == "关闭":
            return
        strip = MotifStrip(parent, offset=4, cluster=True)
        strip.theme(self.ornament_style, self.density, self.paper_color)
        strip.pack(fill="both", expand=True)  # Last in the pack order; uses leftover space only.

    def item_list(self, parent, items, label):
        box = tk.Listbox(
            parent,
            height=6,
            width=25,
            bg="white",
            fg=INK,
            bd=0,
            highlightthickness=1,
            highlightbackground="#cfdad0",
            activestyle="none",
            exportselection=False,
            selectbackground="#c9decd",
            selectforeground=INK,
        )
        box.pack(fill="both", expand=True, pady=(4, 6))
        for item in items:
            box.insert("end", label(item))
        if items:
            box.selection_set(0)
        return box

    def edit(self):
        result = MetadataDialog(self, self.rows[self.pid], self.groups).result
        if result:
            with self.library.db:
                self.library.db.execute(
                    """UPDATE papers SET title=:title, author=:author, year=:year,
                    tags=:tags, doi=:doi, collection=:collection WHERE id=:id""",
                    {**result, "id": self.pid},
                )
            self.refresh()

    def update_flag(self, field):
        if field not in ("favorite", "trashed") or not self.pid:
            return
        self.paper_actions.flag((self.pid,), field, 1 - self.rows[self.pid][field])

    def export_pdf(self, row):
        if row:
            target = filedialog.asksaveasfilename(
                parent=self,
                title="另存 PDF",
                initialdir=self.library.export_dir,
                defaultextension=".pdf",
                initialfile=f"paper-{self.pid}-{row['id']}.pdf",
                filetypes=[("PDF", "*.pdf")],
            )
            if target:
                try:
                    shutil.copyfile(self.library.root / row["path"], target)
                    self.status.set(f"已导出 {target}")
                except OSError as e:
                    messagebox.showerror("导出失败", str(e), parent=self)

    def export_citation(self, ids=None):
        ids = self.selection() if ids is None else ids
        if not ids:
            return
        records = [self.rows[i] for i in ids]
        target = filedialog.asksaveasfilename(
            parent=self, title=f"导出 {len(ids)} 篇文献的引用", defaultextension=".bib",
            initialdir=self.library.export_dir,
            filetypes=[("BibTeX", "*.bib")]
        )
        if target:
            try:
                Path(target).write_text("\n".join(self.library.bibtex(row) for row in records), encoding="utf-8")
                self.status.set(f"已导出 {len(ids)} 篇文献的引用")
            except OSError as e:
                messagebox.showerror("导出失败", str(e), parent=self)

    def open_reader(self, fid=None, page=None):
        if self.pid:
            return self.workspace.open_pdf(self.rows[self.pid], fid, page)

    def translate(self, paper, current=None):
        if not self.library.has_file(self.library.original_record(paper["id"])):
            messagebox.showinfo("原文不可用", "找不到原文 PDF，请重新导入同一份原文后再翻译。", parent=self)
            return
        if self.translation and self.translation.winfo_exists():
            if self.translation.proc:
                self.translation.lift()
                return
            self.translation.destroy()
        self.translation = TranslationWindow(self, paper, current)
        self.translation.lift()

    def translated(self, pid):
        self.refresh()
        for reader in self.workspace.readers():
            if reader.paper["id"] == pid:
                reader.refresh_versions()

    def open_study(self, paper):
        if self.study and self.study.winfo_exists():
            if self.study.paper["id"] == paper["id"] or self.study.proc:
                if not self.study.proc and not self.study.load():
                    self.study.start()
                self.study.lift()
                return
            self.study.destroy()
        self.study = StudyWindow(self, paper)

    def close(self):
        if self.study and self.study.winfo_exists() and self.study.proc:
            if not messagebox.askyesno("退出文献书房", "取消正在生成的论文导读并退出？", parent=self):
                return
            self.study.stop()
        t = self.translation
        if t and t.winfo_exists() and t.proc:
            if not messagebox.askyesno("退出文献书房", "取消正在运行的翻译并退出？", parent=self):
                return
            t.stop()
            t.cleanup()
        self.destroy()
        self.library.db.close()


if __name__ == "__main__":
    App().mainloop()
