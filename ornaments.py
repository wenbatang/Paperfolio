"""Small, locally drawn ornaments for the unused parts of the library window."""

from dataclasses import dataclass
from functools import lru_cache
from math import cos, pi, sin
import tkinter as tk

from PIL import Image, ImageColor, ImageDraw, ImageTk


@dataclass(frozen=True)
class Palette:
    title: str
    rail: str
    accent: str
    tint: str
    paper: str
    leaf: str
    gold: str
    motifs: tuple


STYLES = {
    "spring": Palette(
        "春日花园",
        "#243e36",
        "#39664f",
        "#e6efdf",
        "#f6f8f1",
        "#88b98f",
        "#edaaa7",
        ("blossom", "sprout", "butterfly", "swallow", "tulip", "snail"),
    ),
    "summer": Palette(
        "夏日海岸",
        "#1c3c4a",
        "#216678",
        "#dff0ef",
        "#f3f8f6",
        "#80c4bf",
        "#efb078",
        ("wave", "shell", "sailboat", "lighthouse", "starfish", "melon"),
    ),
    "autumn": Palette(
        "秋林手记",
        "#48332a",
        "#855133",
        "#f3e6d5",
        "#faf5ec",
        "#c79963",
        "#e99564",
        ("maple", "acorn", "pumpkin", "mushroom", "wheat", "pinecone"),
    ),
    "winter": Palette(
        "冬山行旅",
        "#293d50",
        "#44667c",
        "#e3ecf3",
        "#f3f7fa",
        "#97bbd2",
        "#dfab99",
        ("snowflake", "fir", "mitten", "crystal", "scarf", "igloo"),
    ),
    "day": Palette(
        "日光书斋",
        "#44392d",
        "#795936",
        "#f3e9d1",
        "#faf6ec",
        "#95b19a",
        "#e5bb76",
        ("book", "teacup", "pencil", "lamp", "inkwell", "glasses"),
    ),
    "night": Palette(
        "星夜漫游",
        "#292c47",
        "#555781",
        "#e7e6f1",
        "#f5f4f9",
        "#aba6d5",
        "#e7c983",
        ("crescent", "saturn", "comet", "dipper", "telescope", "aurora"),
    ),
}
PAPER_COLORS = {
    "纸白": ("#f7f8f4", "#f1f5f0"),
    "暖杏": ("#faf0df", "#faf4e9"),
    "鼠尾草": ("#e4eee3", "#edf4ed"),
    "雾蓝": ("#e5edf4", "#edf3f8"),
}
DENSITIES = ("丰富", "疏朗", "关闭")


def preference(library):
    key = library.preference("ornament_style")
    if key in STYLES:
        return key
    return {"暖杏": "autumn", "雾蓝": "winter"}.get(library.preference("theme"), "spring")


def mix(a, b, amount):
    values = (round(x + (y - x) * amount) for x, y in zip(ImageColor.getrgb(a), ImageColor.getrgb(b)))
    return "#%02x%02x%02x" % tuple(values)


class Pen:
    """A 32-unit drawing grid rendered at four times its design resolution."""

    def __init__(self, palette, dark):
        self.im = Image.new("RGBA", (128, 128))
        self.draw = ImageDraw.Draw(self.im)
        self.ink = "#ece9d8" if dark else palette.rail
        self.leaf, self.gold = palette.leaf, palette.gold
        self.cream = "#fff2d6"

    @staticmethod
    def coords(values):
        return tuple(round(v * 4) for v in values)

    def line(self, *xy, color=None, width=1.5):
        self.draw.line(self.coords(xy), fill=color or self.ink, width=round(width * 4), joint="curve")

    def shape(self, points, fill):
        self.draw.polygon(self.coords(points), fill=fill)
        self.line(*points, *points[:2])

    def oval(self, box, fill, outline=True):
        self.draw.ellipse(self.coords(box), fill=fill, outline=self.ink if outline else None, width=5)

    def arc(self, box, start, end, color=None, width=1.5):
        self.draw.arc(self.coords(box), start, end, fill=color or self.ink, width=round(width * 4))

    def dot(self, x, y, r, color):
        self.oval((x - r, y - r, x + r, y + r), color, False)

    def star(self, x, y, outer, inner, fill, arms=5):
        coords = []
        for i in range(arms * 2):
            a = pi * i / arms - pi / 2
            radius = inner if i % 2 else outer
            coords.extend((x + radius * cos(a), y + radius * sin(a)))
        self.shape(coords, fill)


