"""剧本配音的编排层：解析 → 逐段合成 → 缓存 → 拼接 → 字幕与报告。"""

import dataclasses
import os
import time
from typing import Any, Dict, List, Optional

from . import audio, subtitles
from .cache import SegmentCache, fingerprint
from .errors import IndexTTSError
from .parser import BUILTIN_ROLE_COUNT, ParseError, parse_document
from .version import VERSION

DEFAULT_SAMPLE_RATE = 22050
PLACEHOLDER_MS = 100

STATUS_LABEL = {"ok": "ok", "empty": "empty", "failed": "failed"}
KIND_LABEL = {"user": "用户", "builtin": "内置"}
EMOTION_CN = {
    "happy": "开心",
    "angry": "愤怒",
    "sad": "悲伤",
    "afraid": "害怕",
    "disgusted": "厌恶",
    "melancholic": "低落",
    "surprised": "惊讶",
    "calm": "平静",
}


@dataclasses.dataclass
class SegmentResult:
    index: int
    role: int
    kind: str
    voice_index: int
    voice_name: str
    status: str
    pcm: bytes
    sample_rate: int
    duration_ms: Optional[int]
    text: str
    emotion: Any
    error: str = ""
    cached: bool = False


@dataclasses.dataclass
class Result:
    segments: List[SegmentResult]
    merged: bytes
    sample_rate: int
    subtitles: str
    segment_list: str
    voice_report: str
    failed_segments: str
    summary: str
    warnings: List[str]
    total_seconds: float


def _emotion_text(emotion):
    if emotion.mode == "follow":
        return "跟随"
    if emotion.mode == "vector":
        return "向量:" + "+".join("%s%g" % (EMOTION_CN.get(k, k), v) for k, v in emotion.vector.items())
    return "文本:" + emotion.text


def _ms(pcm, sample_rate):
    return int(round(len(pcm) / 2.0 / float(sample_rate) * 1000))


def _voice_key(voice, ref_paths):
    if voice["kind"] == "user":
        path = ref_paths[voice["index"]]
        stat = os.stat(path)
        return "user:%s:%d:%d" % (path, int(stat.st_mtime), int(stat.st_size))
    return "builtin:%d" % voice["index"]


def _file_name_for(path):
    return os.path.basename(path)


