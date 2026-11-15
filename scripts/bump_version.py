#!/usr/bin/env python3
"""升版本号：同步 core/version.py 与 pyproject.toml，并在 CHANGELOG 顶部插入条目。

用法：
    python3 scripts/bump_version.py 1.0.2 "banner 双语、字体兜底"
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/bump_version.py <新版本号> [变更说明]")
        return 2
    version = sys.argv[1].strip()
    note = sys.argv[2].strip() if len(sys.argv) > 2 else "（待补充）"

    version_file = ROOT / "core" / "version.py"
    version_file.write_text(
        '"""单一版本号来源（构建脚本与测试都读它）。"""' + chr(10) + chr(10) +
        'VERSION = "%s"' % version + chr(10),
        encoding="utf-8",
    )

    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("version = "):
            lines.append('version = "%s"' % version)
        else:
            lines.append(line)
    pyproject.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")

    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    entry = "## %s" % version + chr(10) + chr(10) + "- " + note + chr(10) + chr(10)
    marker = "## "
    index = text.find(marker)
    if index == -1:
        text = text + chr(10) + entry
    else:
        text = text[:index] + entry + text[index:]
    changelog.write_text(text, encoding="utf-8")

    print("版本已更新为 %s" % version)
    print("下一步：python3 tests/run_tests.py && comfy node validate && comfy node pack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