def spring(p, motif):
    if motif == "blossom":
        for i in range(5):
            a = i * 2 * pi / 5 - pi / 2
            x, y = 16 + 6 * cos(a), 16 + 6 * sin(a)
            p.oval((x - 4.8, y - 5, x + 4.8, y + 5), p.gold)
        p.dot(16, 16, 3, p.cream)
        p.dot(16, 16, 1.2, p.ink)
    elif motif == "sprout":
        p.shape((16, 20, 10, 19, 5, 14, 3, 9, 10, 10, 15, 14), p.leaf)
        p.shape((16, 16, 17, 9, 23, 5, 29, 5, 26, 11, 21, 15), p.leaf)
        p.line(8, 13, 16, 20, 16, 26, width=1.7)
        p.line(16, 19, 24, 9)
        p.arc((7, 23, 25, 30), 185, 350)
    elif motif == "butterfly":
        p.oval((3, 5, 16, 20), p.gold)
        p.oval((16, 5, 29, 20), p.gold)
        p.oval((7, 16, 16, 26), p.leaf)
        p.oval((16, 16, 25, 26), p.leaf)
        p.dot(9, 12, 2, p.cream)
        p.dot(23, 12, 2, p.cream)
        p.line(13, 5, 16, 10, 19, 5)
        p.line(16, 10, 16, 24, width=2.1)
    elif motif == "swallow":
        p.shape(
            (2, 7, 13, 12, 21, 6, 27, 5, 23, 11, 30, 13, 23, 15, 17, 20, 13, 27, 13, 20, 5, 24, 10, 17),
            p.leaf,
        )
        p.line(5, 9, 14, 16, 21, 12)
        p.dot(24, 9, 1, p.ink)
    elif motif == "tulip":
        p.line(16, 15, 16, 29)
        p.shape((6, 21, 11, 21, 16, 27, 11, 26), p.leaf)
        p.shape((16, 25, 20, 20, 27, 18, 23, 24), p.leaf)
        p.shape((9, 5, 14, 9, 16, 3, 20, 9, 24, 5, 23, 14, 19, 18, 14, 18, 10, 14), p.gold)
    else:  # snail
        p.shape((3, 24, 19, 23, 23, 17, 28, 16, 29, 20, 25, 24, 19, 26, 6, 26), p.leaf)
        p.oval((4, 9, 20, 25), p.gold)
        p.arc((8, 12, 17, 22), 30, 320)
        p.arc((11, 15, 16, 19), 210, 490)
        p.line(24, 17, 23, 12)
        p.line(27, 17, 29, 12)
        p.dot(23, 12, 1.2, p.ink)
        p.dot(29, 12, 1.2, p.ink)


