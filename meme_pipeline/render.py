"""Text-to-image rendering with basic typesetting rules.

- short words (prepositions, conjunctions) are glued to the next word with a
  no-break space, so a line never ends with "in" or "and";
- paragraphs are wrapped into balanced lines: first a greedy wrap tells how many
  lines are needed, then a binary search finds the narrowest width that still
  gives that many lines, so lines end up of similar length instead of one long
  line and a short orphan;
- the font size is the largest one at which the whole text fits the box
  (binary search over sizes).
"""
import math
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NBSP = " "
SHORT_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "and", "or", "but", "is", "i",
    "в", "во", "на", "с", "со", "к", "ко", "у", "о", "об", "от", "из", "по", "под", "над", "до",
    "при", "про", "без", "для", "за", "и", "а", "но", "да", "или", "не", "ни", "что", "как",
}


def bind_short_words(text: str, short_words: set[str] = SHORT_WORDS) -> str:
    words = text.split(" ")
    out = []
    for i, word in enumerate(words):
        out.append(word)
        if i < len(words) - 1:
            bare = re.sub(r"^\W+", "", word).lower()
            out.append(NBSP if bare in short_words else " ")
    return "".join(out)


def load_font(path: str | Path | None, size: int) -> ImageFont.FreeTypeFont:
    if path and Path(path).exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text.replace(NBSP, " "), font=font)


def wrap_greedy(paragraph: str, font, max_width: float, draw) -> list[str]:
    lines, current = [], ""
    for word in paragraph.split(" "):
        candidate = f"{current} {word}" if current else word
        if not current or text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_balanced(paragraph: str, font, max_width: float, draw) -> list[str]:
    lines = wrap_greedy(paragraph, font, max_width, draw)
    if len(lines) < 2:
        return lines
    target = len(lines)
    low, high = max_width / 2, max_width
    best = lines
    while high - low > 1:
        mid = (low + high) / 2
        attempt = wrap_greedy(paragraph, font, mid, draw)
        if len(attempt) <= target and all(text_width(draw, l, font) <= max_width for l in attempt):
            best, high = attempt, mid
        else:
            low = mid
    return best


def wrap_text(text: str, font, max_width: float, draw) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        paragraph = bind_short_words(" ".join(paragraph.split()))
        lines += wrap_balanced(paragraph, font, max_width, draw) if paragraph else [""]
    return lines


@dataclass
class Layout:
    font: ImageFont.FreeTypeFont
    lines: list[str]
    line_height: int

    @property
    def height(self) -> int:
        return self.line_height * len(self.lines)


def fit_text(text: str, font_path, box_w: int, box_h: int, min_size=18, max_size=96, spacing=1.25) -> Layout:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def layout(size: int) -> Layout:
        font = load_font(font_path, size)
        return Layout(font, wrap_text(text, font, box_w, draw), int(size * spacing))

    best = layout(min_size)
    low, high = min_size, max_size
    while low <= high:
        mid = (low + high) // 2
        candidate = layout(mid)
        widest = max((text_width(draw, l, candidate.font) for l in candidate.lines), default=0)
        if candidate.height <= box_h and widest <= box_w:
            best, low = candidate, mid + 1
        else:
            high = mid - 1
    return best


def draw_lines(draw, layout: Layout, x_center: float, top: float, fill) -> None:
    for i, line in enumerate(layout.lines):
        line = line.replace(NBSP, " ")
        width = draw.textlength(line, font=layout.font)
        draw.text((x_center - width / 2, top + i * layout.line_height), line, font=layout.font, fill=fill)


def add_watermark(canvas: Image.Image, watermark_path: str | Path | None, opacity: float = 0.6, margin: int = 24) -> None:
    if not watermark_path or not Path(watermark_path).exists():
        return
    mark = Image.open(watermark_path).convert("RGBA")
    scale = canvas.width * 0.18 / mark.width
    mark = mark.resize((int(mark.width * scale), int(mark.height * scale)), Image.LANCZOS)
    alpha = mark.getchannel("A").point(lambda a: int(a * opacity))
    mark.putalpha(alpha)
    canvas.alpha_composite(mark, (canvas.width - mark.width - margin, canvas.height - mark.height - margin))


def caption_card(image_path: str | Path, text: str, font_path=None, size: int = 1080,
                 text_share: float = 0.28, padding: int = 48) -> Image.Image:
    """Square card: text on a white band at the top, the picture below it."""
    canvas = Image.new("RGBA", (size, size), "white")
    band = int(size * text_share)
    layout = fit_text(text, font_path, size - 2 * padding, band - 2 * padding)
    draw_lines(ImageDraw.Draw(canvas), layout, size / 2, (band - layout.height) / 2, "black")

    with Image.open(image_path) as src:
        picture = src.convert("RGBA")
    area_w, area_h = size, size - band
    scale = min(area_w / picture.width, area_h / picture.height)
    picture = picture.resize((max(1, int(picture.width * scale)), max(1, int(picture.height * scale))), Image.LANCZOS)
    canvas.alpha_composite(picture, ((area_w - picture.width) // 2, band + (area_h - picture.height) // 2))
    return canvas


def bubble_polygon(x1, y1, x2, y2, radius, tail_x, tail_height, steps=10) -> list[tuple[float, float]]:
    """Rounded rectangle with a tail at the bottom edge pointing down at tail_x."""
    def arc(cx, cy, start):
        return [
            (cx + radius * math.cos(math.radians(start + 90 * i / steps)),
             cy + radius * math.sin(math.radians(start + 90 * i / steps)))
            for i in range(steps + 1)
        ]

    tail_w = tail_height * 0.8
    points = arc(x1 + radius, y1 + radius, 180) + arc(x2 - radius, y1 + radius, 270)
    points += arc(x2 - radius, y2 - radius, 0)
    points += [(tail_x + tail_w / 2, y2), (tail_x, y2 + tail_height), (tail_x - tail_w / 2, y2)]
    points += arc(x1 + radius, y2 - radius, 90)
    return points


def chat_bubble(text: str, template_path=None, font_path=None, size: int = 1080, header: int = 160,
                padding: int = 56, bubble_fill=(255, 255, 255), text_fill=(20, 20, 20)) -> Image.Image:
    """Text styled as a chat message, drawn over a template with a messenger-like header."""
    if template_path and Path(template_path).exists():
        canvas = Image.open(template_path).convert("RGBA").resize((size, size), Image.LANCZOS)
    else:
        canvas = Image.new("RGBA", (size, size), (229, 221, 213, 255))
        ImageDraw.Draw(canvas).rectangle((0, 0, size, header), fill=(84, 110, 122, 255))

    max_w = size - 4 * padding
    max_h = size - header - 4 * padding
    layout = fit_text(text, font_path, max_w, max_h, max_size=72)
    draw = ImageDraw.Draw(canvas)
    widest = max((draw.textlength(l.replace(NBSP, " "), font=layout.font) for l in layout.lines), default=0)

    bubble_w = widest + 2 * padding
    bubble_h = layout.height + 2 * padding
    x1 = (size - bubble_w) / 2
    y1 = header + (size - header - bubble_h) / 2
    x2, y2 = x1 + bubble_w, y1 + bubble_h
    draw.polygon(bubble_polygon(x1, y1, x2, y2, 36, x1 + 80, 40), fill=bubble_fill)
    draw_lines(draw, layout, size / 2, y1 + padding, text_fill)
    return canvas
