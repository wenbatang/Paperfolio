"""Commands shared by the paper list's context menu and selection inspector."""

import sqlite3
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk


class PaperActions:
    def __init__(self, app):
        self.app = app
        self.popup = None
        self.press = None
        self.dragging = False
        self.hover = None

    def press_row(self, event, row):
        """Delay collapsing an existing group until we can distinguish a click from a drag."""
        self.end_drag()
        table = self.app.table
        ids = self.app.selection()
        pid = int(row)
        selected = pid in ids
        multi = self.app.multi.get()
        defer = selected and (multi or len(ids) > 1)
        if multi and not selected:
            table.selection_add(row)
            ids = self.app.selection()
        if multi or defer:
            table.focus_set()
            table.focus(row)
        self.press = (event.x_root, event.y_root, row, ids if selected or multi else (pid,), defer)
        if multi or defer:
            return "break"

    def drop_target(self, x, y):
        box = self.app.collections
        bx, by = x - box.winfo_rootx(), y - box.winfo_rooty()
        if self.app.groups and 0 <= bx < box.winfo_width() and 0 <= by < box.winfo_height():
            index = box.nearest(by)
            bounds = box.bbox(index)
            if bounds and bounds[1] <= by <= bounds[1] + bounds[3] + 1:
                group = self.app.groups[index]
                return group["id"], group["name"], index
        btn = self.app.nav_buttons["unfiled"]
        if 0 <= x - btn.winfo_rootx() < btn.winfo_width() and 0 <= y - btn.winfo_rooty() < btn.winfo_height():
            return None, "未分类", None
        return None

    def hover_color(self, target, active):
        if target is None:
            return
        index = target[2]
        if index is None:
            btn = self.app.nav_buttons["unfiled"]
            bg = self.app.nav_active if self.app.view == "unfiled" else self.app.side.cget("bg")
            btn.configure(bg=self.app.palette.accent if active else bg)
        else:
            box = self.app.collections
            bg = self.app.palette.accent if active else box.cget("bg")
            box.itemconfigure(index, background=bg, selectbackground=bg if active else box.cget("selectbackground"))

    def drag_motion(self, event):
        if not self.press:
            return
        x, y, _, ids, defer = self.press
        if not self.dragging:
            if event.x_root >= self.app.table.winfo_rootx() or max(abs(x-event.x_root), abs(y-event.y_root)) < 6:
                return "break" if defer or self.app.multi.get() else None
            self.dragging = True
            self.app.table.configure(cursor="hand2")
        target = self.drop_target(event.x_root, event.y_root)
        if self.hover != target:
            self.hover_color(self.hover, False)
            self.hover_color(target, True)
            self.hover = target
        self.app.status.set(f"松开以将 {len(ids)} 篇文献移入「{target[1]}」" if target else
                            f"将 {len(ids)} 篇文献拖到左侧分类，或松开取消")
        return "break"

    def release_row(self, event):
        if not self.press:
            return
        _, _, row, ids, defer = self.press
        dragged = self.dragging
        target = self.drop_target(event.x_root, event.y_root) if dragged else None
        self.end_drag()
        if dragged:
            if target:
                self.app.table.selection_set([str(pid) for pid in ids])
                self.apply(ids, "collection", target[0], f"移入「{target[1]}」")
            else:
                self.app.status.set("已取消拖动")
            return "break"
        if defer:
            if self.app.multi.get():
                self.app.table.selection_remove(row)
            else:
                self.app.table.selection_set(row)
            return "break"

    def end_drag(self):
        if self.dragging:
            self.hover_color(self.hover, False)
            self.app.table.configure(cursor="")
        self.press = self.hover = None
        self.dragging = False

    def apply(self, ids, field, value, label, *, new_collection=None):
        try:
            changed = self.app.library.change_papers(ids, field, value, label, new_collection=new_collection)
        except (ValueError, sqlite3.Error) as exc:
            messagebox.showerror("操作未完成", str(exc), parent=self.app)
            self.app.refresh(ids)
            return
        if new_collection:
            self.app.reload_collections()
        self.app.refresh(ids)
        if changed:
            self.app.status.set(f"{label} · 已更改 {changed} 篇文献，可按 Ctrl+Z 撤销")
        else:
            self.app.status.set(f"所选的 {len(ids)} 篇文献已处于目标状态")

    def flag(self, ids, field, value):
        if field == "favorite":
            label = "加上星标" if value else "取消星标"
        else:
            label = "移入回收站" if value else "恢复文献"
        self.apply(ids, field, value, label)

    def new_collection(self, ids):
        name = simpledialog.askstring("新建分类并移入", f"为所选 {len(ids)} 篇文献指定分类名称",
                                      parent=self.app)
        if name and name.strip():
            name = name.strip()
            self.apply(ids, "collection", None, f"移入「{name}」", new_collection=name)

    def collection_menu(self, parent, ids):
        menu = tk.Menu(parent, tearoff=False)
        for group in self.app.groups:
            cid, name = group["id"], group["name"]
            menu.add_command(label=name, command=lambda c=cid, n=name: self.apply(
                ids, "collection", c, f"移入「{n}」"))
        if self.app.groups:
            menu.add_separator()
        menu.add_command(label="新建分类并移入…", command=lambda: self.new_collection(ids))
        menu.add_command(label="移回未分类", command=lambda: self.apply(ids, "collection", None, "移回未分类"))
        return menu

    def context(self, event):
        table = self.app.table
        row = table.identify_row(event.y)
        if not row or table.identify_region(event.x, event.y) not in ("cell", "tree"):
            return "break"
        if row not in table.selection():
            table.selection_set(row)
        table.focus(row)
        table.focus_set()
        self.app.sync_selection()
        self.show_menu(event.x_root, event.y_root)
        return "break"

    def keyboard_menu(self, _):
        table = self.app.table
        ids = table.selection()
        if ids:
            row = table.focus() if table.focus() in ids else ids[0]
            table.see(row)
            box = table.bbox(row)
            if box:
                self.show_menu(table.winfo_rootx() + box[0] + 18, table.winfo_rooty() + box[1] + box[3])
        return "break"

    def show_menu(self, x, y):
        ids = self.app.selection()
        if not ids:
            return
        if self.popup:
            self.popup.destroy()
        self.popup = menu = tk.Menu(self.app, tearoff=False)
        if len(ids) == 1:
            menu.add_command(label="打开文献", command=lambda: self.app.workspace.open_pdf(self.app.rows[ids[0]]))
        menu.add_cascade(label="移入分类", menu=self.collection_menu(menu, ids))
        stars = sum(self.app.rows[i]["favorite"] for i in ids)
        if stars < len(ids):
            menu.add_command(label="加上星标", command=lambda: self.flag(ids, "favorite", 1))
        if stars:
            menu.add_command(label="取消星标", command=lambda: self.flag(ids, "favorite", 0))
        menu.add_command(label="导出所选 BibTeX…", command=lambda: self.app.export_citation(ids))
        menu.add_separator()
        restore = self.app.view == "trash"
        menu.add_command(label="恢复文献" if restore else "移入回收站",
                         command=lambda: self.flag(ids, "trashed", int(not restore)))
        menu.tk_popup(x, y)

    def trash_shortcut(self):
        ids = self.app.selection()
        if ids and self.app.view != "trash":
            self.flag(ids, "trashed", 1)
        return "break"

    def draw(self, panel, ids):
        app = self.app
        ttk.Label(panel, text=f"已选 {len(ids)} 篇文献", style="Section.TLabel").pack(anchor="w")
        tip = "点击文献可加入或移出选区。" if app.multi.get() else "Ctrl 点选多篇，Shift 连选一段。"
        ttk.Label(panel, text=tip + "也可拖到左侧分类。", wraplength=260,
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 8))
        selection = ttk.Frame(panel)
        selection.pack(fill="x")
        ttk.Button(selection, text="全选当前结果", command=app.select_all).pack(side="left")
        ttk.Button(selection, text="清空选择", command=app.deselect_all).pack(side="left", padx=5)
        if not ids:
            return
        ttk.Separator(panel).pack(fill="x", pady=12)
        move = ttk.Menubutton(panel, text="移入分类", image=app.icons.get("tabs"),
                              compound="left", direction="below")
        move.configure(menu=self.collection_menu(move, ids))
        move.pack(fill="x")
        stars = sum(app.rows[i]["favorite"] for i in ids)
        flags = ttk.Frame(panel)
        flags.pack(fill="x", pady=6)
        for label, value, enabled in (("加上星标", 1, stars < len(ids)), ("取消星标", 0, stars > 0)):
            ttk.Button(flags, text=label, state="normal" if enabled else "disabled",
                       command=lambda v=value: self.flag(ids, "favorite", v)).pack(
                side="left", fill="x", expand=True)
        ttk.Button(panel, text="导出所选 BibTeX…", command=lambda: app.export_citation(ids)).pack(fill="x")
        restore = app.view == "trash"
        ttk.Button(panel, text="恢复所选文献" if restore else "移入回收站",
                   command=lambda: self.flag(ids, "trashed", int(not restore))).pack(fill="x", pady=6)
