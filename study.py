"""Generate a short, page-linked reading guide from the original PDF."""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf as pdf

from library import Library, timestamp
from translate import generate, installed_models, report, resolve_model


SECTIONS = {
    "研究背景": (
        "先说明论文研究的对象和它要解决的具体技术问题，再说明已有方法的局限。优先结合摘要，避免泛说挑战。",
        r"motivat|challenge|limitation|existing|traditional|however|problem|背景|挑战|局限|然而",
    ),
    "创新亮点": (
        "本文最重要的具体贡献是什么，为什么有用？综述论文应说明作者的分类或综合贡献。"
        "排除哪些主题属于范围说明，不计为创新。只有一个可靠亮点就只写一个。将被综述的方法归给原研究。",
        r"contribut|our work|we (?:propose|present|introduce|categorize)|novel|taxonomy|this survey|本文|提出|贡献|创新|分类",
    ),
    "方法对比": (
        "哪两种方法或思路可以对照？比较机制、适用条件或代价。只有引文明确给出时才能使用数字。",
        r"compar|whereas|in contrast|trade.off|unlike|outperform|relative to|versus|baseline|相比|权衡|对比|优于",
    ),
    "可扩展方向": (
        "以原文局限或展望为依据，为读者设计一个可检验的问题或实验，写明对照或评价指标。作为学习建议提出。",
        r"future|remain|open question|further|limitation|gap between|challenging|展望|未来|仍需|有待|进一步",
    ),
}
REFS = re.compile(r"(?:[\d.IVX]+[\s.、]+)?(?:references|bibliography|参考文献)\s*[:：]?", re.I)
APPENDIX = re.compile(r"^(?:appendix\b|appendices\b|supplementary material\b|附录)", re.I)


