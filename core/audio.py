"""WAV 处理：只用标准库（wave + array），核心层不依赖 numpy/torch。"""

import array
import io
import sys
import wave

from .errors import bad_audio

_NEED_BYTESWAP = sys.byteorder == "big"


def read_wav(data):
    """WAV 字节 -> (pcm16 单声道 bytes, sample_rate)。

    支持 8/16/24/32-bit PCM；立体声会降混成单声道。非 PCM 直接报错。
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            sampwidth = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frames = handle.getnframes()
            raw = handle.readframes(frames)
    except Exception as exc:
        raise bad_audio(str(exc))

    samples = _to_s16(raw, sampwidth)
    if channels > 1:
        samples = _mix_down(samples, channels)
    return samples.tobytes(), sample_rate


def _to_s16(raw, sampwidth):
    """把任意位深的 PCM 转成 int16 样本数组。"""
    if sampwidth == 2:
        out = array.array("h")
        out.frombytes(raw)
        if _NEED_BYTESWAP:
            out.byteswap()
        return out

    if sampwidth == 1:  # 8-bit 是无符号的，按偏移 128 处理
        return array.array("h", [(byte - 128) << 8 for byte in bytearray(raw)])

    if sampwidth == 3:  # 24-bit：取高 16 位
        return array.array(
            "h",
            [
                (raw[i + 1] | (raw[i + 2] << 8))
                for i in range(0, len(raw) - 2, 3)
            ],
        )

    if sampwidth == 4:  # 32-bit：取高 16 位
        return array.array(
            "h",
            [(raw[i + 2] | (raw[i + 3] << 8)) for i in range(0, len(raw) - 3, 4)],
        )

    raise bad_audio("不支持的采样位宽：%d 字节" % sampwidth)


def _mix_down(samples, channels):
    """多声道求均值 -> 单声道，避免削波。"""
    total = len(samples) - (len(samples) % channels)
    out = array.array("h", bytes(2 * (total // channels)))
    for index in range(total // channels):
        start = index * channels
        out[index] = int(sum(samples[start:start + channels]) / channels)
    return out


def silence(sample_rate, gap_ms):
    """生成 gap_ms 毫秒的静音 PCM（16-bit 单声道）。"""
    samples = int(int(sample_rate) * max(0, int(gap_ms)) / 1000)
    return b"\x00\x00" * samples


def merge(segments, sample_rate, gap_ms):
    """把多段 PCM 用静音拼接起来。"""
    silence_bytes = silence(sample_rate, gap_ms)
    parts = []
    for index, segment in enumerate(segments):
        if index and silence_bytes:
            parts.append(silence_bytes)
        parts.append(segment)
    return b"".join(parts)


def to_wav(pcm, sample_rate):
    """PCM（16-bit 单声道）-> WAV 字节。"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm)
    return buffer.getvalue()


def duration(pcm, sample_rate):
    """PCM 时长（秒）。"""
    if not sample_rate:
        return 0.0
    return len(pcm) / 2.0 / float(sample_rate)
