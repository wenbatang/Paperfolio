"""PDF2Zh layout pipeline with native Ollama generation and progress events."""

import ast
import json
import os
import re
import sys
import threading

from babeldoc.assets.assets import warmup
from babeldoc.format.pdf.high_level import async_translate
from babeldoc.format.pdf.translation_config import TranslationConfig, WatermarkOutputMode
from babeldoc.translator.translator import BaseTranslator
from babeldoc.assets.assets import get_doclayout_onnx_model_path
from babeldoc.docvision.doclayout import OnnxModel
import onnxruntime

from translate import IncompleteGeneration, LANGUAGES, generate, report
from cloud_translate import KEYS, TOKEN, cloud_text


class CompactLayoutModel(OnnxModel):
    """Use the upstream detector and load its ONNX graph directly from disk."""

    def __init__(self, model_path):
        self.model_path = str(model_path)
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = min(12, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.enable_cpu_mem_arena = False
        self.model = onnxruntime.InferenceSession(
            self.model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        metadata = self.model.get_modelmeta().custom_metadata_map
        self._stride = ast.literal_eval(metadata["stride"])
        self._names = ast.literal_eval(metadata["names"])
        self.lock = threading.Lock()


class LocalTranslator(BaseTranslator):
    name = "paperfolio_ollama"

    def __init__(self, source, target, model):
        super().__init__(source, target, ignore_cache=False)
        self.model = model
        self.error = None
        self.untranslated = 0
        self.completed = 0
        self.cancel = None
        self.lock = threading.Lock()
        self.prompt = (
            f"Translate from {LANGUAGES[source]} into {LANGUAGES[target]}. "
            "Output only the translated text. Preserve citations, numbers and placeholders "
            "such as <b1>, </b1> and {v1} exactly. Keep all content."
        )
        self.add_cache_impact_parameters("model", model)
        self.add_cache_impact_parameters("prompt", self.prompt)

    def do_llm_translate(self, text, rate_limit_params=None):
        # BabelDOC probes this method to choose between batch JSON and individual
        # text blocks. Local models receive bounded blocks with inline placeholders.
        raise NotImplementedError

    def translate(self, text, ignore_cache=False, rate_limit_params=None):
        # Returning a fallback outside BaseTranslator keeps it out of the success cache.
        if self.error or not self.has_words(text):
            return text
        try:
            result = super().translate(text, ignore_cache, rate_limit_params)
        except IncompleteGeneration as exc:
            with self.lock:
                self.untranslated += 1
                count = self.untranslated
            report(None, detail=f"重试后仍未完成：{exc}。此块保留原文。", untranslated=count)
            return text
        except (OSError, ValueError) as exc:
            with self.lock:
                if not self.error:
                    self.error = f"本机 Ollama 翻译中断：{exc}"
                    if self.cancel:
                        self.cancel()
            return text
        with self.lock:
            self.completed += 1
        return result

    @staticmethod
    def has_words(text):
        return any(c.isalpha() for c in TOKEN.sub("", text))

    @staticmethod
    def cut(text, limit):
        # Prefer a boundary near the limit. Keep BabelDOC formula/style tokens whole.
        start = limit // 2
        boundaries = list(re.finditer(r"[。！？\n]|[.!?]\s+|\s+", text[start:limit]))
        cut = start + boundaries[-1].end() if boundaries else limit
        for token in TOKEN.finditer(text):
            if token.start() < cut < token.end():
                return token.start() or token.end()
        return cut

    def ask(self, text, *, structured=False):
        if not self.has_words(text):
            return text
        prompt = self.prompt
        schema = None
        if structured:
            prompt = prompt.replace("Output only the translated text.",
                                    "Put the complete translation in the JSON field named translation.")
            schema = {"type": "object", "properties": {"translation": {"type": "string"}},
                      "required": ["translation"]}
        answer = generate(
            self.model,
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            lambda n: report(None, detail=f"本段已生成 {n} 字符"),
            response_format=schema,
            max_tokens=min(3072, max(256, len(text) * 3 + 96)),
        )
        if structured:
            try:
                answer = json.loads(answer)["translation"]
            except (ValueError, KeyError, TypeError) as exc:
                raise IncompleteGeneration("重试回复格式无效") from exc
            if not isinstance(answer, str) or not answer.strip():
                raise IncompleteGeneration("重试后译文为空")
        return answer.strip()

    def translate_part(self, text):
        try:
            return self.ask(text)
        except IncompleteGeneration as exc:
            report(None, detail=f"{exc}，正在单独重试这段文字")
        if len(text) > 220:
            cut = self.cut(text, len(text) // 2)
            return " ".join(self.ask(part, structured=True) for part in (text[:cut], text[cut:]))
        return self.ask(text, structured=True)

    def do_translate(self, text, rate_limit_params=None):
        if self.error:
            raise ValueError(self.error)
        result = []
        while text:
            cut = self.cut(text, 1800) if len(text) > 1800 else len(text)
            result.append(self.translate_part(text[:cut]))
            text = text[cut:]
        return " ".join(result)


class CloudTranslator(BaseTranslator):
    def __init__(self, provider, source, target):
        self.name = "paperfolio_" + provider
        self.model = provider
        self.error = None
        super().__init__(source, target, ignore_cache=False)

    def do_llm_translate(self, text, rate_limit_params=None):
        raise NotImplementedError

    def do_translate(self, text, rate_limit_params=None):
        if self.error:
            raise ValueError(self.error)
        try:
            return cloud_text(self.model, self.lang_in, self.lang_out, text)
        except ValueError as exc:
            self.error = str(exc)
            raise


STAGES = {
    "Parse PDF and Create Intermediate Representation": "解析 PDF",
    "DetectScannedFile": "检测文字层",
    "Parse Page Layout": "分析页面版式",
    "Parse Paragraphs": "识别段落",
    "Parse Formulas and Styles": "识别公式与样式",
    "Translate Paragraphs": "翻译段落",
    "Typesetting": "排版译文",
    "Add Fonts": "嵌入字体",
    "Generate drawing instructions": "生成页面",
    "Subset font": "处理字形",
    "Save PDF": "写入 PDF",
}


async def translate_layout(args, model):
    report("正在检查排版模型和字体")
    warmup()
    source = args.input.resolve()
    spec = args.pages.replace("，", ",").replace(" ", "")
    local = None
    if args.config:
        from pdf2zh_next.config.main import ConfigManager
        from pdf2zh_next.high_level import do_translate_async_stream

        original_args = sys.argv
        try:
            sys.argv = [
                "pdf2zh_next",
                str(source),
                "--config-file",
                str(args.config.resolve()),
                "--output",
                str(args.output.resolve()),
                "--lang-in",
                args.source,
                "--lang-out",
                args.target,
                "--watermark-output-mode",
                "no_watermark",
            ]
            if spec:
                sys.argv.extend(["--pages", spec, "--only-include-translated-page"])
            settings = ConfigManager().initialize_config()
        finally:
            sys.argv = original_args
        settings.basic.input_files = set()
        events = do_translate_async_stream(settings, source)
    else:
        local = (CloudTranslator(args.provider, args.source, args.target) if args.provider in KEYS
                 else LocalTranslator(args.source, args.target, model))
        config = TranslationConfig(
            translator=local,
            input_file=source,
            output_dir=args.output.resolve(),
            lang_in=args.source,
            lang_out=args.target,
            doc_layout_model=CompactLayoutModel(get_doclayout_onnx_model_path()),
            pages=spec or None,
            only_include_translated_page=bool(spec),
            auto_extract_glossary=False,
            qps=1,
            pool_max_workers=1,
            watermark_output_mode=WatermarkOutputMode.NoWatermark,
        )
        if isinstance(local, LocalTranslator):
            local.cancel = config.cancel_translation
        events = async_translate(config)
    finished = False
    async for event in events:
        kind = event["type"]
        if local and local.error:
            raise RuntimeError(local.error)
        if kind.startswith("progress_"):
            stage = event["stage"]
            title = STAGES.get(stage, stage)
            current, total = event["stage_current"], event["stage_total"]
            report(f"{title} · {current}/{total}", event.get("overall_progress"))
        elif kind == "error":
            raise RuntimeError(str(event.get("error", "排版引擎中断")))
        elif kind == "finish":
            finished = True
            break
    if not finished:
        raise RuntimeError("排版引擎在完成前退出")
    if isinstance(local, LocalTranslator) and local.untranslated:
        if not local.completed:
            raise RuntimeError("本次需要翻译的文字均未取得完整译文，请检查模型后重试")
        report("排版完成", 100, f"{local.untranslated} 个文本块保留了原文，可重试补译",
               untranslated=local.untranslated)
