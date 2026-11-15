"""角色音色解析：用户参考音色（ref_audios）→ 内置角色（builtin）。

规则（见 draft/段标规范.md §4）：
- R0 = ref_audios[0]，R1 = ref_audios[1]…
- 越界 → 内置 audios[n % 10]
- 内置 R0 随包；R1–R9 首次用到时从 Release 下载
"""

import hashlib
import os
import pathlib
import zipfile

BUILTIN_ROLE_COUNT = 10
BUILTIN_FILES = [
    "voice_02.wav",  # R0 · 女声（随包）
    "voice_12.wav",  # R1 · 男声（随包）
    "voice_01.wav",
    "voice_03.wav",
    "voice_04.wav",
    "voice_05.wav",
    "voice_06.wav",
    "voice_07.wav",
    "voice_08.wav",
    "voice_09.wav",
]

# 随包发布的角色（其余按需下载）
BUNDLED_ROLES = (0, 1)

PACKAGE_DIR = pathlib.Path(__file__).resolve().parents[1]
BUNDLED_DIR = PACKAGE_DIR / "voices"


class VoiceUnavailable(RuntimeError):
    """内置音色既没下载成功、也不在包内。"""


def default_cache_dir():
    override = os.environ.get("ITTS_VOICE_DIR")
    if override:
        return pathlib.Path(override)
    try:
        import folder_paths  # noqa: F401  (仅 ComfyUI 环境存在)

        return pathlib.Path(folder_paths.models_dir) / "indextts" / "voices"
    except Exception:  # noqa: BLE001
        return PACKAGE_DIR / "voices" / "_cache"


def bundled_path(index):
    name = BUILTIN_FILES[index % BUILTIN_ROLE_COUNT]
    return BUNDLED_DIR / name


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class VoiceResolver(object):
    """把角色号解析成实际音频文件。"""

    def __init__(self, cache_dir=None, downloader=None):
        self.cache_dir = pathlib.Path(cache_dir) if cache_dir else default_cache_dir()
        self.downloader = downloader
        self._downloaded = False
        self._warned = False

    def _cached(self, index):
        path = self.cache_dir / BUILTIN_FILES[index % BUILTIN_ROLE_COUNT]
        return path if path.exists() else None

    def _ensure_builtin(self, index):
        index = index % BUILTIN_ROLE_COUNT
        cached = self._cached(index)
        if cached:
            return cached
        if index in BUNDLED_ROLES:
            bundled = bundled_path(index)
            if bundled.exists():
                return bundled
        if not self._downloaded and self.downloader is not None:
            self._downloaded = True
            try:
                self.downloader(self.cache_dir)
            except Exception:  # noqa: BLE001
                self.downloader = None
            cached = self._cached(index)
            if cached:
                return cached
        bundled = bundled_path(0)
        if bundled.exists():
            self._warned = True
            return bundled
        raise VoiceUnavailable("内置角色 %d 不可用，且没有 R0 兜底" % index)

    def resolve(self, role, ref_audios=None):
        """返回 {"kind": "user"|"builtin", "index": int, "path": str, "degraded": bool}。"""
        ref_audios = ref_audios or []
        if role < len(ref_audios):
            return {"kind": "user", "index": role, "path": None, "degraded": False}
        index = role % BUILTIN_ROLE_COUNT
        return {
            "kind": "builtin",
            "index": index,
            "path": str(self._ensure_builtin(index)),
            "degraded": self._warned,
        }


def download_builtin_archive(cache_dir, url, sha256=None):
    """下载内置音色包并解压（R1–R9）。失败抛异常，由调用方降级。"""
    import requests

    cache_dir = pathlib.Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / "_download.zip"
    response = requests.get(url, timeout=120, stream=True)
    response.raise_for_status()
    with open(target, "wb") as handle:
        for chunk in response.iter_content(1024 * 256):
            handle.write(chunk)
    if sha256 and sha256_of(target).lower() != sha256.lower():
        target.unlink(missing_ok=True)
        raise RuntimeError("内置音色包校验失败")
    with zipfile.ZipFile(target) as archive:
        for member in archive.namelist():
            name = os.path.basename(member)
            if name in BUILTIN_FILES:
                with archive.open(member) as src, open(cache_dir / name, "wb") as dst:
                    dst.write(src.read())
    target.unlink(missing_ok=True)
