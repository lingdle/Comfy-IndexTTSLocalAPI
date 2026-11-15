"""剧本配音 · ComfyUI 节点（IndexTTSLocalScriptDubbing）。"""

import os
import tempfile
import wave

from comfy_api.latest import io

from .core import audio as audio_util
from .core.cache import SegmentCache
from .core.paths import DEFAULT_SUBDIR, resolve_cache_root
from .core.service import ScriptDubbingService
from .core.synthesizer import IndexTTSSynthesizer
from .core.transport import GradioTransport
from .core.voices import VoiceResolver, download_builtin_archive

DEFAULT_BASE_URL = "http://127.0.0.1:7860"

DEFAULT_SCRIPT = """夜色沉下来，街灯一盏一盏亮起。故事从这里开始。

[@R0] 这一行没有情绪字段，情绪跟随参考音色。

[@R0:] 冒号后面留空，效果和上一行完全一样。

[@R0:跟随] 显式写「跟随」，同样不改情绪。

[@R0:开心] 单个情绪标签，权重默认满值。

[@R0:开心0.7] 同一个标签带上权重，情绪会淡一些。

[@R0:愤怒0.6+悲伤0.3] 两个标签叠在一起，先怒后悲。

[@R0:惊讶+害怕] 两个标签都不带权重，各按满值处理。

[@R0:happy] 英文标签和中文标签等价。

[@R0:happy0.8+surprised0.2] 中英混写也支持，仍按标签解析。

[@R0:发狂嘶吼] 这一行是自由描述，交给服务端的情感模型解析。

[@R0:委屈巴巴，快哭了] 描述可以带标点，整句都会被当作情绪文本。

[@r1] 角色号大小写不敏感，这一行和 [@R1] 相同。

[@R01:平静0.8] 前导零会被忽略，R01 就是 R1。

[@R2]
段落可以跨行：从段标开始，
一直到下一个段标之前，都算同一段，
中间有多少换行都不会断开。

[@R9:惊讶] 角色号越界时按「n 对 10 取模」找内置角色。

[@R13:厌恶0.5] 十三对十取模等于三，所以实际用的是内置第 4 个角色。

这一行里出现了 [@R0] 但不在行首，所以它只是普通文字，会被念出来。"""


# ComfyUI 前端会给名为 seed 的 INT 自动加「随机化」下拉，且默认 randomize。
# 新版 V3 支持指定默认值（ControlAfterGenerate.fixed），老版本退回 False。
_CONTROL_AFTER_GENERATE = getattr(io, "ControlAfterGenerate", None)
SEED_CONTROL = _CONTROL_AFTER_GENERATE.fixed if _CONTROL_AFTER_GENERATE else False


def _make_progress_bar(total):
    """ComfyUI 进度条；非 ComfyUI 环境（单测）返回 None。"""
    try:
        from comfy.utils import ProgressBar

        return ProgressBar(total)
    except Exception:  # noqa: BLE001
        return None


def _progress_sink():
    """新版 ComfyUI 的进度接口：ProgressRegistry（2.0 协议，progress_state 事件）。"""
    try:
        from comfy_execution.progress import get_progress_state
        from comfy_execution.utils import get_executing_context

        registry = get_progress_state()
        context = get_executing_context()
        node_id = getattr(context, "node_id", None) if context is not None else None
        if registry is None or node_id is None:
            return None

        def sink(value, maximum):
            registry.update_progress(node_id, value, maximum)

        return sink
    except Exception:  # noqa: BLE001
        return None


def _progress_reporter():
    state = {"bar": None, "sink": False}

    def report(index, total, status, sub=None):
        if not total:
            return
        fraction = (index - 1 + (sub if sub is not None else 0.0)) / float(total)
        fraction = max(0.0, min(1.0, fraction))

        if state["sink"] is False:
            state["sink"] = _progress_sink()

        sink = state["sink"]
        if sink is not None:
            try:
                sink(fraction * 100.0, 100.0)
                return
            except Exception:  # noqa: BLE001
                state["sink"] = None

        # 老版本兜底：comfy.utils.ProgressBar（依赖 PROGRESS_BAR_HOOK）
        if state["bar"] is None:
            state["bar"] = _make_progress_bar(100)
        bar = state["bar"]
        if bar is None:
            return
        try:
            if hasattr(bar, "update_absolute"):
                bar.update_absolute(int(round(fraction * 100)), 100)
            else:
                bar.update(1)
        except Exception:  # noqa: BLE001
            pass

    return report


