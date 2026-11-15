"""错误类型与中文提示。

约定（沿用 Comfy-DeepSeekAPI 的做法）：所有对外错误都抛 IndexTTSError，
message 是给用户看的中文短句，hint 是可执行的建议，ComfyUI 会把它们显示在节点上。
"""

DEFAULT_START_HINT = (
    "在 index-tts 仓库执行 bash outputs/bin/run_webui_3060.sh --daemon"
    "（首次启动约 45-50 秒）"
)


class IndexTTSError(RuntimeError):
    """节点层唯一需要捕获的异常类型。"""

    def __init__(self, code, message, hint=None, retryable=False):
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = retryable
        super().__init__(message if not hint else message + "；" + hint)


def connect_error(base_url, exc=None):
    return IndexTTSError(
        "connect",
        "连不上 IndexTTS 服务：%s" % base_url,
        DEFAULT_START_HINT,
        retryable=True,
    )


def timeout_error(base_url, seconds):
    return IndexTTSError(
        "timeout",
        "等待合成超时（%d 秒）：%s" % (int(seconds), base_url),
        "调大 timeout，或把长文拆成多行用「按行分段」",
    )


def server_error(detail, base_url=""):
    """服务端 process_completed.success=false 时，output.error 里通常有原文。"""
    text = (detail or "").strip()
    return IndexTTSError(
        "server_error",
        "合成失败：%s" % (text[:400] if text else "服务端未返回原因"),
        "常见原因：参考音频太短/太长、文本为空、显存不足；日志在 index-tts/outputs/logs/",
    )


def not_indextts(base_url):
    return IndexTTSError(
        "not_found",
        "这个服务不是 IndexTTS WebUI，或版本太旧：%s" % base_url,
        "确认端口对、跑的是 webui.py；需要带 /gen_single 端点的 Gradio 4/5",
    )


def missing_ref():
    return IndexTTSError(
        "no_voice",
        "没有参考音频：接一个 AUDIO，或在音色库放 wav",
        "3-10 秒干声效果最好",
    )


def empty_text():
    return IndexTTSError("empty_text", "text 为空：请填写要合成的文本")


def bad_audio(detail):
    return IndexTTSError(
        "bad_audio",
        "返回的音频无法解析（%s）" % (detail or "未知格式"),
        "请附上这条信息反馈 issue",
    )


def no_qwen_emotion():
    return IndexTTSError(
        "no_qwen_emotion",
        "这一段用了文本情绪，但服务端没有加载 QwenEmotion",
        "用 --qwen_emo 重启 WebUI；或把情绪改成标签（如 开心0.8）/ 去掉情绪",
    )
