import json
from importlib.util import find_spec
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from library import timestamp
from cloud_translate import KEYS, SERVICES
from translate import EVENT_PREFIX, LANGUAGES, installed_models, page_numbers, resolve_model


class TranslationWindow(tk.Toplevel):
    def __init__(self, app, paper, current=None):
        super().__init__(app)
        self.app, self.paper = app, paper
        self.original = app.library.original_record(paper["id"])
        self.proc = self.folder = None
        self.cancelled = False
        self.events = queue.Queue()
        self.model_results = queue.Queue()
        self.detecting = False
        self.models = []
        self.model_error = ""
        self.phase = self.detail = ""
        self.title("翻译原文 · " + paper["title"])
        self.geometry("680x650")
        self.minsize(550, 580)
        wrap = ttk.Frame(self, padding=22)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="翻译原文", style="Title.TLabel").pack(anchor="w")
        ttk.Label(wrap, text=paper["title"], wraplength=590).pack(anchor="w", pady=(2, 12))
        self.form = ttk.Frame(wrap)
        self.form.pack(fill="x")
        self.form.columnconfigure(1, weight=1)
        layout_mode, paragraph_mode = "PDF2Zh · 保留排版", "段落对照 · 重排译文"
        self.mode = tk.StringVar(value=layout_mode if find_spec("pdf2zh_next") else paragraph_mode)
        saved = app.library.preference("provider", "ollama")
        self.provider = tk.StringVar(value=SERVICES.get(saved, SERVICES["ollama"]))
        self.credentials = {key: tk.StringVar(self, os.environ.get(env, "")) for key, env in KEYS.items()}
        self.region = tk.StringVar(self, os.environ.get("AZURE_TRANSLATOR_REGION", ""))
        self.fields = {}
        self.model = tk.StringVar()
        self.config = tk.StringVar()
        self.src, self.dst = tk.StringVar(value="en"), tk.StringVar(value="zh-CN")
        self.pages = tk.StringVar(value=str(current) if current else "")

        def row(label, widget, index):
            caption = ttk.Label(self.form, text=label)
            caption.grid(row=index, column=0, sticky="w", padx=(0, 15))
            widget.grid(row=index, column=1, sticky="ew", pady=3)
            self.fields[label] = (caption, widget)
            return widget

        def combo(var, values):
            return ttk.Combobox(self.form, textvariable=var, values=values, state="readonly")

        self.mode_box = row("翻译方式", combo(self.mode, [layout_mode, paragraph_mode]), 0)
        self.provider_box = row(
            "翻译服务", combo(self.provider, list(SERVICES.values())), 1
        )
        models_row = ttk.Frame(self.form)
        self.model_entry = ttk.Combobox(models_row, textvariable=self.model, state="readonly")
        self.model_entry.pack(side="left", fill="x", expand=True)
        self.refresh_models = ttk.Button(models_row, text="重新检测", command=self.detect_models)
        self.refresh_models.pack(side="right")
        row("本机模型", models_row, 2)
        config_box = ttk.Frame(self.form)
        self.config_entry = ttk.Entry(config_box, textvariable=self.config)
        self.config_entry.pack(side="left", expand=True, fill="x")
        self.browse = ttk.Button(config_box, text="选择 TOML", command=self.choose_config)
        self.browse.pack(side="right")
        row("配置文件", config_box, 3)
        row("原文语言", combo(self.src, list(LANGUAGES)), 4)
        row("译文语言", combo(self.dst, list(LANGUAGES)), 5)
        page_box = ttk.Frame(self.form)
        ttk.Entry(page_box, textvariable=self.pages).pack(side="left", fill="x", expand=True)
        ttk.Button(page_box, text="填入正文页", command=self.select_body).pack(side="right")
        row(f"页码（共 {self.original['pages']} 页）", page_box, 6)
        self.key_entry = row("API 密钥", ttk.Entry(self.form, show="●"), 7)
        row("Azure 资源区域", ttk.Entry(self.form, textvariable=self.region), 8)
        self.hint = ttk.Label(wrap, wraplength=600, style="Muted.TLabel")
        self.hint.pack(anchor="w", pady=(4, 10))
        self.mode_box.bind("<<ComboboxSelected>>", self.configure_fields)
        self.provider_box.bind("<<ComboboxSelected>>", self.provider_changed)
        self.state_text = tk.StringVar(value="就绪")
        ttk.Label(wrap, textvariable=self.state_text, wraplength=600, style="Section.TLabel").pack(
            anchor="w"
        )
        self.activity = tk.StringVar()
        ttk.Label(wrap, textvariable=self.activity, style="Muted.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(wrap, mode="indeterminate")
        self.progress.pack(fill="x", pady=6)
        self.log = tk.Text(
            wrap,
            height=6,
            wrap="word",
            bg="#eef2ef",
            fg="#354c45",
            font=("Consolas", 9),
            relief="flat",
            padx=8,
            pady=6,
            state="disabled",
        )
        self.log.pack(fill="both", expand=True)
        buttons = ttk.Frame(wrap)
        buttons.pack(fill="x", pady=(12, 0))
        self.close_btn = ttk.Button(buttons, text="关闭", command=self.close)
        self.close_btn.pack(side="left")
        self.run_btn = ttk.Button(buttons, text="开始翻译", style="Accent.TButton", command=self.start)
        self.run_btn.pack(side="right")
        self.read_btn = ttk.Button(buttons, text="阅读双语版", command=self.read_result)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.provider_changed()

    def service_id(self):
        return next(key for key, label in SERVICES.items() if self.provider.get() == label)

    def provider_changed(self, _=None):
        self.configure_fields()
        if self.service_id() == "ollama" and not self.models and not self.model_error:
            self.detect_models()

    def detect_models(self):
        if self.detecting or self.proc:
            return
        self.detecting = True
        self.model_error = ""
        self.configure_fields()

        def read():
            try:
                self.model_results.put((installed_models(), ""))
            except (ValueError, OSError, KeyError) as exc:
                self.model_results.put(([], str(exc)))

        threading.Thread(target=read, daemon=True).start()
        self.after(80, self.finish_detection)

    def finish_detection(self):
        try:
            names, self.model_error = self.model_results.get_nowait()
        except queue.Empty:
            self.after(100, self.finish_detection)
            return
        self.detecting, self.models = False, names
        old = self.model.get()
        self.model_entry.configure(values=names)
        self.model.set(resolve_model(old if old in names else "", names) if names else "")
        if not self.proc:
            self.configure_fields()

    def configure_fields(self, _=None):
        layout = self.mode.get().startswith("PDF2Zh")
        available = list(SERVICES.values()) if layout else [SERVICES[k] for k in ("ollama", "microsoft", "google")]
        if self.provider.get() not in available:
            self.provider.set(SERVICES["ollama"])
            if not self.detecting and not self.models and not self.model_error:
                self.detect_models()
        self.provider_box.configure(values=available, state="readonly")
        provider = self.service_id()
        local = provider == "ollama"
        for label, visible in (("本机模型", local), ("配置文件", provider == "config"),
                               ("API 密钥", provider in KEYS), ("Azure 资源区域", provider == "microsoft")):
            for widget in self.fields[label]:
                widget.grid() if visible else widget.grid_remove()
        if provider in KEYS:
            self.key_entry.configure(textvariable=self.credentials[provider])
        self.model_entry.configure(
            state="readonly" if local and self.models and not self.detecting else "disabled"
        )
        self.refresh_models.configure(state="normal" if local and not self.detecting else "disabled")
        for widget in (self.config_entry, self.browse):
            widget.configure(state="disabled" if local else "normal")
        service = "可从下拉列表切换本机模型。" if local else "文档文本将交给 TOML 中配置的翻译服务。"
        if provider in KEYS:
            service = f"所选页面的文字会发送给 {SERVICES[provider]}，用量计入你的云账户。"
            if provider == "microsoft":
                service += "区域按 Azure 资源填写，全球单服务资源可留空。"
        if local and self.detecting:
            service = "正在检测本机 Ollama 模型…"
        elif local and self.model_error:
            service = self.model_error + "。可点「重新检测」。"
        missing_layout = layout and not find_spec("pdf2zh_next")
        if missing_layout:
            service = "请在程序文件夹双击 install-layout.cmd 安装排版引擎，再重新打开翻译窗口。"
        self.run_btn.configure(
            state="disabled" if missing_layout or self.proc or (local and (not self.models or self.detecting)) else "normal"
        )
        self.hint.configure(text="页码留空译全文，也可输入 1,3-5。" + service)

    def choose_config(self):
        name = filedialog.askopenfilename(parent=self, filetypes=[("PDF2Zh 配置", "*.toml")])
        if name:
            self.config.set(name)

    def select_body(self):
        import pymupdf as pdf
        from study import body_end

        if not self.app.library.has_file(self.original):
            self.state_text.set("找不到原文 PDF，请重新导入原文。")
            return
        with pdf.open(self.app.library.root / self.original["path"]) as doc:
            end = body_end(doc)
            self.pages.set(f"1-{end}" if end < len(doc) else "")
            self.state_text.set(
                f"选中第 1–{end} 页，含参考文献起始页"
                if end < len(doc)
                else "已选全文，未识别到可单独省略的末尾参考文献页"
            )

    def start(self):
        if self.proc:
            return
        if not self.app.library.has_file(self.original):
            self.state_text.set("找不到原文 PDF，请重新导入原文。")
            return
        study = getattr(self.app, "study", None)
        provider = self.service_id()
        if provider == "ollama" and study and study.winfo_exists() and study.proc:
            self.state_text.set("导读正在使用模型，请在导读结束后开始翻译")
            return
        config = provider == "config"
        if provider == "ollama" and (self.detecting or not self.models):
            return
        try:
            spec = self.pages.get().strip()
            page_numbers(spec, self.original["pages"])
            if self.src.get() == self.dst.get():
                raise ValueError("请选择不同的原文和译文语言")
            if config and not Path(self.config.get()).is_file():
                raise ValueError("请选择有效的 PDF2Zh TOML 配置文件")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "COLUMNS": "130"}
            if provider in KEYS:
                secret = self.credentials[provider].get().strip()
                if not secret:
                    raise ValueError(f"请填写 {SERVICES[provider]} 的 API 密钥")
                env[KEYS[provider]] = secret
                if provider == "microsoft":
                    env["AZURE_TRANSLATOR_REGION"] = self.region.get().strip()
            mode = "layout" if self.mode.get().startswith("PDF2Zh") else "paragraph"
            self.folder = Path(tempfile.mkdtemp(prefix="paperfolio-", dir=self.app.library.root))
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            argv = [
                str(python),
                "-u",
                str(Path(__file__).with_name("translate.py")),
                str(self.app.library.root / self.original["path"]),
                str(self.folder),
                "--mode",
                mode,
                "--source",
                self.src.get(),
                "--target",
                self.dst.get(),
                "--pages",
                spec,
                "--model",
                self.model.get().strip(),
                "--provider", provider,
            ]
            if config:
                argv += ["--config", self.config.get()]
            elif mode == "paragraph":
                argv += ["--cache", str(self.app.library.root / "paragraph-cache.sqlite3")]
            self.description = f"{self.dst.get()} · {spec or '全文'} · {'排版' if mode == 'layout' else '段落'} · {timestamp()}"
            self.app.library.save_preferences({"provider": provider})
            self.proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (ValueError, OSError) as e:
            self.cleanup()
            messagebox.showerror("无法开始翻译", str(e), parent=self)
            return
        self.cancelled = False
        self.started = self.last_feedback = time.monotonic()
        self.phase = "正在启动翻译"
        self.detail = ""
        self.last_logged = ""
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.read_btn.pack_forget()
        self.run_btn.configure(state="disabled")
        for widget in self.form.winfo_children():
            for child in [widget, *widget.winfo_children()]:
                if isinstance(child, (ttk.Entry, ttk.Button)):
                    child.state(["disabled"])
        self.close_btn.configure(text="取消任务")
        self.state_text.set("翻译中，可以继续在主窗口阅读")
        self.progress.start(14)
        threading.Thread(target=self.read_output, args=(self.proc,), daemon=True).start()
        self.after(150, self.poll)

    def read_output(self, proc):
        with proc.stdout:
            for line in proc.stdout:
                self.events.put(line)
        self.events.put(proc.wait())

    def poll(self):
        lines = []
        code = None
        while not self.events.empty():
            item = self.events.get()
            if isinstance(item, int):
                code = item
                break
            if not item.startswith(EVENT_PREFIX):
                lines.append(item)
                continue
            try:
                event = json.loads(item[len(EVENT_PREFIX) :])
            except ValueError:
                lines.append(item)
                continue
            stage = event.get("stage")
            if stage:
                self.phase = stage
                if stage != self.last_logged:
                    lines.append(stage + "\n")
                    self.last_logged = stage
            self.detail = event.get("detail") or ""
            self.last_feedback = time.monotonic()
            if event.get("percent") is not None:
                if str(self.progress.cget("mode")) != "determinate":
                    self.progress.stop()
                self.progress.configure(mode="determinate", value=event["percent"])
        now = time.monotonic()
        elapsed = int(now - self.started)
        silence = int(now - self.last_feedback)
        self.state_text.set(self.phase)
        info = self.detail or (f"距上次进度更新 {silence} 秒" if silence >= 12 else "")
        self.activity.set(f"已用 {elapsed // 60:02d}:{elapsed % 60:02d}  {info}")
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "".join(lines[-180:]))
            if int(self.log.index("end-1c").split(".")[0]) > 300:
                self.log.delete("1.0", "end-240lines")
            self.log.see("end")
            self.log.configure(state="disabled")
        if code is None:
            self.after(180, self.poll)
            return
        self.proc = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        try:
            if self.cancelled:
                self.state_text.set("翻译已取消")
            elif code:
                self.state_text.set("翻译失败，可查看日志并重试")
            else:
                self.result_file = self.app.library.publish(self.paper["id"], self.folder, self.description)
                self.app.translated(self.paper["id"])
                self.progress.configure(value=100)
                self.read_btn.pack(side="right", padx=4)
                self.state_text.set("已保存译文和双语 PDF，可在论文附件中打开")
        except Exception as e:
            self.state_text.set(f"无法归档译文：{e}")
        finally:
            self.cleanup()
        self.close_btn.configure(text="关闭")
        self.run_btn.configure(state="normal", text="再次翻译")
        for widget in self.form.winfo_children():
            for child in [widget, *widget.winfo_children()]:
                if isinstance(child, (ttk.Entry, ttk.Button)):
                    child.state(["!disabled"])
        self.configure_fields()

    def read_result(self):
        self.app.workspace.open_pdf(self.paper, self.result_file, 1)

    def cleanup(self):
        if self.folder:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.folder = None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.cancelled = True
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
            if messagebox.askyesno("取消翻译", "取消当前翻译任务？", parent=self):
                self.stop()
            return
        self.destroy()