class ScriptDubbingService(object):
    def __init__(self, synthesizer, resolver, cache, on_progress=None):
        self.synthesizer = synthesizer
        self.resolver = resolver
        self.cache = cache
        self.on_progress = on_progress

    def run(
        self,
        text: str,
        ref_audios: Optional[List[str]] = None,
        seed: int = 1000,
        gap_ms: int = 300,
        intro_ms: int = 0,
        duration_factor: float = 1.0,
        emo_weight: float = 0.65,
        lang: str = "ZH",
        subtitle_format: str = "SRT",
    ) -> Result:
        ref_audios = list(ref_audios or [])
        started = time.time()
        try:
            parsed = parse_document(text, len(ref_audios))
        except ParseError as exc:
            raise IndexTTSError(exc.code, exc.message or "段标语法错误", "第 %d 行" % exc.line)
        segments = parsed["segments"]
        warnings = parsed["warnings"]

        results: List[SegmentResult] = []
        failed = []
        for index, segment in enumerate(segments):
            voice = self.resolver.resolve(segment.role, ref_audios)
            kind = voice["kind"]
            voice_index = voice["index"]
            if kind == "user":
                ref_path = ref_audios[voice_index]
                voice_name = _file_name_for(ref_path)
            else:
                ref_path = voice["path"]
                voice_name = _file_name_for(ref_path)

            self._report(index + 1, len(segments), "start", 0.0)

            if segment.status == "empty":
                pcm = audio.silence(DEFAULT_SAMPLE_RATE, PLACEHOLDER_MS)
                results.append(SegmentResult(index + 1, segment.role, kind, voice_index, voice_name,
                                             "empty", pcm, DEFAULT_SAMPLE_RATE, None, segment.text,
                                             segment.emotion))
                self._report(index + 1, len(segments), "done", 1.0)
                continue

            fp = fingerprint(segment.text, _voice_key(voice, ref_audios), segment.emotion.to_dict(),
                            duration_factor, emo_weight, lang)
            cached = self.cache.get(seed, index + 1, fp)
            if cached is not None:
                pcm, sample_rate = cached
                results.append(SegmentResult(index + 1, segment.role, kind, voice_index, voice_name,
                                             "ok", pcm, sample_rate, _ms(pcm, sample_rate), segment.text,
                                             segment.emotion, cached=True))
                self._report(index + 1, len(segments), "done", 1.0)
                continue

            try:
                pcm, sample_rate = self.synthesizer.synthesize(
                    segment.text,
                    ref_path,
                    segment.emotion,
                    duration_factor,
                    emo_weight=emo_weight,
                    lang=lang,
                    on_progress=lambda frac, desc, _i=index + 1: self._report(_i, len(segments), desc, frac),
                )
                self.cache.put(seed, index + 1, fp, pcm, sample_rate)
                results.append(SegmentResult(index + 1, segment.role, kind, voice_index, voice_name,
                                             "ok", pcm, sample_rate, _ms(pcm, sample_rate), segment.text,
                                             segment.emotion))
                self._report(index + 1, len(segments), "done", 1.0)
            except Exception as exc:  # noqa: BLE001
                message = getattr(exc, "message", None) or str(exc)
                failed.append(index + 1)
                placeholder = audio.silence(DEFAULT_SAMPLE_RATE, PLACEHOLDER_MS)
                results.append(SegmentResult(index + 1, segment.role, kind, voice_index, voice_name,
                                             "failed", placeholder, DEFAULT_SAMPLE_RATE, None, segment.text,
                                             segment.emotion, error=message))

        sample_rate = results[0].sample_rate if results else DEFAULT_SAMPLE_RATE
        merged_parts = []
        if intro_ms:
            merged_parts.append(audio.silence(sample_rate, intro_ms))
        for position, item in enumerate(results):
            if position:
                merged_parts.append(audio.silence(sample_rate, gap_ms))
            merged_parts.append(item.pcm)
        merged = b"".join(merged_parts)

        durations = [item.duration_ms for item in results]
        cues = subtitles.build_timeline(
            [type("S", (), {"role": r.role, "status": r.status, "text": r.text}) for r in results],
            durations,
            gap_ms,
            intro_ms,
        )
        total_seconds = len(merged) / 2.0 / float(sample_rate)
        if subtitle_format.upper() == "JSON":
            subtitle_text = subtitles.to_json(cues, intro_ms, gap_ms, total_seconds, failed,
                                              voice_text=self._voice_report(results, ref_audios))
        else:
            subtitle_text = subtitles.to_srt(cues, failed)

        return Result(
            segments=results,
            merged=merged,
            sample_rate=sample_rate,
            subtitles=subtitle_text,
            segment_list=self._segment_list(results),
            voice_report=self._voice_report(results, ref_audios),
            failed_segments=self._failed_report(results),
            summary=self._summary(results, failed, total_seconds, time.time() - started)
            + " | 缓存 %s" % (self.cache.seed_dir(seed)),
            warnings=warnings,
            total_seconds=total_seconds,
        )

    def _report(self, index, total, status, sub=None):
        if self.on_progress:
            self.on_progress(index, total, status, sub)

    # ------------------------------------------------------------------ 报告
    @staticmethod
    def _segment_list(results):
        lines = []
        for item in results:
            line = "#%d [R%d %s] %s %s %s" % (
                item.index,
                item.role,
                KIND_LABEL.get(item.kind, item.kind),
                STATUS_LABEL.get(item.status, item.status),
                _emotion_text(item.emotion),
                (item.text or "").replace("\n", " / "),
            )
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _voice_report(results, ref_audios):
        groups = {}
        for item in results:
            key = (item.role, item.kind, item.voice_index, item.voice_name)
            groups.setdefault(key, []).append(item.index)
        lines = []
        for (role, kind, voice_index, voice_name), indexes in sorted(groups.items()):
            if kind == "user":
                desc = "用户 ref_audios[%d]（%s）" % (voice_index, voice_name)
            else:
                desc = "内置 %s" % voice_name
                if role != voice_index or role >= BUILTIN_ROLE_COUNT:
                    desc += "（越界 %d %% %d）" % (role, BUILTIN_ROLE_COUNT)
            lines.append("R%d = %s → 段 %s" % (role, desc, "、".join(str(i) for i in indexes)))
        return "\n".join(lines)

    @staticmethod
    def _failed_report(results):
        lines = []
        for item in results:
            if item.status != "failed":
                continue
            lines.append(
                "段 %d | R%d %s | %s | %s\n  原文：%s\n  错误：%s"
                % (
                    item.index,
                    item.role,
                    item.kind,
                    item.voice_name,
                    _emotion_text(item.emotion),
                    item.text,
                    item.error,
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _summary(results, failed, total_seconds, elapsed):
        user = len({(r.role) for r in results if r.kind == "user"})
        builtin = len({(r.role) for r in results if r.kind == "builtin"})
        rollover = len({r.role for r in results if r.kind == "builtin" and (r.role != r.voice_index or r.role >= BUILTIN_ROLE_COUNT)})
        rtf = (elapsed / total_seconds) if total_seconds else 0.0
        return "v%s | %d 段 | %.1fs | 用户音色 %d 个 · 内置 %d 个（含 %d 个越界）| 耗时 %.1fs | RTF %.2f | 失败 %d 段" % (
            VERSION,
            len(results),
            total_seconds,
            user,
            builtin,
            rollover,
            elapsed,
            rtf,
            len(failed),
        )
