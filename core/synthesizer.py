"""把一段文本 + 一个参考音色 + 一种情绪，合成成 PCM（唯一出网点）。"""

import uuid

from . import audio, payload
from .errors import IndexTTSError, no_qwen_emotion, server_error

EMOTION_KEYS = ("happy", "angry", "sad", "afraid", "disgusted", "melancholic", "surprised", "calm")

# 与 WebUI 界面默认值保持一致（界面滑块默认 0.65）
EMO_WEIGHT = 0.65


class IndexTTSSynthesizer(object):
    def __init__(self, transport):
        self.transport = transport
        self._spec = None
        self._uploads = {}

    # ------------------------------------------------------------------ 基础
    def spec(self):
        if self._spec is None:
            self._spec = self.transport.tts_spec()
        return self._spec

    def labels(self):
        labels = payload.emotion_labels(self.spec())
        if len(labels) < 3:
            raise IndexTTSError("bad_service", "该服务没有情绪控制参数", "确认是 IndexTTS-2.5 的 webui.py")
        return labels

    def _upload(self, path):
        stat = __import__("os").stat(path)
        key = (str(path), int(stat.st_mtime), int(stat.st_size))
        if key not in self._uploads:
            self._uploads[key] = self.transport.upload(path)
        return self._uploads[key]

    # ------------------------------------------------------------------ 合成
    def synthesize(self, text, ref_path, emotion, duration_factor, session_hash=None, on_progress=None,
                   emo_weight=EMO_WEIGHT, lang="ZH"):
        """返回 (pcm16 单声道, sample_rate)。"""
        spec = self.spec()
        labels = self.labels()
        values = {
            "text": text,
            "prompt": self._upload(ref_path),
            "duration_factor": duration_factor,
            "lang_choice": lang,
        }
        session = session_hash or uuid.uuid4().hex

        if emotion.mode == "vector":
            values["emo_control_method"] = labels[2]
            for index, key in enumerate(EMOTION_KEYS, start=1):
                values["vec%d" % index] = float(emotion.vector.get(key, 0.0))
            values["emo_weight"] = emo_weight
        elif emotion.mode == "text":
            updated = self.transport.enable_experimental(session, labels[0]) or []
            if len(updated) < 4:
                raise no_qwen_emotion()
            labels = updated
            values["emo_control_method"] = labels[3]
            values["emo_text"] = emotion.text
            values["emo_weight"] = emo_weight
        else:
            values["emo_control_method"] = labels[0]
            values["emo_weight"] = emo_weight

        data = payload.build_payload(spec, values)
        try:
            result = self.transport.run(
                self.transport.fn_index(), data, session_hash=session, on_progress=on_progress
            )
        except IndexTTSError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise server_error(str(exc))
        target = self.transport.first_file(result)
        if not target:
            raise server_error("服务端没有返回音频文件")
        wav = self.transport.download(target)
        return audio.read_wav(wav)
