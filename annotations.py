"""Character selection in unrotated PDF coordinates."""

from dataclasses import dataclass

import pymupdf as pdf


COLORS = {"黄": "#ffe38a", "绿": "#a8e6ae", "蓝": "#a9dcff", "粉": "#ffb6cf", "紫": "#d8bef7"}


def distance(box, point):
    x0, y0, x1, y1 = box
    return max(x0 - point.x, 0, point.x - x1) ** 2 + max(y0 - point.y, 0, point.y - y1) ** 2


@dataclass
class TextLine:
    bounds: tuple
    chars: list


class PageText:
    def __init__(self, page):
        raw = page.get_text("rawdict", flags=pdf.TEXTFLAGS_RAWDICT & ~pdf.TEXT_PRESERVE_IMAGES)
        self.lines = []
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                chars = [(c["c"], c["bbox"]) for span in line["spans"] for c in span["chars"]]
                if chars:
                    self.lines.append(TextLine(line["bbox"], chars))

    def nearest(self, point, *, require_hit=False):
        if not self.lines:
            return None
        line = min(range(len(self.lines)), key=lambda i: distance(self.lines[i].bounds, point))
        chars = self.lines[line].chars
        index = min(range(len(chars)), key=lambda i: distance(chars[i][1], point))
        if require_hit and distance(chars[index][1], point) > 5 ** 2:
            return None
        return line, index

    def selection(self, anchor, end):
        (first, a), (last, b) = sorted((anchor, end))
        text, rects = [], []
        for i in range(first, last + 1):
            chars = self.lines[i].chars
            run = chars[a if i == first else 0 : b + 1 if i == last else len(chars)]
            rect = pdf.Rect(run[0][1])
            for _, box in run[1:]:
                rect.include_rect(box)
            rects.append(tuple(rect))
            text.append("".join(c for c, _ in run))
        return "\n".join(text).strip(), rects