def summer(p, motif):
    if motif == "wave":
        p.shape(
            (
                2,
                23,
                7,
                22,
                11,
                18,
                14,
                11,
                19,
                7,
                25,
                7,
                29,
                11,
                25,
                10,
                21,
                13,
                21,
                17,
                25,
                20,
                30,
                19,
                28,
                24,
                18,
                25,
                11,
                24,
                5,
                26,
            ),
            p.leaf,
        )
        p.line(6, 21, 11, 20, 15, 15)
        p.dot(9, 10, 1.5, p.gold)
        p.dot(13, 6, 1, p.leaf)
    elif motif == "shell":
        p.shape(
            (
                13,
                26,
                4,
                19,
                3,
                14,
                5,
                11,
                7,
                11,
                9,
                7,
                13,
                7,
                16,
                4,
                19,
                7,
                23,
                7,
                25,
                11,
                28,
                12,
                29,
                17,
                27,
                20,
                19,
                26,
            ),
            p.gold,
        )
        for x, y in ((6, 13), (10, 9), (16, 7), (22, 9), (26, 14)):
            p.line(16, 24, x, y, width=1)
        p.line(12, 27, 20, 27)
    elif motif == "sailboat":
        p.line(17, 3, 17, 24)
        p.shape((15, 6, 5, 20, 15, 20), p.cream)
        p.shape((19, 8, 19, 21, 27, 21), p.gold)
        p.shape((3, 23, 29, 23, 24, 27, 8, 27), p.leaf)
        p.line(4, 29, 10, 28, 15, 29, 20, 28, 27, 29, width=1)
    elif motif == "lighthouse":
        p.shape((12, 11, 20, 11, 23, 27, 9, 27), p.cream)
        p.shape((11, 18, 21, 16, 21, 20, 10, 22), p.gold)
        p.shape((11, 7, 21, 7, 21, 12, 11, 12), p.leaf)
        p.shape((9, 7, 16, 3, 23, 7), p.gold)
        p.line(6, 28, 26, 28)
        p.line(3, 9, 8, 8)
        p.line(24, 8, 29, 7)
    elif motif == "starfish":
        p.star(16, 16, 13, 5.4, p.gold)
        for x, y in ((16, 9), (21, 14), (20, 21), (12, 21), (10, 14)):
            p.dot(x, y, 1, p.cream)
    else:  # watermelon
        p.shape((3, 11, 29, 11, 28, 17, 25, 22, 20, 26, 15, 27, 9, 25, 5, 20), p.leaf)
        p.shape((5, 12, 27, 12, 25, 18, 21, 22, 16, 24, 11, 22, 7, 18), p.gold)
        for x, y in ((9, 14), (15, 16), (22, 14), (13, 20), (19, 19)):
            p.line(x, y, x - 0.5, y + 1.3, width=1.2)


def autumn(p, motif):
    if motif == "maple":
        p.shape(
            (
                16,
                3,
                19,
                10,
                22,
                7,
                22,
                15,
                28,
                11,
                26,
                16,
                30,
                18,
                22,
                23,
                17,
                23,
                15,
                27,
                14,
                23,
                8,
                24,
                3,
                18,
                7,
                17,
                4,
                12,
                11,
                15,
                10,
                8,
                14,
                11,
            ),
            p.gold,
        )
        p.line(13, 29, 16, 23, 16, 10)
        p.line(8, 17, 16, 22, 23, 17, width=1)
    elif motif == "acorn":
        p.oval((8, 10, 24, 27), p.gold)
        p.shape((6, 15, 8, 10, 13, 7, 20, 7, 25, 10, 26, 14, 18, 16, 11, 16), p.leaf)
        p.line(16, 8, 18, 4, 22, 3)
        p.line(11, 11, 12, 13, 14, 10, 16, 12, 18, 9, 20, 11, width=1)
    elif motif == "pumpkin":
        p.oval((3, 11, 17, 26), p.gold)
        p.oval((15, 11, 29, 26), p.gold)
        p.oval((9, 9, 23, 27), p.gold)
        p.arc((12, 10, 20, 27), 95, 260, width=1)
        p.shape((14, 10, 15, 5, 19, 4, 18, 10), p.leaf)
        p.arc((19, 4, 26, 11), 180, 420)
    elif motif == "mushroom":
        p.shape((13, 17, 19, 17, 22, 27, 18, 29, 11, 27), p.cream)
        p.shape((3, 18, 5, 13, 10, 8, 15, 6, 20, 7, 26, 12, 29, 17, 27, 19, 6, 20), p.gold)
        for x, y, r in ((11, 13, 1.7), (17, 10, 1.1), (22, 15, 1.8), (15, 17, 1)):
            p.dot(x, y, r, p.cream)
    elif motif == "wheat":
        p.line(7, 29, 23, 6)
        for x, y in ((10, 23), (14, 17), (18, 11)):
            p.shape((x, y, x - 4, y - 2, x - 5, y - 7, x - 1, y - 5), p.leaf)
            p.shape((x, y, x + 5, y, x + 9, y - 5, x + 3, y - 4), p.gold)
        p.line(21, 9, 24, 3)
    else:  # pine cone
        p.shape((15, 5, 20, 6, 24, 12, 25, 18, 21, 25, 16, 29, 10, 25, 6, 18, 7, 12, 11, 7), p.leaf)
        for x, y in ((10, 11), (16, 10), (8, 16), (14, 16), (20, 15), (11, 21), (17, 21), (14, 25)):
            p.line(x, y, x + 2, y + 2, x + 4, y - 1, width=1)
        p.line(16, 6, 19, 2)


