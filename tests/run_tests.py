"""剧本配音测试：解析器用例 + 编排层（假合成器）。"""

import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import audio, subtitles  # noqa: E402
from core.cache import SegmentCache, fingerprint  # noqa: E402
from core.parser import ParseError, normalize_ref_audios, parse_document, resolve_role  # noqa: E402
from core.service import ScriptDubbingService  # noqa: E402

CASES = pathlib.Path(__file__).resolve().parent / "fixtures" / "cases.json"
SR = 22050


class FakeSynth(object):
    def __init__(self, fail_calls=()):
        self.calls = []
        self.fail_calls = set(fail_calls)
        self.sr = SR

    def synthesize(self, text, ref_path, emotion, duration_factor, on_progress=None, **kwargs):
        self.calls.append({"text": text, "ref": ref_path, "emotion": emotion.to_dict()})
        if on_progress:
            on_progress(0.5, "halfway")
        if len(self.calls) in self.fail_calls:
            raise RuntimeError("合成失败：显存不足")
        return b"\x01\x00" * int(self.sr * 0.5), self.sr


class FakeResolver(object):
    def resolve(self, role, ref_audios=None):
        ref_audios = ref_audios or []
        if role < len(ref_audios):
            return {"kind": "user", "index": role, "path": ref_audios[role], "degraded": False}
        index = role % 10
        return {"kind": "builtin", "index": index, "path": "voice_%02d.wav" % (index + 1), "degraded": False}


def make_service(tmp, fail_calls=()):
    synth = FakeSynth(fail_calls)
    cache = SegmentCache(pathlib.Path(tmp) / "cache")
    service = ScriptDubbingService(synth, FakeResolver(), cache)
    return service, synth


def ref_files(tmp, count):
    paths = []
    for index in range(count):
        path = pathlib.Path(tmp) / ("ref%d.wav" % index)
        path.write_bytes(b"RIFF")
        paths.append(str(path))
    return paths


# ---------------------------------------------------------------- 解析器用例
def test_parser_cases():
    data = json.loads(CASES.read_text(encoding="utf-8"))
    fake = {
        "none": None,
        "single": {"waveform": [[[0.0]]]},
        "batch3": {"waveform": [[[0.0]], [[0.0]], [[0.0]]]},
        "list2": [{"waveform": [[[0.0]]]}, {"waveform": [[[0.0]]]}],
        "empty": [],
    }
    failures = []
    for case in data["cases"]:
        cid = case["id"]
        expect = case["expect"]
        try:
            if case["group"] == "J":
                got = normalize_ref_audios(fake[case["input"]])
                if len(got) != expect["len"]:
                    failures.append("%s len %d != %d" % (cid, len(got), expect["len"]))
                continue
            result = parse_document(case["text"], case.get("ref_audios", 0))
            want = expect.get("segments", [])
            if len(result["segments"]) != len(want):
                failures.append("%s 段数 %d != %d" % (cid, len(result["segments"]), len(want)))
                continue
            for got, exp in zip(result["segments"], want):
                if got.role != exp["role"] or got.text != exp["text"] or got.emotion.to_dict() != exp["emotion"]:
                    failures.append("%s segment mismatch" % cid)
                    break
            else:
                if result["warnings"] != expect.get("warnings", []):
                    failures.append("%s warnings %r" % (cid, result["warnings"]))
                if "voice" in expect:
                    voice = resolve_role(want[0]["role"], case.get("ref_audios", 0))
                    if voice != expect["voice"]:
                        failures.append("%s voice %r" % (cid, voice))
        except ParseError as exc:
            err = expect.get("error")
            if not err or exc.code != err["code"] or exc.line != err["line"]:
                failures.append("%s 意外错误 %s" % (cid, exc))
    assert not failures, failures


