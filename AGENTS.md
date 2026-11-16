# AGENTS

本仓库是 ComfyUI 自定义节点包 **Comfy-IndexTTSLocalAPI**，提供节点「剧本配音 / Script Dubbing」：
把一份带段标的剧本交给本地 IndexTTS WebUI，合成多角色、多情绪的配音，并输出段级字幕。

## 必读

| 文档 | 内容 |
|---|---|
| [README.md](README.md) | 安装、用法、示例工作流、赞助 |
| [语法速查手册.md](语法速查手册.md) / [syntax-reference.md](syntax-reference.md) | 段标语法、情绪标签、错误码、FAQ |
| [example-script.md](example-script.md) | 覆盖全部语法的 17 段样例剧本 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史与版本规则 |
| [docs/director-prompt.md](docs/director-prompt.md) | 给 Agent 的导演系统提示词 |
| `draft/`（未入库） | 设计讨论、服务端参数清单、术语表 |

**命名唯一依据是 `draft/术语表.md`**：新增名词先入表再使用，禁止临时起名。

## 常用命令（仓库根目录）

    python3 tests/run_tests.py                       # 单元测试，必须全绿
    python3 scripts/bump_version.py 1.0.x "变更说明"  # 升版本号（version.py / pyproject / CHANGELOG）
    comfy node validate                              # 发布前校验
    comfy node pack                                  # 打包 node.zip（按 .comfyignore 过滤）

## 开发约定

- **不改 index-tts**：只通过它的 WebUI HTTP 接口（`queue/join` + `queue/data`）调用，仓库内没有任何三方库改动
- **每次提交必须升版本号**：用 `scripts/bump_version.py`；版本一致性由 `test_version_is_consistent` 强制
- **命名**：节点 ID `IndexTTSLocalScriptDubbing` 固定不变；输入/输出标签就是英文 ID；新增字段先进术语表
- **i18n**：`locales/{zh,en}/nodeDefs.json`，输入的 `name` 必须等于 id，顺序与 schema 一致
- **测试**：`tests/run_tests.py` 覆盖解析、编排、缓存、i18n、示例工作流；改 schema 必须同步改示例工作流
- **缓存**：`output/indextts-cache/<seed>/seg{NNN}_{指纹}.wav`；内容、`emo_weight`、`lang` 或版本变化即失效

## 发布流程

1. `python3 scripts/bump_version.py <版本> "<变更>"`，跑 `tests/run_tests.py`
2. `comfy node validate` → `comfy node pack`
3. 提交、打 tag、推到 GitHub（本机 `git push` 会卡住，用 `draft/push_via_api.py` 走 GitHub API）
4. 维护者执行 `comfy node publish --changelog "..."`；**版本号发布后不可修改**

## 环境

- 本地 IndexTTS WebUI：`~/aigcspace/index-tts`，启动 `bash outputs/bin/run_webui_3060.sh --daemon`
- 实测版本：index-tts `v2.5.0-11-gd9e41aa`，Gradio `5.45.0`
- 内置音色：R0 女声、R1 男声随包；R2–R9 从 Release `voices-v1` 下载