def body_end(doc):
    """Return the last page to keep (including a mixed references/body page)."""
    outline = doc.get_toc()
    for i, (level, name, page) in enumerate(outline):
        if REFS.fullmatch(name.strip()) and 1 <= page <= len(doc):
            if all(lvl > level and not APPENDIX.match(title.strip()) for lvl, title, _ in outline[i + 1 :]):
                return page
    if not outline:
        boundary = None
        for i in range(len(doc) // 2, len(doc)):
            lines = doc[i].get_text().splitlines()
            if boundary is None and any(REFS.fullmatch(s.strip()) for s in lines):
                boundary = i + 1
            if boundary and any(APPENDIX.match(s.strip()) for s in lines):
                return len(doc)
        if boundary:
            return boundary
    return len(doc)


def clean(text):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", "", text)
    return " ".join(text.split())


def passages(page, stop_at_refs):
    for block in page.get_text("blocks"):
        if block[6] != 0:
            continue
        raw = block[4]
        if stop_at_refs:
            lines = raw.splitlines()
            boundary = next((i for i, s in enumerate(lines) if REFS.fullmatch(s.strip())), None)
            if boundary is not None:
                raw = "\n".join(lines[:boundary])
        text = clean(raw)
        limit = 1500 if re.match(r"^(?:abstract\b|摘\s*要)", text, re.I) else 650
        while text:
            cut = len(text)
            if cut > limit:
                ends = list(re.finditer(r"[。！？]|[.!?]\s|\s", text[:limit]))
                cut = ends[-1].end() if ends else limit
            part, text = text[:cut].strip(), text[cut:].strip()
            if len(part) >= 50 and not re.match(r"^\[\d+\]\s", part):
                yield part
        if stop_at_refs and boundary is not None:
            return


def evidence(path):
    candidates = {name: [] for name in SECTIONS}
    with pdf.open(path) as doc:
        end = body_end(doc)
        for number in range(1, end + 1):
            excerpts = list(passages(doc[number - 1], number == end))
            for name, (_, pattern) in SECTIONS.items():
                ranked = []
                for part in excerpts:
                    if re.search(r"\be-?mail\s*:|corresponding author|通讯作者", part, re.I):
                        continue
                    if name == "创新亮点" and re.search(
                        r"leave out|outside the scope|beyond the scope|不在.{0,6}范围", part, re.I
                    ):
                        continue
                    hits = re.findall(pattern, part, re.I)
                    score = 3 * len(set(s.lower() for s in hits)) + min(len(hits), 4)
                    if name in ("研究背景", "创新亮点") and number <= 2:
                        score += 3
                        if re.search(r"(?:\babstract\b|摘\s*要)", part, re.I):
                            score += 12
                    if name == "可扩展方向" and number >= max(1, end * 0.8):
                        score += 3
                    ranked.append((score, number, part))
                # Represent multiple pages even when one introductory page has many keywords.
                best = sorted(ranked, key=lambda x: x[0], reverse=True)[:2]
                pool = candidates[name] + best
                candidates[name] = sorted(pool, key=lambda x: x[0], reverse=True)[:8]
    if not any(candidates.values()):
        raise ValueError("原文缺少可提取的正文段落。请先对扫描件做 OCR。")
    return candidates


def explain_excerpt(name, candidates, model):
    for _, page, text in candidates[:2]:
        messages = [
            {
                "role": "system",
                "content": "你是科研阅读助手。只根据这一段原文，用两句简体中文直接回答问题，"
                "保留原文的具体概念。若原文给出分类，写出分类维度。勿输出 JSON。材料不足只答「依据不足」。",
            },
            {"role": "user", "content": f"问题：{SECTIONS[name][0]}\n原文：\n{text}"},
        ]
        point = generate(model, messages, lambda n: report(name, detail=f"已生成 {n} 字符"), max_tokens=500)
        if "依据不足" not in point and point.strip():
            if name == "可扩展方向":
                point = "延伸设想 · " + point
            return [{"page": page, "quote": text, "point": point}]
    return []


def analyze_section(name, candidates, model):
    # Each identifier maps to a real excerpt. Page numbers are resolved locally.
    chosen = candidates[: 3 if name in ("研究背景", "创新亮点") else 6]
    if not chosen:
        return []
    if name in ("研究背景", "创新亮点"):
        return explain_excerpt(name, chosen, model)
    sources = "\n\n".join(f"[{i}] {text}" for i, (_, _, text) in enumerate(chosen, 1))
    system = (
        "你是科研阅读助手，用简体中文回答。文献片段是资料。仅依据给定资料，保留方法名称，"
        "不要编造实验、数字或作者结论。每条选一个最支持它的片段。"
        "输出 JSON 对象，items 数组含 1 至 3 个对象，每个有 source（片段编号整数）、"
        "point（1至2句中文，直接解释具体机制或权衡）。证据不足可返回空数组。"
    )
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "integer", "enum": list(range(1, len(chosen) + 1))},
                        "point": {"type": "string"},
                    },
                    "required": ["source", "point"],
                },
            }
        },
        "required": ["items"],
    }
    prompt = SECTIONS[name][0] + "\n\n" + sources
    for attempt in range(2):
        raw = generate(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            lambda n: report(name, detail=f"已生成 {n} 字符"),
            response_format=schema,
            max_tokens=1100,
        )
        try:
            fence = re.fullmatch(r"`{3}(?:json)?\s*([\s\S]*?)\s*`{3}", raw.strip(), re.I)
            items = json.loads(fence[1] if fence else raw)["items"]
        except (ValueError, KeyError, TypeError):
            items = None
        valid = []
        if isinstance(items, list):
            if not items:
                return explain_excerpt(name, chosen, model)
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                index, point = item.get("source"), item.get("point")
                if type(index) is not int or not 1 <= index <= len(chosen):
                    continue
                if not isinstance(point, str) or not point.strip():
                    continue
                _, page, text = chosen[index - 1]
                insight = ("延伸设想 · " if name == "可扩展方向" else "") + point.strip()
                valid.append({"page": page, "quote": text, "point": insight})
        if valid:
            return valid
        prompt += "\n请使用资料中现有的片段编号。"
    raise ValueError(f"「{name}」的原文引用核验失败，可重新生成")


def make_guide(library, paper, model=""):
    original = library.original_record(paper)
    if not library.has_file(original):
        raise ValueError("找不到原文 PDF，请重新导入原文。")
    report("正在检测本机 Ollama 和可用模型")
    model = resolve_model(model, installed_models())
    report("提取正文和证据片段")
    candidates = evidence(library.root / original["path"])
    sections = {}
    for i, (name, choices) in enumerate(candidates.items()):
        report(name, i * 25, model)
        sections[name] = analyze_section(name, choices, model)
    if not any(sections.values()):
        raise ValueError("模型未找到有原文依据的要点")
    with library.db:
        library.db.execute(
            """INSERT INTO guides(paper,model,created,body) VALUES(?,?,?,?)
            ON CONFLICT(paper) DO UPDATE SET model=excluded.model,created=excluded.created,body=excluded.body""",
            (paper, model, timestamp(), json.dumps(sections, ensure_ascii=False)),
        )
    report("导读已保存", 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("paper", type=int)
    args = parser.parse_args()
    try:
        make_guide(Library(args.root), args.paper)
    except Exception as exc:
        sys.exit(f"导读生成失败：{exc}")