def winter(p, motif):
    if motif == "snowflake":
        for i in range(6):
            a = i * pi / 3 + pi / 6
            x, y = cos(a), sin(a)
            p.line(16, 16, 16 + 12 * x, 16 + 12 * y, color=p.ink)
            for sign in (-1, 1):
                p.line(
                    16 + 7 * x, 16 + 7 * y, 16 + 9 * x - sign * 3 * y, 16 + 9 * y + sign * 3 * x, color=p.ink
                )
        p.dot(16, 16, 2.2, p.leaf)
    elif motif == "fir":
        p.shape((14, 23, 18, 23, 18, 29, 14, 29), p.gold)
        p.shape((16, 3, 23, 12, 20, 12, 26, 19, 22, 19, 29, 25, 3, 25, 10, 19, 6, 19, 12, 12, 9, 12), p.leaf)
        p.line(12, 12, 15, 10, 17, 12, 20, 11, color=p.cream)
        p.line(9, 19, 14, 17, 17, 19, 21, 18, color=p.cream)
    elif motif == "mitten":
        p.shape(
            (10, 22, 7, 18, 5, 14, 6, 11, 9, 10, 12, 14, 12, 7, 15, 4, 19, 4, 23, 6, 25, 10, 24, 18, 20, 24),
            p.leaf,
        )
        p.shape((9, 21, 21, 23, 20, 28, 8, 26), p.gold)
        p.star(18, 13, 4, 1.5, p.cream, 4)
    elif motif == "crystal":
        p.shape((7, 11, 15, 3, 23, 10, 23, 23, 16, 29, 8, 23), p.leaf)
        p.line(15, 3, 13, 12, 15, 28)
        p.line(23, 10, 19, 13, 16, 28)
        p.line(8, 11, 13, 12, 19, 13, 23, 10)
        p.line(3, 19, 6, 21)
        p.line(26, 7, 29, 5)
    elif motif == "scarf":
        p.shape((7, 7, 22, 7, 26, 10, 24, 14, 11, 16, 6, 13), p.leaf)
        p.shape((12, 15, 17, 15, 16, 27, 10, 26), p.gold)
        p.shape((18, 14, 23, 13, 27, 23, 22, 26), p.leaf)
        p.line(11, 22, 16, 23)
        p.line(22, 20, 25, 18)
        for x in (11, 13, 15):
            p.line(x, 26, x - 1, 29, width=1)
    else:  # igloo
        p.shape((3, 24, 4, 17, 7, 12, 12, 8, 18, 7, 23, 10, 26, 14, 29, 22, 28, 25), p.leaf)
        p.line(6, 15, 25, 15)
        p.line(4, 20, 26, 20)
        p.line(14, 9, 14, 15)
        p.line(9, 15, 9, 20)
        p.line(20, 15, 20, 19)
        p.shape((15, 25, 15, 21, 18, 17, 22, 17, 25, 21, 25, 25), p.cream)
        p.arc((18, 20, 23, 28), 175, 365)


