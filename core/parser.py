"""剧本配音 · 段标解析器（纯函数，不联网、不依赖 ComfyUI）。

命名遵循 draft/术语表.md：
- 段标 segment marker：行首 [@Rn] / [@Rn:情绪]
- 段 segment：段标到下一个段标之间的内容
- 角色 role：由参考音色定义的说话者，R0 起
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Dict, List, Optional

BUILTIN_ROLE_COUNT = 10

ROLE_PATTERN = re.compile(r"^[Rr](\d+)$")

# 中文/英文情绪标签 → 内部键（顺序与上游 8 维一致）
EMOTION_ALIASES = {
    "happy": ("开心", "高兴", "happy"),
    "angry": ("愤怒", "生气", "angry"),
    "sad": ("悲伤", "sad"),
    "afraid": ("害怕", "恐惧", "afraid"),
    "disgusted": ("厌恶", "disgusted"),
    "melancholic": ("低落", "忧郁", "melancholy", "melancholic"),
    "surprised": ("惊讶", "surprised"),
    "calm": ("平静", "自然", "calm"),
}
_ALIAS_TO_KEY = {alias: key for key, aliases in EMOTION_ALIASES.items() for alias in aliases}
_ALIASES_BY_LENGTH = sorted(_ALIAS_TO_KEY, key=len, reverse=True)


class ParseError(Exception):
    """段标语法错误；携带错误码与行号。"""

    def __init__(self, code: str, line: int, message: str = ""):
        super().__init__("%s（第 %d 行）%s" % (code, line, ("：" + message) if message else ""))
        self.code = code
        self.line = line
        self.message = message


@dataclasses.dataclass
class Emotion:
    """一段的情绪：follow（跟随）/ vector（8 维）/ text（自由描述）。"""

    mode: str = "follow"
    vector: Dict[str, float] = dataclasses.field(default_factory=dict)
    text: str = ""
    explicit_weight: bool = False

    def to_dict(self) -> Any:
        if self.mode == "follow":
            return "follow"
        if self.mode == "vector":
            return {"vector": dict(self.vector)}
        return {"text": self.text}


@dataclasses.dataclass
class Segment:
    """一个段：角色、情绪、文本。"""

    index: int
    line: int
    role: int
    emotion: Emotion
    text: str
    status: str = "ok"  # ok / empty


def _parse_weight(raw: str, line: int) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ParseError("WEIGHT_RANGE", line, "权重无法解析：%s" % raw)
    if value < 0 or value > 1:
        raise ParseError("WEIGHT_RANGE", line, "权重需在 0–1，当前 %s" % raw)
    return value


def parse_emotion(raw: Optional[str], line: int = 1) -> Emotion:
    """把段标里的情绪字段解析成 Emotion。"""
    if raw is None:
        return Emotion()
    text = raw.strip()
    if not text:
        return Emotion()
    if text == "跟随":
        return Emotion()

    # 误写成 开心=0.8 时给出明确错误
    if "=" in text:
        left = text.split("=", 1)[0].strip()
        if left in _ALIAS_TO_KEY:
            raise ParseError("EQ_SYNTAX", line, "请写成 开心0.8，不要用等号")

    vector: Dict[str, float] = {}
    explicit = False
    for part in text.split("+"):
        piece = part.strip()
        if not piece:
            raise ParseError("WEIGHT_RANGE", line, "情绪表达式有空项")
        matched = None
        for alias in _ALIASES_BY_LENGTH:
            if piece == alias:
                matched = (alias, "")
                break
            if piece.startswith(alias):
                rest = piece[len(alias):]
                if re.fullmatch(r"-?\d+(?:\.\d+)?", rest):
                    matched = (alias, rest)
                    break
        if matched is None:
            return Emotion(mode="text", text=text)
        alias, weight_raw = matched
        key = _ALIAS_TO_KEY[alias]
        if weight_raw:
            explicit = True
        value = 1.0 if not weight_raw else _parse_weight(weight_raw, line)
        vector[key] = vector.get(key, 0.0) + value
    return Emotion(mode="vector", vector=vector, explicit_weight=explicit)


def _split_lines(text: str) -> List[str]:
    lines = text.split("\n")
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def parse_document(text: Optional[str], ref_audios_count: int = 0) -> Dict[str, Any]:
    """把带段标的剧本解析成段列表。

    返回 {"segments": [Segment...], "warnings": ["INDENT:3", ...]}。
    语法错误抛 ParseError（带错误码与行号）。
    """
    if text is None:
        text = ""
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise ParseError("EMPTY_TEXT", 1, "没有可合成内容")

    warnings: List[str] = []
    raw_segments: List[Dict[str, Any]] = []
    preamble: List[str] = []

    for line_no, line in enumerate(_split_lines(text), start=1):
        if line.startswith("[@"):
            close = line.find("]")
            if close < 0:
                raise ParseError("MARKER_UNCLOSED", line_no, "段标缺少 ]")
            inner = line[2:close]
            role_part, _, emotion_part = inner.partition(":")
            match = ROLE_PATTERN.match(role_part.strip())
            if not match:
                raise ParseError("INVALID_ROLE", line_no, "角色需为 R + 非负整数")
            emotion = parse_emotion(emotion_part, line_no) if emotion_part else Emotion()
            if emotion.mode == "vector" and len(emotion.vector) > 1 and not emotion.explicit_weight:
                warnings.append("SUM_OVER_0.8")
            raw_segments.append({
                "line": line_no,
                "role": int(match.group(1)),
                "emotion": emotion,
                "parts": [line[close + 1:]],
            })
            continue

        if line.lstrip(" \t\u3000").startswith("[@"):
            warnings.append("INDENT:%d" % line_no)
        elif line.startswith("\uff3b@"):
            warnings.append("FULLWIDTH:%d" % line_no)

        if raw_segments:
            raw_segments[-1]["parts"].append(line)
        else:
            preamble.append(line)

    segments: List[Segment] = []
    if preamble and any(item.strip() for item in preamble):
        segments.append(Segment(0, 1, 0, Emotion(), "\n".join(preamble)))

    for item in raw_segments:
        body = "\n".join(item["parts"])
        status = "ok"
        if not body.strip():
            if body:
                warnings.append("WHITESPACE_ONLY:%d" % item["line"])
            body = ""
            status = "empty"
        segments.append(Segment(len(segments), item["line"], item["role"], item["emotion"], body, status))

    if not segments:
        raise ParseError("EMPTY_TEXT", 1, "没有可合成内容")

    return {"segments": segments, "warnings": warnings}


def resolve_role(role: int, ref_audios_count: int, builtin_count: int = BUILTIN_ROLE_COUNT) -> Dict[str, Any]:
    """角色号 → 实际音色来源（用户参考音色 / 内置角色）。"""
    if role < ref_audios_count:
        return {"kind": "user", "index": role}
    return {"kind": "builtin", "index": role % builtin_count}


def normalize_ref_audios(value: Any) -> List[Any]:
    """把 ref_audios 输入归一化成一维数组（单个 / batch / list 都接受）。"""
    if value is None:
        return []
    if isinstance(value, dict):
        waveform = value.get("waveform")
        if waveform is None:
            return [value]
        batch = len(waveform)
        if batch <= 1:
            return [value]
        return [{"waveform": [waveform[i]]} for i in range(batch)]
    if isinstance(value, (list, tuple)):
        items: List[Any] = []
        for element in value:
            items.extend(normalize_ref_audios(element))
        return items
    return [value]