def _comfy_output():
    """ComfyUI 的输出目录（绝对路径；受 --base-directory / --output-directory 控制）。"""
    try:
        import folder_paths

        return os.path.abspath(folder_paths.get_output_directory())
    except Exception:  # noqa: BLE001
        return None


def _default_cache_dir():
    """面板里显示的子目录名（相对 output）。"""
    return DEFAULT_SUBDIR


def _output_root(custom=""):
    return str(resolve_cache_root(custom, _comfy_output()))


def _audio_to_wav(audio, directory):
    """ComfyUI AUDIO -> 临时 wav 路径。"""
    waveform = audio["waveform"]
    sample_rate = int(audio.get("sample_rate") or 22050)
    if getattr(waveform, "ndim", 0) == 3:
        waveform = waveform[0]
    if getattr(waveform, "ndim", 0) == 2:
        waveform = waveform[0]
    samples = (waveform.detach().cpu().numpy() * 32767.0).astype("int16").tobytes()
    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=directory)
    with wave.open(handle.name, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(samples)
    handle.close()
    return handle.name


def _pcm_to_audio(pcm, sample_rate):
    import numpy
    import torch

    samples = numpy.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    return {"waveform": torch.from_numpy(samples).reshape(1, 1, -1), "sample_rate": int(sample_rate)}


class ScriptDubbingNode(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="IndexTTSLocalScriptDubbing",
            display_name="剧本配音",
            category="IndexTTSLocalAPI",
            description=(
                "一段带段标的剧本 → 多角色、多情绪配音 + 精确字幕。"
                "段标写作 [@R0]、[@R1:发狂嘶吼]，必须顶格、只在行首生效。"
            ),
            search_aliases=["IndexTTS", "剧本配音", "dubbing", "tts", "段标", "多角色"],
            inputs=[
                io.String.Input(
                    "text",
                    multiline=True,
                    default=DEFAULT_SCRIPT,
                    tooltip="带段标的剧本；默认是一段两角色示例。为空会报错。段标写法：[@R0]、[@R1:发狂嘶吼]",
                ),
                io.Autogrow.Input(
                    "ref_audio",
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input("audio"),
                        prefix="ref_audio_",
                        min=0,
                        max=8,
                    ),
                    tooltip="参考音色插口：第 1 个 = R0，第 2 个 = R1…；不接的槽位走内置角色",
                ),
                io.Combo.Input(
                    "lang",
                    options=["ZH", "EN", "JA", "ES", "AR"],
                    default="ZH",
                    tooltip="语种：决定分词与发音词典（不是翻译）。中英混排的稿子请选 ZH",
                ),
                io.Int.Input("gap_ms", default=300, min=0, max=2000, step=10, tooltip="合并时两段之间插入的静音毫秒数"),
                io.Int.Input("intro_ms", default=0, min=0, max=5000, step=10, tooltip="合并轨最前面插入的静音毫秒数"),
                io.Combo.Input("subtitle_format", options=["SRT", "JSON"], default="SRT", tooltip="字幕输出格式"),
                io.Int.Input("seed", default=1000, min=0, max=2147483647, control_after_generate=SEED_CONTROL, tooltip="版本号：同一 seed 复用缓存文件，换 seed 则全部重新合成"),
                io.Float.Input(
                    "emo_weight",
                    default=0.65,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    tooltip="情绪权重（emo_alpha）：默认 0.65，与 WebUI 一致；实际强度 = 写的权重 × 上游偏置 × 该值",
                ),
                io.Float.Input(
                    "duration_factor",
                    default=1.0,
                    min=0.5,
                    max=2.0,
                    step=0.05,
                    advanced=True,
                    tooltip="语速：0.5 更快更短，2.0 更慢更长；改动会让所有段重新合成",
                ),
                io.String.Input(
                    "cache_dir",
                    default=_default_cache_dir(),
                    advanced=True,
                    tooltip="output 目录下的子目录名（可多级，如 my/tts）；绝对路径会被规整，最终一定在 ComfyUI 输出目录之下",
                ),
                io.String.Input(
                    "base_url",
                    default=DEFAULT_BASE_URL,
                    advanced=True,
                    tooltip="IndexTTS WebUI 地址；只有端口不是 7860 时才需要改",
                ),
            ],
            outputs=[
                io.Audio.Output("segment_audios", display_name="segment_audios", is_output_list=True, tooltip="分段配音：每段一条的列表（长度 = 段数，空段/失败段为 0.1 秒静音）；下游会按段逐个执行"),
                io.Audio.Output("merged_audio", display_name="merged_audio", tooltip="合成配音：片头静音 + 各段 + 段间静音"),
                io.String.Output("subtitles", display_name="subtitles", tooltip="字幕：SRT 或 JSON，条数 = 段数，失败段占位"),
                io.String.Output("segment_list", display_name="segment_list", tooltip="分段明细：序号 / 状态 / 角色 / 情绪 / 起止 / 文本"),
                io.String.Output("voice_report", display_name="voice_report", tooltip="音色报告：每个角色实际用了用户的还是内置的"),
                io.String.Output("failed_segments", display_name="failed_segments", tooltip="失败段清单：段号 / 原文 / 服务端错误；全部成功时为空"),
                io.String.Output("summary", display_name="summary", tooltip="概要：段数 / 成功 / 失败 / 总时长 / 耗时 / RTF"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        """把版本号并进缓存键：升级后旧缓存自动失效，避免读到旧输出。"""
        from .core.version import VERSION

        return VERSION

    @classmethod
    def execute(cls, text, ref_audio=None, lang="ZH", gap_ms=300, intro_ms=0, subtitle_format="SRT", seed=1000,
                emo_weight=0.65, duration_factor=1.0, cache_dir="", base_url=DEFAULT_BASE_URL):
        workdir = tempfile.mkdtemp(prefix="indextts-")
        try:
            slots = ref_audio or {}
            if isinstance(slots, (list, tuple)):
                slots = {"ref_audio_%d" % i: item for i, item in enumerate(slots)}
            ref_paths = []
            for name in sorted(slots):
                audio = slots[name]
                if audio:
                    ref_paths.append(_audio_to_wav(audio, workdir))

            transport = GradioTransport(base_url)

            resolver = VoiceResolver()
            if resolver.downloader is None:
                resolver.downloader = _default_downloader()
            service = ScriptDubbingService(
                IndexTTSSynthesizer(transport),
                resolver,
                SegmentCache(_output_root(cache_dir)),
                on_progress=_progress_reporter(),
            )
            result = service.run(
                text=text,
                ref_audios=ref_paths,
                seed=seed,
                gap_ms=gap_ms,
                intro_ms=intro_ms,
                duration_factor=duration_factor,
                emo_weight=emo_weight,
                lang=lang,
                subtitle_format=subtitle_format,
            )
            segment_audios = [_pcm_to_audio(item.pcm, item.sample_rate) for item in result.segments]
            merged = _pcm_to_audio(result.merged, result.sample_rate)
            return io.NodeOutput(
                segment_audios,
                merged,
                result.subtitles,
                result.segment_list,
                result.voice_report,
                result.failed_segments,
                result.summary,
            )
        finally:
            for path in ref_paths if "ref_paths" in dir() else []:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _default_downloader():
    """内置音色下载：清单在 voices/manifest.yaml，缺失时静默跳过（退回 R0）。"""
    import json
    import pathlib

    manifest_path = pathlib.Path(__file__).resolve().parent / "voices" / "manifest.json"
    if not manifest_path.exists():
        return None

    def download(cache_dir):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        archive = manifest.get("archive") or {}
        download_builtin_archive(cache_dir, archive["url"], archive.get("sha256"))

    return download