def day(p, motif):
    if motif == "book":
        p.shape((3, 7, 9, 6, 16, 9, 22, 6, 29, 7, 28, 25, 23, 24, 16, 27, 9, 24, 3, 25), p.cream)
        p.line(16, 9, 16, 26)
        p.line(6, 11, 10, 10, 13, 12)
        p.line(6, 15, 11, 15, 13, 16)
        p.shape((22, 7, 25, 7, 25, 16, 23, 14, 21, 16), p.gold)
    elif motif == "teacup":
        p.arc((20, 10, 29, 20), 245, 460, width=2)
        p.shape((5, 12, 23, 12, 22, 18, 19, 23, 11, 24, 7, 20), p.leaf)
        p.arc((3, 21, 26, 28), 5, 175)
        p.line(10, 9, 12, 6, 11, 3)
        p.line(16, 9, 18, 6, 17, 3)
    elif motif == "pencil":
        p.shape((4, 26, 6, 18, 22, 3, 28, 9, 12, 25, 3, 28), p.gold)
        p.shape((4, 26, 6, 18, 12, 25, 3, 28), p.cream)
        p.line(9, 21, 24, 6)
        p.line(19, 6, 25, 12)
        p.line(15, 28, 29, 28, color=p.leaf)
    elif motif == "lamp":
        p.line(16, 12, 22, 17, 15, 26, width=2.4)
        p.oval((20, 15, 24, 19), p.gold)
        p.shape((7, 4, 15, 5, 19, 12, 4, 16), p.leaf)
        p.line(5, 18, 19, 14, color=p.gold)
        p.shape((9, 26, 21, 26, 24, 29, 7, 29), p.leaf)
    elif motif == "inkwell":
        p.shape((7, 17, 18, 17, 21, 21, 21, 28, 4, 28, 4, 21), p.leaf)
        p.shape((8, 14, 17, 14, 17, 18, 8, 18), p.gold)
        p.shape((14, 16, 17, 9, 22, 5, 29, 3, 27, 9, 21, 14), p.cream)
        p.line(13, 20, 24, 8)
        p.line(7, 22, 12, 22, color=p.cream)
    else:  # spectacles
        p.oval((3, 14, 14, 24), p.cream)
        p.oval((18, 14, 29, 24), p.cream)
        p.arc((12, 13, 20, 20), 205, 335)
        p.line(3, 17, 7, 8, 11, 7)
        p.line(29, 17, 26, 8, 23, 8)
        p.line(6, 19, 9, 16, color=p.leaf)
        p.line(21, 19, 24, 16, color=p.leaf)


def night(p, motif):
    if motif == "crescent":
        p.shape(
            (
                21,
                4,
                15,
                5,
                10,
                9,
                8,
                14,
                9,
                20,
                13,
                25,
                19,
                27,
                25,
                25,
                28,
                21,
                22,
                22,
                17,
                20,
                14,
                16,
                14,
                11,
                17,
                6,
            ),
            p.gold,
        )
        p.star(25, 9, 3.3, 1.2, p.leaf, 4)
    elif motif == "saturn":
        p.oval((8, 7, 25, 24), p.leaf)
        p.arc((1, 11, 31, 24), 180, 322, color=p.gold, width=2.5)
        p.arc((1, 9, 31, 23), 0, 180, color=p.ink, width=2.6)
        p.arc((1, 8, 31, 22), 0, 180, color=p.gold, width=1.4)
        p.dot(26, 5, 1, p.gold)
    elif motif == "comet":
        p.shape((5, 23, 9, 16, 20, 8, 29, 4, 21, 13, 14, 20), p.leaf)
        p.line(12, 18, 22, 11, color=p.cream)
        p.line(16, 21, 27, 14, color=p.gold)
        p.star(8, 23, 6, 3, p.gold)
    elif motif == "dipper":
        points = (3, 8, 9, 9, 14, 13, 18, 14, 26, 10, 29, 17, 22, 21, 18, 14)
        p.line(*points, color=p.leaf)
        for x, y in zip(points[::2], points[1::2]):
            p.dot(x, y, 1.8, p.gold)
        p.star(8, 22, 2.8, 1, p.cream, 4)
    elif motif == "telescope":
        p.shape((5, 14, 23, 5, 26, 11, 8, 19), p.leaf)
        p.shape((21, 5, 25, 3, 29, 11, 25, 13), p.gold)
        p.line(7, 16, 3, 19, 4, 21, 9, 18)
        p.line(16, 15, 16, 21, 10, 28)
        p.line(16, 21, 23, 28)
    else:  # aurora
        p.shape((3, 12, 9, 10, 16, 4, 21, 4, 17, 10, 12, 14, 8, 16, 3, 20), p.leaf)
        p.line(13, 17, 20, 12, 26, 7, 29, 7, color=p.gold, width=2)
        p.shape((3, 27, 10, 20, 15, 25, 20, 19, 29, 27), p.cream)
        p.dot(5, 6, 1, p.gold)
        p.dot(25, 16, 1, p.gold)


