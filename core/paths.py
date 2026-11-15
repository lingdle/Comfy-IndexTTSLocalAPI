"""缓存目录解析：永远是 ComfyUI output 目录下的子目录。

规则（0.8.0）：
- cache_dir 只是 output 下的**相对子目录名**，可以是多级（a/b）
- 绝对路径、盘符、~、.. 都会被规整，最终一定仍在 output 之下
- 留空 = indextts-cache
- 拿不到 output 目录时（非 ComfyUI 环境）退到系统临时目录
"""

import os
import pathlib
import re
import tempfile

DEFAULT_SUBDIR = "indextts-cache"


def _subdir_parts(value):
    """把用户输入规整成不含锚点的相对路径片段。"""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return []
    text = os.path.expanduser(text)
    text = re.sub(r"^[A-Za-z]:", "", text)      # 去掉盘符
    return [part for part in text.split("/") if part not in ("", ".", "..")]


def resolve_cache_root(subdir="", output_dir=None):
    """返回 <output>/<subdir>；output 不可用时用临时目录兜底。"""
    base = pathlib.Path(os.path.abspath(str(output_dir))) if output_dir else pathlib.Path(tempfile.gettempdir())
    parts = _subdir_parts(subdir) or [DEFAULT_SUBDIR]
    return (base.joinpath(*parts)).resolve()


def display_subdir(subdir=""):
    """给界面看：把用户输入规整成子目录形式。"""
    parts = _subdir_parts(subdir) or [DEFAULT_SUBDIR]
    return "/".join(parts)
