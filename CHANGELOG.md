# Changelog

版本规则：每次改动都升版本号。修 bug / 文案 → patch；行为或默认值变化 → minor；破坏兼容 → major。

## 1.0.1

- Registry DisplayName 改为 `Comfy-IndexTTSLocalAPI`（1.0.0 发布时仍是「剧本配音 · Script Dubbing」，而版本号不可覆盖，只能发新版本）

## 1.0.0 — 首个公开版本

**节点**
- `剧本配音`（`IndexTTSLocalScriptDubbing`）：一份带段标的剧本 → 多角色、多情绪配音 + 段级精确字幕
- `lang` 支持 ZH / EN / JA / ES / AR

**段标语法**
- `[@Rn]` / `[@Rn:情绪]`：必须顶格、只在行首生效、跨行成段
- 情绪支持 8 维标签（中英别名、可带权重、可 + 组合）、自由描述（QwenEmotion）、跟随音色
- 详见 `syntax-reference.md` / `语法速查手册.md` / `example-script.md`

**执行与缓存**
- 一段一次请求、严格串行；按 (seed + 内容指纹) 缓存到 `output/indextts-cache/<seed>/`
- 失败段跳过 + 0.1 秒占位，所有输出按段索引对齐；`failed_segments` 给出完整原文与服务端错误

**输入 / 输出**
- 输入 11 个：text、ref_audio（Autogrow）、lang、gap_ms、intro_ms、subtitle_format、seed、emo_weight、duration_factor、cache_dir、base_url
- 输出 7 个：segment_audios、merged_audio、subtitles、segment_list、voice_report、failed_segments、summary

**内置音色**
- R0 女声、R1 男声随包；R2–R9 首次使用时从 Release `voices-v1` 下载（sha256 校验）

**其它**
- 中英双语 i18n（`locales/`）、示例工作流、赞助小节
- Registry DisplayName 使用包名 `Comfy-IndexTTSLocalAPI`

## 0.17.2

- 内置音色包已发布：GitHub Release `voices-v1` 提供 `indextts-voices-8.zip`（8 个音色，4.77 MB）
- `voices/manifest.json` 填入真实下载地址与 sha256，R2–R9 现在可以自动下载

## 0.17.1

- 新增示例工作流 `example_workflows/Comfy-IndexTTSLocalAPI.json` 与截图，README 增加 Example 小节
- 新增测试：示例工作流的节点/输入/控件值必须与 schema 一致

## 0.17.0

- `text` 默认值换成覆盖全部语法的 17 段样例（与 example-script.md 一致）

## 0.16.0

- 新增输入 `lang`（ZH / EN / JA / ES / AR，默认 ZH）：决定分词与发音词典，随请求传给服务端
- `lang` 参与缓存指纹

## 0.15.4

- 新增 `example-script.md`：覆盖全部段标语法的样例剧本（17 段）与对照表

## 0.15.3

- 新增英文版语法速查 `syntax-reference.md`，README 中英分区各自链接

## 0.15.2

- README 增加 Sponsor 小节（支付宝 / 微信收款码）

## 0.15.1

- README 改为参考 Comfy-DeepSeekAPI 的极简双语风格
- 新增 `语法速查手册.md`：段标、角色、情绪标签、权重、错误码、常见问题

## 0.15.0

- 新增输入 `emo_weight`（0–1，默认 0.65）：情绪权重 emo_alpha，与 WebUI 默认一致，面板可调
- `emo_weight` 参与缓存指纹：改了它会重新合成

## 0.14.3

- `emo_weight` 改为 **0.65**，与 WebUI 界面默认一致（原来是 1.0）
- 注意：这意味着段标里写的权重会被放大前先乘 0.65，例如 `[@R0:开心0.8]` 实际生效 0.52
- 新增合成器 payload 测试，锁定 emo_weight / vec / emo_control_method

## 0.14.2

- 节点加入 `fingerprint_inputs`：版本号参与 ComfyUI 缓存键，升级后不会再读到旧缓存

## 0.14.1

- 修复 `segment_list` 输出为空：拼好的行没有 append 进列表，函数永远返回空串

## 0.14.0

- 输入 `ref_audios` 改为 **`ref_audio`（Autogrow 插口）**：默认 1 个，可加到最多 8 个，第 1 个 = R0、第 2 个 = R1…
- 每个插口接一个内置 `LoadAudio`（上传与播放器用内置节点，不再自己做）

## 0.13.0

- **移除** 多音频上传节点（`IndexTTSLocalAudioUploadList`）：固定槽位仍无法稳定提供上传/播放控件
- 剧本配音节点回退 `is_input_list`，恢复单音频输入（`ref_audios` 仍可按数组传入）

## 0.12.0

- 多音频上传改为**固定 4 个槽位**：`audio_1..audio_4`，每个都是 `Combo.Input(upload=UploadType.audio)`，带上传按钮与播放器
- 原因：Autogrow 会把 widget 输入强制变成连线插口（源码 `force_input=True`），无法提供上传/播放控件

## 0.11.0

- 新增节点 `多音频上传`（`IndexTTSLocalAudioUploadList`）：Autogrow 槽位，每个槽位一个上传控件与播放器，输出 AUDIO 列表
- 剧本配音节点改为 `is_input_list=True`，可以接收这个列表（自动解包标量输入）

## 0.10.0

- **移除** 预览分段配音节点（`IndexTTSLocalPreviewAudioList`）：ComfyUI 的音频预览控件是单播放器，多段一起显示无法可靠实现
- 建议用法：听整体接 `merged_audio` → 内置 `PreviewAudio`；要每段文件接 `segment_audios` → `SaveAudio`（会按段存 N 个）

## 0.9.6