DRAW = {"spring": spring, "summer": summer, "autumn": autumn, "winter": winter, "day": day, "night": night}


@lru_cache(maxsize=180)
def glyph(style, motif, size, dark=False):
    p = Pen(STYLES[style], dark)
    DRAW[style](p, motif)
    return p.im.resize((size, size), Image.Resampling.LANCZOS)


def ribbon(style, width, height, ground, density, *, dark=False, offset=0, cluster=False):
    surface = Image.new("RGB", (width, height), ground)
    if density == "关闭" or width < 32 or height < 18:
        return surface
    motifs = STYLES[style].motifs
    size = min(36 if cluster else 25, height - 4)
    step = size + (14 if density == "丰富" else 28)
    columns = max(0, (width - 8 + step - size) // step)
    max_rows = 2 if cluster and height >= size * 2 + 16 else 1
    count = min(len(motifs) if density == "丰富" else 3, columns * max_rows)
    if not count:
        return surface
    cols = min(columns, (count + 1) // 2) if max_rows == 2 and count > 3 else min(count, columns)
    rows = (count + cols - 1) // cols
    for i in range(count):
        row, col = divmod(i, cols)
        per_row = min(cols, count - row * cols)
        x = (width - (per_row - 1) * step - size) // 2 + col * step
        y = (height - rows * (size + 4) + 4) // 2 + row * (size + 4) + (2 if col % 2 else 0)
        icon = glyph(style, motifs[(i + offset) % len(motifs)], size, dark)
        surface.paste(icon, (x, y), icon)
    return surface


class MotifStrip(tk.Canvas):
    def __init__(self, parent, *, dark=False, offset=0, cluster=False):
        super().__init__(parent, width=1, height=1, bd=0, highlightthickness=0, takefocus=False)
        self.options = dict(dark=dark, offset=offset, cluster=cluster)
        self.pending = self.photo = self.signature = None
        self.style_key, self.density, self.ground = "spring", "丰富", "#ffffff"
        self.item = self.create_image(0, 0, anchor="nw")
        self.bind("<Configure>", self.schedule)
        self.bind("<Destroy>", self.cancel)

    def theme(self, key, density, ground):
        self.style_key, self.density, self.ground = key, density, ground
        self.configure(bg=ground)
        self.schedule()

    def schedule(self, _=None):
        if self.pending is None:
            self.pending = self.after_idle(self.paint)

    def cancel(self, _=None):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None

    def paint(self):
        self.pending = None
        width, height = self.winfo_width(), self.winfo_height()
        key = self.style_key, width, height, self.ground, self.density
        if width < 2 or height < 2 or key == self.signature:
            return
        self.signature = key
        self.photo = ImageTk.PhotoImage(ribbon(*key, **self.options), master=self)
        self.itemconfigure(self.item, image=self.photo)
