from bisect import bisect_right
import json
import math
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf as pdf
from PIL import Image, ImageChops, ImageDraw, ImageTk

from annotations import COLORS, PageText


class NoteDialog(simpledialog.Dialog):
    def __init__(self, parent, page, initial=""):
        self.initial = initial
        super().__init__(parent, f"第 {page} 页 · 阅读笔记")

    def body(self, master):
        self.editor = tk.Text(master, width=58, height=10, wrap="word", padx=10, pady=8, undo=True)
        self.editor.pack()
        self.editor.insert("1.0", self.initial)
        self.editor.edit_reset()
        for sequence in ("<Control-y>", "<Control-Shift-Z>"):
            self.editor.bind(sequence, lambda _: self.editor.event_generate("<<Redo>>") or "break")
        return self.editor

    def apply(self):
        self.result = self.editor.get("1.0", "end-1c").strip()


class Reader(ttk.Frame):
    def __init__(self, parent, app, paper, fid, page, files):
        super().__init__(parent)
        self.app, self.library, self.paper = app, app.library, paper
        icon = app.icons.get
        self.doc = self.resize_timer = None
        self.paint_timer = None
        self.tops = []
        self.photos = {}
        self.page = 1
        self.pending_page = None
        self.start = self.selection_page = None
        self.last_search = None
        self.files = files
        self.pos = tk.StringVar()
        self.find_text = tk.StringVar()
        self.zoom = 1.0
        self.selected = ""
        self.text_page = None
        self.selected_rects = []
        self.mark_window = None
        self.mark_menu = tk.Menu(self, tearoff=False)
        top = ttk.Frame(self, padding=(14, 9))
        top.pack(fill="x")
        ttk.Button(top, text="导航", image=icon("outline"), compound="left",
                   command=self.toggle_navigation).pack(side="left", padx=(0,8))
        self.version = ttk.Combobox(
            top, values=[f["label"] for f in self.files], state="readonly", width=21,
            postcommand=self.refresh_versions,
        )
        self.version.pack(side="left")
        self.version.bind("<<ComboboxSelected>>", self.choose_version)
        ttk.Button(top, text="记笔记", image=icon("note"), compound="left", command=self.note).pack(side="right")
        ttk.Button(top, text="高亮列表", image=icon("marks"), compound="left", command=self.show_marks).pack(side="right", padx=4)
        self.pen_color = tk.StringVar(value="")
        self.pen_label = tk.StringVar(value="荧光笔")
        pen = ttk.Menubutton(top, textvariable=self.pen_label, image=icon("pen"), compound="left")
        pen.pack(side="right")
        pens = tk.Menu(pen, tearoff=False)
        pen.configure(menu=pens)
        pens.add_radiobutton(label="普通选文", variable=self.pen_color, value="",
                             command=lambda: self.pen_label.set("荧光笔"))
        for name, color in COLORS.items():
            pens.add_radiobutton(label=name + "色连续高亮", background=color, variable=self.pen_color,
                                 value=color, command=lambda n=name: self.pen_label.set(n + "色荧光笔"))
        ttk.Button(top, text="翻译原文", image=icon("language"), compound="left",
                   command=self.translate_original).pack(side="right", padx=6)
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        self.nav = ttk.Frame(self.body, padding=8)
        self.nav_tree = ttk.Treeview(self.nav, show="tree", selectmode="browse")
        self.nav_tree.column("#0",width=188,stretch=False)
        ttk.Button(self.nav, text="添加 / 移除本页书签", image=icon("marks"), compound="left",
                   command=self.toggle_bookmark).pack(side="bottom",fill="x",pady=(6,0))
        scroll = ttk.Scrollbar(self.nav, command=self.nav_tree.yview)
        scroll.pack(side="right",fill="y")
        self.nav_tree.configure(yscrollcommand=scroll.set)
        self.nav_tree.pack(fill="both",expand=True)
        self.nav_tree.bind("<<TreeviewSelect>>",self.jump_navigation)
        area = ttk.Frame(self.body)
        self.page_area = area
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg="#dce3df", highlightthickness=0, cursor="xterm")
        sy = ttk.Scrollbar(area, command=self.canvas.yview)
        sx = ttk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        self.scrollbar = sy
        self.canvas.configure(yscrollcommand=self.scrolled, xscrollcommand=sx.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", lambda e: self.scroll_pixels(-72))
        self.canvas.bind("<Button-5>", lambda e: self.scroll_pixels(72))
        self.canvas.bind("<Up>", lambda e: self.scroll_pixels(-48))
        self.canvas.bind("<Down>", lambda e: self.scroll_pixels(48))
        self.canvas.bind("<ButtonPress-1>", self.start_selection)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end_selection)
        self.canvas.bind("<Button-3>", self.mark_context)
        self.canvas.bind("<Control-c>", self.copy)
        self.canvas.bind("<Escape>", lambda _: self.clear_selection())
        self.selection_tools = ttk.Frame(self.canvas, padding=3, relief="solid", borderwidth=1)
        ttk.Button(self.selection_tools, text="复制", width=5, command=self.copy).pack(side="left")
        ttk.Button(self.selection_tools, text="记笔记", width=7, command=self.note).pack(side="left")
        for name, color in COLORS.items():
            tk.Button(self.selection_tools, text=name, bg=color, fg="#202923", width=2,
                      command=lambda c=color: self.save_mark(c)).pack(side="left", padx=1)
        bar = ttk.Frame(self, padding=(12, 6))
        bar.pack(side="bottom", before=self.body, fill="x")
        ttk.Button(bar, text="上一页", command=lambda: self.go(self.page - 1)).pack(side="left")
        field = ttk.Entry(bar, textvariable=self.pos, width=5, justify="center")
        self.page_field = field
        field.pack(side="left", padx=(4, 0))
        field.bind("<Return>", lambda e: self.go(self.pos.get()))
        self.total = ttk.Label(bar)
        self.total.pack(side="left", padx=4)
        ttk.Button(bar, text="下一页", command=lambda: self.go(self.page + 1)).pack(side="left")
        for label, factor in (("−", 0.8), ("+", 1.25), ("适宽", 0)):
            ttk.Button(bar, text=label, width=4, command=lambda f=factor: self.scale(f)).pack(
                side="left", padx=2
            )
        ttk.Button(bar, text="查找下一页", command=self.find).pack(side="right")
        field = ttk.Entry(bar, width=16, textvariable=self.find_text)
        field.pack(side="right", padx=6)
        field.bind("<Return>", lambda e: self.find())
        self.search = field
        self.caption = ttk.Label(self, text="拖选文字后可复制或记笔记", padding=(13, 2))
        self.caption.pack(side="bottom", before=bar, anchor="w")
        self.version.current(next(i for i, f in enumerate(self.files) if f["id"] == fid))
        self.bind("<Unmap>", self.release_images)
        self.bind("<Map>", self.resume_paint)
        self.open_version(page)

    def release_images(self, event):
        if event.widget is self:
            for number in self.photos:
                self.canvas.delete(f"page-{number}")
            self.photos.clear()

    def resume_paint(self, event):
        if event.widget is self and self.tops and self.paint_timer is None:
            self.paint_timer = self.after_idle(self.paint_visible)

    def choose_version(self, _):
        index = self.version.current()
        if index < 0:
            return
        fid = self.files[index]["id"]
        self.refresh_versions()
        self.app.workspace.open_pdf(self.paper, fid)

    def focus_page(self):
        self.page_field.focus_set()
        self.page_field.select_range(0,"end")

    def toggle_navigation(self):
        if self.nav.winfo_manager():
            self.nav.pack_forget()
        else:
            self.nav.pack(side="left", before=self.page_area, fill="y")
            self.refresh_navigation()

    def refresh_navigation(self):
        tree = self.nav_tree
        tree.delete(*tree.get_children())
        favorites = tree.insert("", "end", text="我的书签", open=True)
        for row in self.library.db.execute("SELECT page FROM bookmarks WHERE file=? ORDER BY page",(self.file["id"],)):
            tree.insert(favorites,"end",text=f"第 {row[0]} 页",values=(row[0],))
        root = tree.insert("", "end", text="论文目录", open=True)
        parents = [root]
        for level, title, page in self.doc.get_toc():
            level = min(max(1,level),len(parents))
            parents = parents[:level]
            node = tree.insert(parents[-1],"end",text=title,values=(page,),open=level==1)
            parents.append(node)
        if not tree.get_children(root):
            tree.insert(root,"end",text="此 PDF 没有内置目录")

    def jump_navigation(self, _):
        selection = self.nav_tree.selection()
        if selection:
            values = self.nav_tree.item(selection[0],"values")
            if values and 1 <= int(values[0]) <= len(self.doc):
                self.go(values[0])

    def toggle_bookmark(self):
        if self.tops:
            self.sync_page()
        row = self.library.db.execute("SELECT * FROM bookmarks WHERE file=? AND page=?",
                                      (self.file["id"],self.page)).fetchone()
        label = "移除书签" if row else "添加书签"
        self.library.record(label, "bookmarks", row, None if row else dict(file=self.file["id"],page=self.page))
        self.refresh_navigation()
        self.caption.configure(text=f"{label} · 第 {self.page} 页")

    def refresh_versions(self):
        self.files = self.library.files(self.paper["id"])
        self.version.configure(values=[f["label"] for f in self.files])
        index = next((i for i, f in enumerate(self.files) if f["id"] == self.file["id"]), None)
        if index is None:
            self.version.set("已打开的文件已移除")
        else:
            self.version.current(index)

    def open_version(self, page=None):
        if self.mark_window and self.mark_window.winfo_exists():
            self.mark_window.destroy()
        self.text_page = None
        if self.tops:
            self.sync_page()
        file = self.files[self.version.current()]
        try:
            new = pdf.open(self.library.root / file["path"])
        except Exception as e:
            messagebox.showerror("无法打开附件", str(e), parent=self)
            self.destroy()
            return
        if self.doc is not None:
            self.doc.close()
        self.doc, self.file = new, file
        self.sizes = [(p.rect.width, p.rect.height) for p in self.doc]
        self.last_search = None
        self.tops = []
        self.page = file["position"] or 1
        self.pending_page = page or self.page
        self.total.configure(text=f"/ {len(new)}")
        if self.canvas.winfo_width() > 1:
            self.layout()
        self.canvas.xview_moveto(0)
        self.canvas.focus_set()

    def go(self, number):
        try:
            number = max(1, min(int(number), len(self.doc)))
        except ValueError:
            self.pos.set(str(self.page))
            return
        if not self.tops or self.viewport_height != self.canvas.winfo_height():
            self.pending_page = number
            self.layout()
            return
        self.clear_selection()
        self.canvas.yview_moveto((self.tops[number - 1] - 14) / self.height)
        self.sync_page()
        self.pos.set(str(self.page))

    def page_at(self, y):
        return max(1, bisect_right(self.tops, y))

    def reading_y(self):
        # Tk can move the viewport to fit the old scrollregion while the window grows.
        if self.viewport_height != self.canvas.winfo_height():
            return self.view_y
        return self.canvas.canvasy(0)

    def sync_page(self):
        self.view_y = self.reading_y()
        number = self.page_at(self.view_y + 14)
        if number != self.page:
            self.page = number
            self.pos.set(str(number))
            with self.library.db:
                self.library.db.execute("UPDATE files SET position=? WHERE id=?", (number, self.file["id"]))

    def wheel(self, event):
        units = event.delta if self.tk.call("tk", "windowingsystem") == "aqua" else event.delta / 120
        return self.scroll_pixels(-72 * units)

    def scroll_pixels(self, pixels):
        if self.tops:
            self.canvas.yview_moveto((self.canvas.canvasy(0) + pixels) / self.height)
        return "break"

    def scrolled(self, first, last):
        self.scrollbar.set(first, last)
        if self.tops and self.paint_timer is None:
            self.paint_timer = self.after_idle(self.paint_visible)

    def scale(self, factor):
        self.zoom = min(3.0, max(0.4, self.zoom * factor)) if factor else 1.0
        self.layout()

    def resize(self, _):
        if self.resize_timer:
            self.after_cancel(self.resize_timer)
        self.resize_timer = self.after(100, self.layout)

    def layout(self):
        if self.resize_timer:
            self.after_cancel(self.resize_timer)
            self.resize_timer = None
        # Keep the same point on the page under the top margin during a resize or zoom.
        if self.canvas.winfo_width() <= 1 or self.doc is None:
            return
        number, self.pending_page = self.pending_page, None
        offset = 0
        if number is None:
            y = self.reading_y() + 14
            number = self.page_at(y)
            offset = (y - self.tops[number - 1]) / self.ratios[number - 1]
        number = max(1, min(number, len(self.sizes)))
        self.clear_selection()
        self.canvas.delete("all")
        self.photos.clear()
        self.tops, self.ratios, self.widths = [], [], []
        width = max(160, self.canvas.winfo_width() - 36)
        y = 14
        for w, h in self.sizes:
            ratio = min(width / w * self.zoom, 3.5, math.sqrt(9000000 / max(1, w * h)))
            self.tops.append(y)
            self.ratios.append(ratio)
            self.widths.append(math.ceil(w * ratio))
            y += math.ceil(h * ratio) + 14
        self.content_width = max(width, max(self.widths)) + 36
        # Leave room to align even a short final page with the top of the viewport.
        self.viewport_height = self.canvas.winfo_height()
        self.height = max(y, self.tops[-1] - 14 + self.viewport_height)
        self.canvas.configure(scrollregion=(0, 0, self.content_width, self.height))
        index = number - 1
        y = self.tops[index] - 14 + round(offset * self.ratios[index])
        self.canvas.yview_moveto(y / self.height)
        self.sync_page()
        self.pos.set(str(self.page))
        self.scrolled(*self.canvas.yview())

    def paint_visible(self):
        self.paint_timer = None
        if not self.tops or not self.winfo_ismapped():
            return
        self.sync_page()
        y = self.canvas.canvasy(0)
        first = self.page_at(y - 24)
        last = self.page_at(y + self.canvas.winfo_height() + 24)
        for number in list(self.photos):
            if not first <= number <= last:
                self.canvas.delete(f"page-{number}")
                del self.photos[number]
                if self.selection_page == number:
                    self.clear_selection()
        for number in range(first, last + 1):
            if number not in self.photos:
                self.draw_page(number)
        self.canvas.tag_raise("selection")
        self.position_tools()

    def origin(self, number):
        return (self.content_width - self.widths[number - 1]) // 2, self.tops[number - 1]

    def draw_page(self, number):
        page = self.doc[number - 1]
        ratio = self.ratios[number - 1]
        bitmap = page.get_pixmap(
            matrix=pdf.Matrix(ratio, ratio), colorspace=pdf.csRGB, alpha=False
        )
        marks = self.library.highlights(self.file["id"], number)
        if marks:
            image = bitmap.pil_image()
            overlay = Image.new("RGB", image.size, "white")
            draw = ImageDraw.Draw(overlay)
            transform = page.rotation_matrix * pdf.Matrix(ratio, ratio)
            for mark in marks:
                for box in json.loads(mark["rects"]):
                    draw.rectangle(tuple(pdf.Rect(box) * transform), fill=mark["color"])
            self.photos[number] = ImageTk.PhotoImage(ImageChops.multiply(image, overlay), master=self)
        else:
            self.photos[number] = tk.PhotoImage(master=self, data=bitmap.tobytes("ppm"), format="PPM")
        left, top = self.origin(number)
        tag = f"page-{number}"
        self.canvas.create_image(left, top, anchor="nw", image=self.photos[number], tags=tag)
        self.highlight(number)

    def highlight(self, number):
        if self.last_search:
            page = self.doc[number - 1]
            ratio = self.ratios[number - 1]
            left, top = self.origin(number)
            for hit in page.search_for(self.last_search):
                r = hit * page.rotation_matrix * pdf.Matrix(ratio, ratio)
                self.canvas.create_rectangle(
                    left + r.x0, top + r.y0, left + r.x1, top + r.y1,
                    fill="#fad56f",
                    stipple="gray50",
                    outline="#bb8b29",
                    tags=(f"page-{number}", "match"),
                )

    def find(self):
        term = self.find_text.get().strip()
        repeated = self.last_search == term
        self.last_search = term
        self.canvas.delete("match")
        for number in self.photos:
            self.highlight(number)
        if not term:
            return
        start = self.page if repeated else self.page - 1
        for offset in range(len(self.doc)):
            index = (start + offset) % len(self.doc)
            if self.doc[index].search_for(term):
                self.go(index + 1)
                self.caption.configure(text=f"第 {self.page} 页包含「{term}」")
                return
        self.caption.configure(text=f"全文未找到「{term}」")

    def point(self, event):
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def pdf_point(self, number, event):
        x, y = self.point(event)
        left, top = self.origin(number)
        scale = self.ratios[number - 1]
        return pdf.Point((x - left) / scale, (y - top) / scale) * self.doc[number - 1].derotation_matrix

    def start_selection(self, event):
        self.canvas.focus_set()
        self.clear_selection()
        if not self.tops:
            return
        number = self.page_at(self.point(event)[1])
        if not self.text_page or self.text_page[0] != number:
            self.text_page = number, PageText(self.doc[number - 1])
        text = self.text_page[1]
        if not text.lines:
            self.caption.configure(text="本页没有可选择的文字。扫描页需先做 OCR。")
            return
        self.start = text.nearest(self.pdf_point(number, event), require_hit=True)
        if self.start is not None:
            self.selection_page = number
            self.press_xy = event.x, event.y

    def clear_selection(self):
        self.start = self.selection_page = None
        self.selected = ""
        self.selected_rects = []
        self.selection_tools.place_forget()
        self.canvas.delete("selection")
        self.caption.configure(text="沿文字拖动即可复制、记笔记或高亮；右键高亮可改色或删除")

    def drag(self, event):
        if self.start is None:
            return
        self.canvas.delete("selection")
        self.selected, self.selected_rects = "", []
        if max(abs(event.x - self.press_xy[0]), abs(event.y - self.press_xy[1])) < 3:
            return
        n = self.selection_page
        text = self.text_page[1]
        end = text.nearest(self.pdf_point(n, event))
        self.selected, self.selected_rects = text.selection(self.start, end)
        left, top = self.origin(n)
        ratio = self.ratios[n - 1]
        transform = self.doc[n - 1].rotation_matrix * pdf.Matrix(ratio, ratio)
        for box in self.selected_rects:
            r = pdf.Rect(box) * transform
            self.canvas.create_rectangle(
                left+r.x0, top+r.y0, left+r.x1, top+r.y1, fill="#93bfae",
                stipple="gray25", outline="#35785b", tags="selection",
            )

    def end_selection(self, event):
        if self.start is None:
            return
        self.drag(event)
        self.start = None
        if self.selected:
            if self.pen_color.get():
                self.save_mark(self.pen_color.get())
                return
            self.position_tools()
            self.caption.configure(text="点颜色保存高亮，或按 Ctrl+C 复制选文")

    def position_tools(self):
        if self.start is not None or not self.selected:
            return
        box = self.canvas.bbox("selection")
        if not box:
            return
        top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        if box[3] < top or box[1] > top + height:
            self.selection_tools.place_forget()
            return
        tools = self.selection_tools
        x = max(0, min(box[0] - self.canvas.canvasx(0), self.canvas.winfo_width() - tools.winfo_reqwidth()))
        y = min(height - tools.winfo_reqheight(), box[3] - top + 4)
        tools.place(x=x, y=max(0, y))

    def copy(self, _=None):
        if self.selected:
            self.clipboard_clear()
            self.clipboard_append(self.selected)
            self.caption.configure(text="已复制选文")
            return "break"

    def save_mark(self, color):
        if not self.selected:
            return
        number = self.selection_page
        self.library.record("添加高亮", "highlights", None,
                            dict(file=self.file["id"], page=number, quote=self.selected, color=color,
                                 rects=json.dumps(self.selected_rects)))
        self.clear_selection()
        self.marks_changed(number)
        self.caption.configure(text=f"已保存第 {number} 页的高亮")

    def marks_changed(self, number):
        for reader in self.master.winfo_children():
            if not isinstance(reader, Reader) or reader.file["id"] != self.file["id"]:
                continue
            if number in reader.photos:
                reader.canvas.delete(f"page-{number}")
                reader.draw_page(number)
                reader.canvas.tag_raise("selection")
            if reader.mark_window and reader.mark_window.winfo_exists():
                reader.refresh_marks()

    def edit_mark(self, mark, color=None):
        if color is None and not messagebox.askyesno(
            "删除高亮", f"删除第 {mark['page']} 页的这处高亮？", parent=self
        ):
            return
        self.library.record("高亮改色" if color else "删除高亮", "highlights", mark,
                            dict(mark, color=color) if color else None)
        self.marks_changed(mark["page"])

    def mark_context(self, event):
        if not self.tops:
            return
        number = self.page_at(self.point(event)[1])
        point = self.pdf_point(number, event)
        for mark in reversed(self.library.highlights(self.file["id"], number)):
            if any(point in pdf.Rect(box) for box in json.loads(mark["rects"])):
                self.clear_selection()
                menu = self.mark_menu
                menu.delete(0, "end")
                for name, color in COLORS.items():
                    menu.add_command(label="改为" + name + "色", background=color,
                                     command=lambda c=color: self.edit_mark(mark, c))
                menu.add_separator()
                menu.add_command(label="摘录到笔记", command=lambda: self.write_note(number, mark["quote"]))
                menu.add_command(label="删除高亮", command=lambda: self.edit_mark(mark))
                menu.tk_popup(event.x_root, event.y_root)
                return

    def show_marks(self):
        if self.mark_window and self.mark_window.winfo_exists():
            self.mark_window.lift()
            return
        self.mark_window = window = tk.Toplevel(self)
        window.title("高亮列表 · " + self.file["label"])
        window.geometry("520x360")
        bar = ttk.Frame(window, padding=6)
        bar.pack(side="bottom", fill="x")
        self.mark_list = tk.Listbox(window, exportselection=False, activestyle="none")
        scroll = ttk.Scrollbar(window, command=self.mark_list.yview)
        scroll.pack(side="right", fill="y")
        self.mark_list.configure(yscrollcommand=scroll.set)
        self.mark_list.pack(fill="both", expand=True)
        def selected():
            indices = self.mark_list.curselection()
            return self.mark_rows[indices[0]] if indices else None

        def jump():
            mark = selected()
            if mark is None:
                return
            number = mark["page"]
            self.go(number)
            box = pdf.Rect(json.loads(mark["rects"])[0]) * self.doc[number - 1].rotation_matrix
            left, top = self.origin(number)
            ratio = self.ratios[number - 1]
            self.canvas.yview_moveto((top + max(-14, box.y0 * ratio - 40)) / self.height)
            self.canvas.xview_moveto(max(0, left + box.x0 * ratio - 40) / self.content_width)
            window.destroy()
            self.canvas.focus_set()

        def excerpt():
            if mark := selected():
                self.write_note(mark["page"], mark["quote"])

        def remove():
            if mark := selected():
                self.edit_mark(mark)

        self.mark_list.bind("<Double-1>", lambda _: jump())
        ttk.Button(bar, text="定位原文", command=jump).pack(side="left")
        ttk.Button(bar, text="摘录到笔记", command=excerpt).pack(side="left", padx=4)
        ttk.Button(bar, text="导出带高亮的 PDF", command=self.export_marks).pack(side="left")
        ttk.Button(bar, text="删除高亮", command=remove).pack(side="right")
        self.refresh_marks()

    def export_marks(self):
        target = filedialog.asksaveasfilename(
            parent=self.mark_window, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialdir=self.library.export_dir,
            initialfile=self.paper["title"].translate(str.maketrans({c: "_" for c in '<>:"/\\|?*'}))[:80] + "-高亮.pdf",
        )
        if target:
            try:
                self.library.export_highlights(self.file, target)
            except (RuntimeError, ValueError, OSError) as exc:
                messagebox.showerror("导出高亮失败", str(exc), parent=self.mark_window)
            else:
                self.caption.configure(text=f"已导出 {target}")

    def refresh_marks(self):
        self.mark_rows = self.library.highlights(self.file["id"])
        self.mark_list.delete(0, "end")
        for mark in self.mark_rows:
            quote = " ".join(mark["quote"].split())
            self.mark_list.insert("end", f"第 {mark['page']} 页    {quote}")
            self.mark_list.itemconfigure("end", background=mark["color"])
        if self.mark_rows:
            self.mark_list.selection_set(0)

    def note(self):
        number = self.selection_page if self.selected else self.page
        self.write_note(number, self.selected)

    def write_note(self, number, quote):
        body = NoteDialog(self.winfo_toplevel(), number, quote).result
        if body:
            self.library.save_note(self.file["id"], number, body)
            self.app.draw_detail()
            self.caption.configure(text=f"已保存第 {number} 页的笔记")

    def translate_original(self):
        self.app.translate(self.paper, self.page if self.file["label"] == "原文" else None)

    def destroy(self):
        if self.tops and self.doc is not None:
            self.sync_page()
        if self.paint_timer:
            self.after_cancel(self.paint_timer)
        if self.resize_timer:
            self.after_cancel(self.resize_timer)
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        super().destroy()
