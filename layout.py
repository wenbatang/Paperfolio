"""PDF2Zh layout pipeline with native Ollama generation and progress events."""

import ast
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

from translate import LANGUAGES, generate, report
from cloud_translate import KEYS, cloud_text


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

    def do_translate(self, text, rate_limit_params=None):
        if self.error:
            raise ValueError(self.error)
        result = []
        while text:
            cut = len(text)
            if cut > 1800:
                breaks = list(re.finditer(r"[。！？\n]|[.!?]\s+|\s+", text[:1800]))
                cut = breaks[-1].end() if breaks else 1800
            part, text = text[:cut], text[cut:]
            if not part.strip():
                result.append(part)
                continue
            try:
                result.append(
                    generate(
                        self.model,
                        [{"role": "system", "content": self.prompt}, {"role": "user", "content": part}],
                        lambda n: report(None, detail=f"本段已生成 {n} 字符"),
                    )
                )
            except (ValueError, OSError) as error:
                self.error = f"本机模型未完成当前段落：{error}"
                raise ValueError(self.error) from error
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
