"""段级磁盘缓存：<output>/indextts/<seed>/seg{NNN}_{指纹}.wav"""

import hashlib
import json
import pathlib

from . import audio

PLACEHOLDER_MS = 100


def fingerprint(text, voice_key, emotion, duration_factor, emo_weight=0.65, lang="ZH"):
    """内容指纹：文本 / 音色 / 情绪 / 语速 变了就换文件名。"""
    payload = json.dumps(
        {
            "text": text,
            "voice": voice_key,
            "emotion": emotion,
            "duration_factor": round(float(duration_factor), 4),
            "emo_weight": round(float(emo_weight), 4),
            "lang": lang,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def file_name(index, fp):
    return "seg%03d_%s.wav" % (index, fp)


class SegmentCache(object):
    def __init__(self, root):
        self.root = pathlib.Path(root)

    def seed_dir(self, seed):
        return self.root / str(int(seed))

    def path(self, seed, index, fp):
        return self.seed_dir(seed) / file_name(index, fp)

    def get(self, seed, index, fp):
        path = self.path(seed, index, fp)
        if not path.exists():
            return None
        try:
            return audio.read_wav(path.read_bytes())
        except Exception:  # noqa: BLE001
            return None

    def put(self, seed, index, fp, pcm, sample_rate):
        path = self.path(seed, index, fp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio.to_wav(pcm, sample_rate))
        return path
