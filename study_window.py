import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from translate import EVENT_PREFIX


class StudyWindow(tk.Toplevel):
    def __init__(self, app, paper):
        super().__init__(app)
        self.app, self.paper = app, paper
        self.original = app.library.original_record(paper["id"])
        self.proc = None
        self.events = queue.Queue()
        self.title("论文导读 · " + paper["title"])
        self.geometry("850x710")
        self.minsize(580, 430)
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="论文导读", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text=paper["title"], wraplength=690).pack(anchor="w", pady=(2, 12))
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(
            body,
            wrap="word",
            padx=18,
            pady=12,
            bd=0,
            bg="#ffffff",
            fg="#233c34",
            font=("Microsoft YaHei UI", 11),
            spacing3=5,
        )
        scroll = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("section", font=("Microsoft YaHei UI", 15, "bold"), spacing1=12, spacing3=8)
        self.text.tag_configure("link", foreground="#20644e", underline=True)
        self.text.tag_configure(
            "quote", foreground="#58675f", lmargin1=16, lmargin2=16, font=("Microsoft YaHei UI", 9)
        )
        bar = ttk.Frame(outer)
        bar.pack(side="bottom", before=body, fill="x", pady=(10, 0))
        self.state = tk.StringVar()
        self.show_quotes = tk.BooleanVar(value=False)
        self.quotes_btn = ttk.Checkbutton(bar, text="显示原文摘录", variable=self.show_quotes, command=self.load)
        self.cancel_btn = ttk.Button(bar, text="取消生成", command=self.stop)
        self.run_btn = ttk.Button(bar, text="生成导读", style="Accent.TButton", command=self.start)
        self.run_btn.pack(side="right")
        self.quotes_btn.pack(side="right", padx=6)
        ttk.Label(bar, textvariable=self.state, wraplength=330).pack(side="left", fill="x", expand=True)
        if not self.load():
            self.after_idle(self.start)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def load(self):
        row = self.app.library.db.execute(
            "SELECT * FROM guides WHERE paper=?", (self.paper["id"],)
        ).fetchone()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if row:
            for section, points in json.loads(row["body"]).items():
                self.text.insert("end", section + "\n", "section")
                if not points:
                    self.text.insert("end", "所选原文片段里缺少足够依据。\n")
                for point in points:
                    page = point["page"]
                    self.text.insert("end", point["point"] + "  ")
                    tag = f"page-{page}"
                    self.text.insert("end", f"原文第 {page} 页\n", ("link", tag))
                    self.text.tag_bind(tag, "<Button-1>", lambda e, n=page: self.open_page(n))
                    if self.show_quotes.get():
                        self.text.insert("end", point["quote"] + "\n\n", "quote")
            self.run_btn.configure(text="重新生成")
            self.state.set(f"{row['model']} · {row['created'].replace('T', ' ')}")
        else:
            self.text.insert("end", "生成的导读会显示在这里。点击要点旁的页码可核对原文。")
            self.state.set("准备连接本机 Ollama")
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)
        return row is not None

    def open_page(self, page):
        if self.original:
            self.app.workspace.open_pdf(self.paper, self.original["id"], page)

    def start(self):
        if self.proc:
            return
        if not self.app.library.has_file(self.original):
            self.state.set("找不到原文 PDF，请重新导入原文后再生成导读。")
            return
        tr = self.app.translation
        if tr and tr.winfo_exists() and tr.proc and tr.service_id() == "ollama":
            self.state.set("翻译正在使用模型，请在翻译结束后生成导读")
            return
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":
            python = python.with_name("python.exe")
        try:
            self.proc = subprocess.Popen(
                [
                    str(python),
                    "-u",
                    str(Path(__file__).with_name("study.py")),
                    str(self.app.library.root),
                    str(self.paper["id"]),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            messagebox.showerror("无法启动导读", str(exc), parent=self)
            return
        self.cancelled = False
        self.run_btn.configure(state="disabled")
        self.quotes_btn.configure(state="disabled")
        self.cancel_btn.pack(side="right", before=self.quotes_btn, padx=4)
        self.state.set("正在连接本机 Ollama…")
        self.last_line = ""
        threading.Thread(target=self.read_output, args=(self.proc,), daemon=True).start()
        self.after(150, self.poll)

    def read_output(self, proc):
        with proc.stdout:
            for line in proc.stdout:
                self.events.put(line.rstrip())
        self.events.put(proc.wait())

    def poll(self):
        while not self.events.empty():
            line = self.events.get()
            if isinstance(line, int):
                self.proc = None
                self.cancel_btn.pack_forget()
                self.run_btn.configure(state="normal")
                self.quotes_btn.configure(state="normal")
                if line == 0:
                    self.load()
                else:
                    self.state.set("生成已取消" if self.cancelled else self.last_line or "生成失败")
                return
            if line.startswith(EVENT_PREFIX):
                event = json.loads(line[len(EVENT_PREFIX) :])
                self.state.set(f"{event['stage']}  {event['detail']}")
            elif line:
                self.last_line = line
                self.state.set(line)
        self.after(150, self.poll)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.cancelled = True
            # The Windows virtual-environment launcher has a child interpreter.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                self.proc.terminate()

    def close(self):
        if self.proc:
            if not messagebox.askyesno("关闭导读", "取消本次生成并关闭窗口？", parent=self):
                return
            self.stop()
        self.destroy()
