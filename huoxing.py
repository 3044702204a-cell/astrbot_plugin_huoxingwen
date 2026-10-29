"""火星文 / 繁体字转换核心。

码表来自 huoxingwen.qianwanku.com 的 huoxing.js，三张等长码表按索引一一对应，
转换逻辑与站点保持一致：简体 -> 火星文，繁体 -> 火星文。
"""

from __future__ import annotations

import random
import re
from typing import Iterable, Iterator, Sequence

try:
    from .huoxing_tables import MARTIAN, SIMP, TRAD
except ImportError:  # pragma: no cover - 兼容非包方式加载
    from huoxing_tables import MARTIAN, SIMP, TRAD

# 简体 / 繁体 -> 火星文
TO_MARTIAN: dict[str, str] = {}
# 简体 -> 繁体
TO_TRADITIONAL: dict[str, str] = {}

for _s, _t, _m in zip(SIMP, TRAD, MARTIAN):
    TO_MARTIAN.setdefault(_s, _m)
    TO_TRADITIONAL.setdefault(_s, _t)
    if _t != _s:
        TO_MARTIAN.setdefault(_t, _m)
        TO_TRADITIONAL.setdefault(_t, _t)

MODES = ("huoxing", "traditional", "mix")
MODE_LABELS = {
    "huoxing": "火星文",
    "traditional": "繁体字",
    "mix": "火星文+繁体混排",
}

DEFAULT_DECORATIONS = "ゞ﹏ヾ灬のヽ〆゛☆★誮"

# 需要原样保留的片段（代码、链接、@ 等）
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]{}（）【】《》\"']+")
_CQ_CODE = re.compile(r"\[CQ:[^\]]*\]")
_AT = re.compile(r"(?<![\w])@[A-Za-z0-9_\u4e00-\u9fff\-]{1,32}")


def _protected_spans(text: str, patterns: Sequence[re.Pattern]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    if not spans:
        return []
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _map_chars(chars: Iterable[str], mode: str, rng: random.Random) -> str:
    if mode == "traditional":
        return "".join(TO_TRADITIONAL.get(ch, ch) for ch in chars)
    if mode == "mix":
        out = []
        for ch in chars:
            hx = TO_MARTIAN.get(ch)
            if hx is None:
                out.append(ch)
            elif hx == ch or rng.random() < 0.55:
                out.append(hx)
            else:
                out.append(TO_TRADITIONAL.get(ch, ch))
        return "".join(out)
    return "".join(TO_MARTIAN.get(ch, ch) for ch in chars)


def _decorate(text: str, chars: str, rng: random.Random) -> str:
    pool = [c for c in chars if not c.isspace()]
    if not pool or not text.strip():
        return text
    head = rng.choice(pool) if rng.random() < 0.8 else ""
    tail = rng.choice(pool) if rng.random() < 0.8 else ""
    body = text.strip()
    return f"{head}{body}{tail}"


def to_martian(
    text: str,
    *,
    mode: str = "huoxing",
    protect_code: bool = True,
    protect_url: bool = True,
    protect_at: bool = True,
    decorate: bool = False,
    decoration_chars: str = DEFAULT_DECORATIONS,
    rng: random.Random | None = None,
) -> str:
    """把一段文本转换成火星文（或繁体 / 混排）。"""
    if not text:
        return text
    if mode not in MODES:
        mode = "huoxing"
    rng = rng or random.Random()

    patterns: list[re.Pattern] = [_CQ_CODE]
    if protect_code:
        patterns.extend([_CODE_FENCE, _INLINE_CODE])
    if protect_url:
        patterns.append(_URL)
    if protect_at:
        patterns.append(_AT)

    spans = _protected_spans(text, patterns)
    if not spans:
        result = _map_chars(text, mode, rng)
    else:
        pieces: list[str] = []
        cursor = 0
        for start, end in spans:
            if start > cursor:
                pieces.append(_map_chars(text[cursor:start], mode, rng))
            pieces.append(text[start:end])
            cursor = end
        if cursor < len(text):
            pieces.append(_map_chars(text[cursor:], mode, rng))
        result = "".join(pieces)

    if decorate:
        result = _decorate(result, decoration_chars, rng)
    return result


def iter_preview(text: str, modes: Sequence[str] = MODES) -> Iterator[tuple[str, str]]:
    """给测试/调试用的多模式预览。"""
    for mode in modes:
        yield MODE_LABELS.get(mode, mode), to_martian(text, mode=mode)