- 预览节点改为与内置 PreviewAudio 相同形态：单 AUDIO 输入、不声明 is_input_list，靠 ComfyUI 按段逐个执行
- 以 (prompt_id, node_id) 累积各段临时文件，最后一次执行把所有结果一起交给前端

## 0.9.5

- 预览节点补上 `hidden=[prompt, extra_pnginfo]`（与内置 PreviewAudio 一致，AudioSaveHelper 需要 cls.hidden）
- 预览保存失败不再抛异常，而是把失败原因写进 summary，节点照常完成

## 0.9.4

- 修复进度条一直为 0：新版 ComfyUI 不再设置 `comfy.utils.PROGRESS_BAR_HOOK`，改为直接调用 `comfy_execution.progress.get_progress_state().update_progress()`（progress_state 协议），旧版再退回 ProgressBar

## 0.9.3

- 修复预览节点不执行：V3 schema 需要 `is_output_node=True` 才会被当作输出节点执行（否则只有连到别的输出节点才会跑）

## 0.9.2

- 预览节点新增 AUDIO 透传输出（与内置 PreviewAudio 一致），并保留 summary 输出
- UI 走 `SavedAudios`，缺该类型时退回 V1 风格 `{"audio": [...]}`

## 0.9.1

- 修复预览节点：`FolderType` 在 `comfy_api.latest.io` 里，不在 `ui` 里；改为自动探测两个模块
- 保存逻辑抽成 `_save_audio`，缺少 `AudioSaveHelper` 时给出明确错误

## 0.9.0

- 新增节点 `预览分段配音`（`IndexTTSLocalPreviewAudioList`）：接 `segment_audios`，把每段存成临时 flac 一起预览，并输出每段时长清单
- 使用 V3 的 `ui.SavedAudios` + `AudioSaveHelper`（临时目录，不污染 output）

## 0.8.1

- 修复：`segment_audios` 未声明 `is_output_list=True`，ComfyUI 会把整个列表当成一个音频数据，导致下游行为异常、与 `merged_audio` 对不上
- 现在下游节点会按段逐个执行（`SaveAudio` 会存 N 个文件）

## 0.8.0

- `cache_dir` 语义改为：**ComfyUI output 目录下的相对子目录**（可多级），绝对路径/盘符/.. 都会被规整，缓存永远不跑出 output
- 面板默认值改为子目录名 `indextts-cache`（不再是绝对路径）
- 移除 `ITTS_CACHE_DIR` 环境变量（与“永远在 output 下”冲突）

## 0.7.1

- `cache_dir` 默认值改为**绝对路径**（`os.path.abspath` 包一层），自定义/环境变量路径也统一转绝对
- 说明：ComfyUI 没有 base 目录环境变量，权威来源是 `folder_paths.get_output_directory()`（受 `--base-directory` / `--output-directory` 控制）

## 0.7.0

- `cache_dir` 默认值改为**实际绝对路径**（ComfyUI 输出目录下的 `indextts-cache`），面板上直接可见
- 清空该字段时回落到环境变量 `ITTS_CACHE_DIR`，再回落默认路径

## 0.6.0

- 默认缓存目录改为 `ComfyUI/output/indextts-cache/`（原来是 `indextts/`）
- `summary` 末尾追加实际缓存路径，跑完就能看到文件在哪

## 0.5.0

- 新增 Advanced 参数 `cache_dir`：自定义分段缓存目录；留空走 ComfyUI 输出目录，也支持环境变量 `ITTS_CACHE_DIR`
- 优先级：参数 > 环境变量 > ComfyUI output/indextts > 临时目录

## 0.4.0

- 修复：`seed` 不再默认随机化。ComfyUI 前端会给名叫 seed 的 INT 自动加「随机化」下拉，现在显式设为 `ControlAfterGenerate.fixed`（老版本自动退回 False）
- 默认值仍是 1000：不点随机、不改数字时，重复运行会命中缓存，不会再无故重算

## 0.3.0

- 新增：节点接上 ComfyUI 进度条——按段推进，并把每段内部的 gradio progress 映射到该段的区间
- 缓存命中段与空段也会立即报告完成，进度不会卡住
- 非 ComfyUI 环境（单测）自动降级为无进度条

## 0.2.0

- **默认剧本**换成「介绍 IndexTTSLocalAPI」的 6 行 / 5 段示例，只使用标签情绪，不依赖 QwenEmotion
- **内置音色改为随包一男一女**：R0 = voice_02.wav（女，F0≈279Hz），R1 = voice_12.wav（男，F0≈104Hz）；R2–R9 首次使用时下载
- 修复：上传的 FileData 现在带 `meta: {"_type": "gradio.FileData"}`（Gradio 5 拒收裸路径，之前每次请求都会被预处理拦下）
- 修复：字幕文本去掉前导/尾随空白（只影响展示，不影响合成）
- 新增测试：`test_bundled_roles_skip_download`、`test_upload_returns_file_data_with_meta`、`test_subtitle_text_is_stripped`、`test_default_script_is_valid`
- 真机验证：默认剧本 5 段 / 28.8 秒 / 0 失败；同 seed 二次执行 0 秒（全部命中缓存）

## 0.1.0

- 首个版本：节点 `IndexTTSLocalScriptDubbing`（剧本配音 / Script Dubbing）
- 段标 `[@Rn]` / `[@Rn:情绪]`：角色由参考音色定义，情绪支持标签与自由描述
- 按段磁盘缓存（seed + 内容指纹）；一段一次请求、串行执行
- 输出：`segment_audios`、`merged_audio`、`subtitles`（SRT/JSON）、`segment_list`、`voice_report`、`failed_segments`、`summary`
- 失败跳过 + 0.1s 占位，索引对齐不跳号
- i18n：`locales/zh|en/nodeDefs.json`