# ---------------------------------------------------------------- 编排层
def test_all_success_merge():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        result = service.run("[@R0] 你好\n[@R1] 世界", ref_files(tmp, 2), gap_ms=300)
        assert len(result.segments) == 2
        assert [s.status for s in result.segments] == ["ok", "ok"]
        assert len(synth.calls) == 2
        expected = int(SR * 0.5) * 2 * 2 + int(SR * 0.3) * 2
        assert len(result.merged) == expected
        assert result.subtitles.count("-->") == 2
        assert "用户 ref_audios[0]" in result.voice_report


def test_failure_placeholder_and_report():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp, fail_calls=(1,))
        result = service.run("[@R0] 第一段\n[@R1] 第二段", ref_files(tmp, 2))
        assert [s.status for s in result.segments] == ["failed", "ok"]
        assert len(result.segments) == 2
        assert result.segments[0].duration_ms is None
        assert "未合成" in result.subtitles
        assert "段 1" in result.failed_segments
        assert "显存不足" in result.failed_segments
        assert "失败 1 段" in result.summary


def test_empty_segment_is_placeholder():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        result = service.run("[@R0]\n[@R1] 有字", ref_files(tmp, 2))
        assert len(synth.calls) == 1
        assert result.segments[0].status == "empty"
        assert result.segments[0].duration_ms is None
        assert "空白段" in result.subtitles


def test_cache_hit_and_seed_isolation():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        refs = ref_files(tmp, 1)
        service.run("[@R0] 你好", refs, seed=1000)
        assert len(synth.calls) == 1
        service.run("[@R0] 你好", refs, seed=1000)
        assert len(synth.calls) == 1, "同 seed 应命中缓存"
        service.run("[@R0] 你好", refs, seed=1001)
        assert len(synth.calls) == 2, "换 seed 应重新请求"


def test_text_change_only_regenerates_that_segment():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        refs = ref_files(tmp, 1)
        service.run("[@R0] 甲\n[@R0] 乙", refs, seed=1)
        assert len(synth.calls) == 2
        service.run("[@R0] 甲\n[@R0] 丙", refs, seed=1)
        assert len(synth.calls) == 3, "只有改动的那段重算"


def test_intro_and_json_subtitles():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        result = service.run("[@R0] 你好", ref_files(tmp, 1), intro_ms=1500, subtitle_format="JSON")
        data = json.loads(result.subtitles)
        assert data["intro_ms"] == 1500
        assert data["segments"][0]["start"] == 1.5
        assert data["segments"][0]["status"] == "ok"


def test_srt_timestamp_format():
    cues = [
        {"index": 1, "start": 0.0, "end": 4.671, "role": 0, "status": "ok", "text": "甲"},
    ]
    text = subtitles.to_srt(cues)
    assert "00:00:00,000 --> 00:00:04,671" in text


def test_voice_rollover_reported():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        result = service.run("[@R13] 你好", ref_audios=[], seed=1000)
        assert "越界 13 % 10" in result.voice_report
        assert "内置" in result.voice_report


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for func in tests:
        try:
            func()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %s" % (func.__name__, exc))
        else:
            print("ok   %s" % func.__name__)
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0




# ---------------------------------------------------------------- 节点 / i18n
PKG_NAME = "indextts_script_dubbing"


