"""字幕与时间轴：SRT / JSON，条数与段数一一对应。"""

import json

PLACEHOLDER_MS = 100
EMPTY_TEXT = "（空白段）"
FAILED_SUFFIX = "（未合成）"


def _timestamp(seconds):
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3600 * 1000)
    minutes, millis = divmod(millis, 60 * 1000)
    secs, millis = divmod(millis, 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, secs, millis)


def build_timeline(segments, durations_ms, gap_ms, intro_ms):
    """给每段算起止时间；空段/失败段用 0.1 秒占位。"""
    cues = []
    cursor = float(intro_ms)
    for index, segment in enumerate(segments):
        duration = durations_ms[index]
        if duration is None or duration <= 0:
            duration = PLACEHOLDER_MS
        start = cursor
        end = start + duration
        cues.append(
            {
                "index": index + 1,
                "start": start / 1000.0,
                "end": end / 1000.0,
                "role": segment.role,
                "status": segment.status,
                "text": segment.text,
            }
        )
        cursor = end + (gap_ms if index < len(segments) - 1 else 0)
    return cues


def to_srt(cues, failed_indexes=()):
    failed = set(failed_indexes)
    blocks = []
    for cue in cues:
        text = (cue["text"] or "").strip()
        if cue["status"] == "empty":
            text = EMPTY_TEXT
        elif cue["index"] in failed:
            text = (text or "") + FAILED_SUFFIX
        blocks.append(
            "%d\n%s --> %s\n%s\n" % (
                cue["index"],
                _timestamp(cue["start"]),
                _timestamp(cue["end"]),
                text,
            )
        )
    return "\n".join(blocks).rstrip() + "\n"


def to_json(cues, intro_ms, gap_ms, total_seconds, failed_indexes=(), voice_text=None):
    failed = set(failed_indexes)
    items = []
    for cue in cues:
        item = {
            "index": cue["index"],
            "start": round(cue["start"], 3),
            "end": round(cue["end"], 3),
            "role": cue["role"],
            "status": cue["status"] if cue["index"] not in failed else "failed",
            "text": (cue["text"] or "").strip(),
        }
        if cue["index"] in failed:
            item["error"] = True
        items.append(item)
    return json.dumps(
        {
            "intro_ms": intro_ms,
            "gap_ms": gap_ms,
            "total": round(total_seconds, 3),
            "segments": items,
        },
        ensure_ascii=False,
        indent=1,
    )