def _load_package():
    import importlib.util
    import types

    class _Type(object):
        def __init__(self, kind):
            self.kind = kind

        def Input(self, ident, **kwargs):
            record = {"type": self.kind, "id": ident}
            record.update(kwargs)
            return record

        def Output(self, ident=None, **kwargs):
            record = {"type": self.kind, "id": ident}
            record.update(kwargs)
            return record

    class Schema(object):
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __getattr__(self, item):
            return self.kwargs[item]

    class NodeOutput(object):
        def __init__(self, *args):
            self.args = args

    io_module = types.SimpleNamespace(
        String=_Type("STRING"),
        Int=_Type("INT"),
        Float=_Type("FLOAT"),
        Boolean=_Type("BOOLEAN"),
        Combo=_Type("COMBO"),
        Audio=_Type("AUDIO"),
        Schema=Schema,
        NodeOutput=NodeOutput,
        ComfyNode=object,
        UploadType=types.SimpleNamespace(audio="audio"),
        Autogrow=types.SimpleNamespace(
            TemplatePrefix=lambda input, prefix, min, max: {"input": input, "prefix": prefix, "min": min, "max": max},
            Input=lambda ident, template, **kwargs: dict({"type": "AUTOGROW", "id": ident, "template": template}, **kwargs),
        ),
        ControlAfterGenerate=types.SimpleNamespace(fixed="fixed"),
        Hidden=types.SimpleNamespace(prompt="prompt", extra_pnginfo="extra_pnginfo"),
        FolderType=types.SimpleNamespace(temp="temp", output="output", input="input"),
    )
    latest_ui = types.SimpleNamespace(
        AudioSaveHelper=types.SimpleNamespace(save_audio=lambda *a, **k: []),
        SavedAudios=lambda results: None,
    )
    comfy_api = types.ModuleType("comfy_api")
    latest = types.ModuleType("comfy_api.latest")
    latest.io = io_module
    latest.ui = latest_ui
    latest.ComfyExtension = object
    comfy_api.latest = latest
    sys.modules["comfy_api"] = comfy_api
    sys.modules["comfy_api.latest"] = latest

    spec = importlib.util.spec_from_file_location(
        PKG_NAME, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = package
    spec.loader.exec_module(package)
    return package


NODE_ID = "IndexTTSLocalScriptDubbing"
EXPECTED_INPUTS = ["text", "ref_audio", "lang", "gap_ms", "intro_ms", "subtitle_format", "seed", "emo_weight", "duration_factor", "cache_dir", "base_url"]
EXPECTED_OUTPUTS = 7


def _schema():
    package = _load_package()
    return package.ScriptDubbingNode.define_schema()


def test_node_schema():
    schema = _schema()
    assert schema.node_id == NODE_ID
    assert schema.display_name == "剧本配音"
    assert schema.category == "IndexTTSLocalAPI"
    assert [item["id"] for item in schema.inputs] == EXPECTED_INPUTS
    assert len(schema.outputs) == EXPECTED_OUTPUTS
    assert schema.outputs[0]["is_output_list"] is True, "segment_audios 必须是列表输出"
    assert not schema.outputs[1].get("is_output_list"), "merged_audio 是单条"
    by_id = {item["id"]: item for item in schema.inputs}
    advanced = [item["id"] for item in schema.inputs if item.get("advanced")]
    assert advanced == ["duration_factor", "cache_dir", "base_url"]
    assert by_id["emo_weight"]["default"] == 0.65
    assert by_id["seed"]["default"] == 1000
    assert by_id["seed"]["control_after_generate"] == "fixed", "seed 默认必须是 fixed"


def test_locale_coverage_and_order():
    schema = _schema()
    for lang in ("zh", "en"):
        data = json.loads((ROOT / "locales" / lang / "nodeDefs.json").read_text(encoding="utf-8"))
        assert NODE_ID in data, lang
        entry = data[NODE_ID]
        assert entry["display_name"] and entry["description"], lang
        assert list(entry["inputs"]) == EXPECTED_INPUTS, lang
        for item in schema.inputs:
            slot = entry["inputs"][item["id"]]
            assert slot["name"] == item["id"], "%s/%s name" % (lang, item["id"])
            assert slot["tooltip"], "%s/%s tooltip" % (lang, item["id"])
        for index in range(EXPECTED_OUTPUTS):
            assert entry["outputs"][str(index)]["tooltip"], "%s output %d" % (lang, index)


def test_source_strings_are_monolingual():
    schema = _schema()
    assert "\n" not in schema.description
    for item in schema.inputs:
        assert "\n" not in (item.get("tooltip") or ""), item["id"]
    for item in schema.outputs:
        assert "\n" not in (item.get("tooltip") or ""), item.get("id")


# ---------------------------------------------------------------- 内置音色解析（I 组）
def test_voice_resolver_cache_hit_skips_download():
    from core.voices import VoiceResolver

    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = pathlib.Path(tmp)
        from core.voices import BUILTIN_FILES
        (cache_dir / BUILTIN_FILES[5]).write_bytes(b"RIFF")
        calls = []
        resolver = VoiceResolver(cache_dir=cache_dir, downloader=lambda d: calls.append(d))
        voice = resolver.resolve(5, [])
        assert voice["kind"] == "builtin" and voice["index"] == 5
        assert voice["path"].endswith(BUILTIN_FILES[5])
        assert not calls, "缓存命中不应触发下载"


def test_voice_resolver_downloads_once():
    from core.voices import BUILTIN_FILES, VoiceResolver

    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = pathlib.Path(tmp)
        calls = []

        def downloader(target):
            calls.append(target)
            (pathlib.Path(target) / BUILTIN_FILES[3]).write_bytes(b"RIFF")

        resolver = VoiceResolver(cache_dir=cache_dir, downloader=downloader)
        voice = resolver.resolve(3, [])
        assert voice["path"].endswith(BUILTIN_FILES[3])
        resolver.resolve(4, [])
        assert len(calls) == 1, "整个任务只下载一次"


def test_voice_resolver_falls_back_to_bundled_r0():
    from core.voices import VoiceResolver, bundled_path

    with tempfile.TemporaryDirectory() as tmp:
        def broken(target):
            raise RuntimeError("network down")

        resolver = VoiceResolver(cache_dir=pathlib.Path(tmp), downloader=broken)
        voice = resolver.resolve(7, [])
        assert voice["kind"] == "builtin"
        assert pathlib.Path(voice["path"]) == bundled_path(0)
        assert voice["degraded"] is True


def test_user_audio_wins_over_builtin():
    from core.voices import VoiceResolver

    with tempfile.TemporaryDirectory() as tmp:
        resolver = VoiceResolver(cache_dir=pathlib.Path(tmp))
        voice = resolver.resolve(1, ["a.wav", "b.wav"])
        assert voice["kind"] == "user" and voice["index"] == 1 and voice["path"] is None


def test_default_script_is_valid():
    schema = _schema()
    text_input = [item for item in schema.inputs if item["id"] == "text"][0]
    default = text_input["default"]
    assert default and "[@R1" in default and "[@R0" in default
    parsed = parse_document(default, 0)
    assert len(parsed["segments"]) == 17
    assert parsed["warnings"] == ["SUM_OVER_0.8"]


def test_bundled_roles_skip_download():
    from core.voices import VoiceResolver, bundled_path

    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        resolver = VoiceResolver(cache_dir=pathlib.Path(tmp), downloader=lambda d: calls.append(d))
        for role in (0, 1):
            voice = resolver.resolve(role, [])
            assert pathlib.Path(voice["path"]) == bundled_path(role)
        assert not calls, "R0/R1 随包，不应触发下载"


def test_upload_returns_file_data_with_meta():
    from core.transport import GradioTransport

    class Response(object):
        status_code = 200

        def json(self):
            return [{"path": "/tmp/gradio/abc/voice-1234.wav", "url": "http://x/file=y"}]

    class Session(object):
        trust_env = False

        def post(self, *args, **kwargs):
            return Response()

    with tempfile.TemporaryDirectory() as tmp:
        local = pathlib.Path(tmp) / "ref.wav"
        local.write_bytes(b"RIFF")
        transport = GradioTransport("http://127.0.0.1:7860", session=Session())
        transport._config = {"api_prefix": "/gradio_api"}
        result = transport.upload(str(local))
        assert isinstance(result, dict)
        assert result["path"].endswith(".wav")
        assert result["meta"] == {"_type": "gradio.FileData"}


def test_subtitle_text_is_stripped():
    cues = [
        {"index": 1, "start": 0.0, "end": 1.0, "role": 0, "status": "ok", "text": " 你好"},
        {"index": 2, "start": 1.0, "end": 2.0, "role": 1, "status": "ok", "text": "\n第二句\n"},
    ]
    text = subtitles.to_srt(cues)
    assert "你好" in text and " 你好" not in text
    assert "第二句" in text
    assert all(not line.startswith(" ") for line in text.splitlines() if line)
    data = json.loads(subtitles.to_json(cues, 0, 300, 2.0))
    assert data["segments"][0]["text"] == "你好"


def test_version_is_consistent():
    import re

    core_text = (ROOT / "core" / "version.py").read_text(encoding="utf-8")
    version = re.search(r'VERSION = "([^"]+)"', core_text).group(1)
    init_text = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "__version__ = VERSION" in init_text
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert version == declared, (version, declared)
    assert "## " + version in changelog, version


def test_progress_reports_monotonic():
    with tempfile.TemporaryDirectory() as tmp:
        synth = FakeSynth()
        reports = []
        service = ScriptDubbingService(
            synth, FakeResolver(), SegmentCache(pathlib.Path(tmp) / "cache"),
            on_progress=lambda index, total, status, sub: reports.append((index, total, status, sub)),
        )
        service.run("[@R0] 甲\n[@R1] 乙", ref_files(tmp, 2))
        starts = [r for r in reports if r[2] == "start"]
        dones = [r for r in reports if r[2] == "done"]
        assert len(starts) == 2 and len(dones) == 2
        assert starts[0][0] == 1 and starts[1][0] == 2
        assert all(r[1] == 2 for r in reports)
        assert ("halfway", 0.5) in [(r[2], r[3]) for r in reports]


def test_cache_root_stays_under_output():
    from core.paths import resolve_cache_root

    out = "/tmp/out"
    assert str(resolve_cache_root("", out)) == "/tmp/out/indextts-cache"
    assert str(resolve_cache_root("mycache", out)) == "/tmp/out/mycache"
    assert str(resolve_cache_root("a/b", out)) == "/tmp/out/a/b"
    assert str(resolve_cache_root("/abs/path", out)) == "/tmp/out/abs/path"
    assert str(resolve_cache_root("D:/tts/cache", out)) == "/tmp/out/tts/cache"
    assert str(resolve_cache_root("../escape", out)) == "/tmp/out/escape"
    assert str(resolve_cache_root("~/x", out)).startswith("/tmp/out/")


def test_segment_list_has_rows():
    with tempfile.TemporaryDirectory() as tmp:
        service, synth = make_service(tmp)
        result = service.run("[@R0] 甲\n[@R1] 乙", ref_files(tmp, 2))
        rows = result.segment_list.strip().splitlines()
        assert len(rows) == 2, result.segment_list
        assert rows[0].startswith("#1 [R0 用户]")
        assert "甲" in rows[0] and "乙" in rows[1]


def test_synthesizer_payload_uses_webui_weight():
    import io as _io

    from core.parser import Emotion
    from core.synthesizer import EMO_WEIGHT, IndexTTSSynthesizer

    spec = {
        "parameters": [
            {"parameter_name": "emo_control_method", "parameter_default": "same",
             "type": {"enum": ["same", "audio", "vector", "text"]}},
            {"parameter_name": "prompt", "parameter_default": None},
            {"parameter_name": "text", "parameter_default": None},
            {"parameter_name": "emo_weight", "parameter_default": 0.65},
            {"parameter_name": "vec1", "parameter_default": 0.0},
            {"parameter_name": "duration_factor", "parameter_default": 1.0},
        ]
    }

    class FakeTransport(object):
        def __init__(self):
            self.data = None

        def tts_spec(self):
            return spec

        def fn_index(self, api_name=None):
            return 21

        def upload(self, path):
            return {"path": "/tmp/x.wav", "meta": {"_type": "gradio.FileData"}}

        def run(self, fn_index, data, session_hash=None, on_progress=None):
            self.data = data
            return [{"path": "/tmp/out.wav"}]

        def first_file(self, data):
            return "/tmp/out.wav"

        def download(self, target):
            pcm = b"\x00\x00" * 100
            return __import__("core.audio", fromlist=["x"]).to_wav(pcm, 22050)

    with tempfile.TemporaryDirectory() as tmp:
        ref = pathlib.Path(tmp) / "ref.wav"
        ref.write_bytes(b"RIFF")
        transport = FakeTransport()
        synth = IndexTTSSynthesizer(transport)
        synth.synthesize("你好", str(ref), Emotion(mode="vector", vector={"happy": 0.8}), 1.0)
        values = dict(zip([p["parameter_name"] for p in spec["parameters"]], transport.data))
        assert values["emo_control_method"] == "vector"
        assert values["vec1"] == 0.8
        assert values["emo_weight"] == EMO_WEIGHT == 0.65, values["emo_weight"]


def test_emo_weight_affects_fingerprint():
    from core.cache import fingerprint

    a = fingerprint("x", "v", "follow", 1.0, 0.65)
    b = fingerprint("x", "v", "follow", 1.0, 0.5)
    assert a != b, "改 emo_weight 必须让缓存失效"


def test_synthesizer_passes_lang():
    from core.parser import Emotion
    from core.synthesizer import IndexTTSSynthesizer

    spec = {"parameters": [
        {"parameter_name": "emo_control_method", "parameter_default": "same", "type": {"enum": ["same", "audio", "vector", "text"]}},
        {"parameter_name": "prompt", "parameter_default": None},
        {"parameter_name": "text", "parameter_default": None},
        {"parameter_name": "emo_weight", "parameter_default": 0.65},
        {"parameter_name": "duration_factor", "parameter_default": 1.0},
        {"parameter_name": "lang_choice", "parameter_default": "ZH"},
    ]}

    class FakeTransport(object):
        def __init__(self):
            self.data = None

        def tts_spec(self):
            return spec

        def fn_index(self, api_name=None):
            return 21

        def upload(self, path):
            return {"path": "/tmp/x.wav", "meta": {"_type": "gradio.FileData"}}

        def run(self, fn_index, data, session_hash=None, on_progress=None):
            self.data = data
            return [{"path": "/tmp/out.wav"}]

        def first_file(self, data):
            return "/tmp/out.wav"

        def download(self, target):
            from core import audio

            return audio.to_wav(b"\x00\x00" * 10, 22050)

    with tempfile.TemporaryDirectory() as tmp:
        ref = pathlib.Path(tmp) / "ref.wav"
        ref.write_bytes(b"RIFF")
        transport = FakeTransport()
        IndexTTSSynthesizer(transport).synthesize(
            "hello", str(ref), Emotion(), 1.0, lang="EN")
        values = dict(zip([p["parameter_name"] for p in spec["parameters"]], transport.data))
        assert values["lang_choice"] == "EN", values


def test_example_workflow_matches_schema():
    workflow = json.loads((ROOT / "example" / "workflows" / "Comfy-IndexTTSLocalAPI.json").read_text(encoding="utf-8"))
    node = next(n for n in workflow["nodes"] if n["type"] == "IndexTTSLocalScriptDubbing")
    schema = _schema()

    names = [item["name"] for item in node["inputs"]]
    slots = [n for n in names if n.startswith("ref_audio.")]
    others = [n for n in names if not n.startswith("ref_audio.")]
    assert slots == ["ref_audio.ref_audio_%d" % i for i in range(5)], slots
    assert others == [item["id"] for item in schema.inputs if item["id"] != "ref_audio"], others

    values = node["widgets_values"]
    assert values[0].startswith("夜色沉下来")
    assert values[1:6] == ["ZH", 300, 0, "SRT", 1000]
    assert values[6] == "fixed"
    assert values[7] == 0.65
    assert values[8] == 1
    assert values[9] == "indextts-cache"
    assert values[10].startswith("http")

    assert [o["name"] for o in node["outputs"]] == [
        "segment_audios", "merged_audio", "subtitles", "segment_list",
        "voice_report", "failed_segments", "summary",
    ]

if __name__ == "__main__":
    raise SystemExit(main())
