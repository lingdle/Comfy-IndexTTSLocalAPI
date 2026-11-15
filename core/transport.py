"""Gradio 协议客户端（唯一出网点）。

走「有会话」路径：queue/join + queue/data。只有这条路径能拿到
  - 文本情感（模式 3，需要同 session 先开实验开关）
  - 真进度（progress 0->1 + speech synthesis i/N）
  - 错误原文（process_completed.success=false 时的 output.error）
  - 取消入口（POST /cancel）

无状态 /call/{api} 留作降级时再补，v1 不用。
"""

import json
import os
import uuid

import requests

from .errors import IndexTTSError, connect_error, not_indextts, server_error

CHUNK = 1024 * 64


class GradioTransport(object):
    def __init__(self, base_url, connect_timeout=5.0, read_timeout=300.0, session=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, read_timeout)
        self.session = session if session is not None else requests.Session()
        # WSL 的 NO_PROXY 里常有 [::1]，httpx/requests 会误用代理；本地服务一律不走代理
        self.session.trust_env = False
        self._config = None
        self._endpoint = None

    # ------------------------------------------------------------------ 基础请求
    def _abs(self, path):
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return self.base_url + path

    def _get_json(self, path):
        try:
            response = self.session.get(self._abs(path), timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise connect_error(self.base_url)
        except requests.exceptions.RequestException:
            raise connect_error(self.base_url)
        if response.status_code == 404:
            raise not_indextts(self.base_url)
        if response.status_code != 200:
            raise server_error(response.text, self.base_url)
        try:
            return response.json()
        except ValueError:
            raise not_indextts(self.base_url)

    # ------------------------------------------------------------------ 元信息
    def config(self, refresh=False):
        if self._config is None or refresh:
            self._config = self._get_json("/config")
        return self._config

    @property
    def prefix(self):
        return (self.config().get("api_prefix") or "").rstrip("/")

    def title(self):
        return self.config().get("title") or ""

    def dependencies(self):
        """api_name -> fn_index（/config 里的 api_name 没有前导斜杠）。"""
        deps = self.config().get("dependencies") or []
        return dict((d.get("api_name"), d.get("id")) for d in deps if d.get("api_name"))

    def api_info(self):
        return self._get_json(self.prefix + "/info")

    def endpoints(self):
        return (self.api_info().get("named_endpoints") or {})

    def tts_endpoint(self):
        if self._endpoint:
            return self._endpoint
        endpoints = self.endpoints()
        if "/gen_single" in endpoints:
            self._endpoint = "/gen_single"
            return self._endpoint
        for name, spec in endpoints.items():
            names = set(item.get("parameter_name") for item in spec.get("parameters") or [])
            if {"text", "prompt", "emo_control_method"} <= names:
                self._endpoint = name
                return name
        raise not_indextts(self.base_url)

    def tts_spec(self):
        return self.endpoints()[self.tts_endpoint()]

    def fn_index(self, api_name=None):
        name = (api_name or self.tts_endpoint()).lstrip("/")
        mapping = self.dependencies()
        if name not in mapping:
            raise not_indextts(self.base_url)
        return mapping[name]

    # ------------------------------------------------------------------ 文件
    def upload(self, local_path):
        name = "voice-%s.wav" % uuid.uuid4().hex[:8]  # 避免中文文件名
        try:
            with open(local_path, "rb") as handle:
                response = self.session.post(
                    self._abs(self.prefix + "/upload"),
                    params={"upload_id": uuid.uuid4().hex},
                    files={"files": (name, handle, "audio/wav")},
                    timeout=self.timeout,
                )
        except (requests.exceptions.RequestException, OSError):
            raise connect_error(self.base_url)
        if response.status_code != 200:
            raise server_error(response.text, self.base_url)
        try:
            uploaded = response.json()
        except ValueError:
            raise server_error("上传返回不是 JSON", self.base_url)
        if isinstance(uploaded, list) and uploaded:
            uploaded = uploaded[0]
        if isinstance(uploaded, str):
            path = uploaded
        elif isinstance(uploaded, dict):
            path = uploaded.get("path") or uploaded.get("name")
        else:
            raise server_error("上传返回格式异常", self.base_url)
        if not path:
            raise server_error("上传返回里没有文件路径", self.base_url)
        # gradio 5 的 FileData 必须显式带 meta，否则 pydantic 直接拒收
        return self.file_data(path)

    def download(self, target):
        """target 可以是服务器绝对路径，也可以是 gradio 给的完整 url。"""
        if target.startswith("http://") or target.startswith("https://"):
            url = target
        else:
            url = self.base_url + self.prefix + "/file=" + target
        try:
            response = self.session.get(url, timeout=self.timeout)
        except (requests.exceptions.RequestException, OSError):
            raise connect_error(self.base_url)
        if response.status_code != 200:
            raise server_error("取音频失败（HTTP %s）" % response.status_code, self.base_url)
        return response.content

    # ------------------------------------------------------------------ 调用
    def start(self, fn_index, data, session_hash):
        payload = {"data": data, "fn_index": fn_index, "session_hash": session_hash}
        try:
            response = self.session.post(
                self._abs(self.prefix + "/queue/join"), json=payload, timeout=self.timeout
            )
        except requests.exceptions.Timeout:
            raise connect_error(self.base_url)
        except requests.exceptions.RequestException:
            raise connect_error(self.base_url)
        if response.status_code != 200:
            raise server_error(response.text, self.base_url)
        try:
            event_id = response.json().get("event_id")
        except ValueError:
            raise not_indextts(self.base_url)
        if not event_id:
            raise not_indextts(self.base_url)
        return event_id

    def wait(self, event_id, session_hash, on_progress=None, interrupt_check=None):
        """读 queue/data 的 SSE，按 event_id 过滤，直到拿到结果。"""
        url = self._abs(self.prefix + "/queue/data")
        try:
            streaming = self.session.get(
                url, params={"session_hash": session_hash}, stream=True, timeout=self.timeout
            )
        except (requests.exceptions.RequestException, OSError):
            raise connect_error(self.base_url)
        with streaming as response:
            if response.status_code != 200:
                raise server_error(response.text, self.base_url)
            for raw in response.iter_lines(decode_unicode=True):
                if interrupt_check:
                    interrupt_check()
                if not raw or not raw.startswith("data:"):
                    continue
                try:
                    message = json.loads(raw[5:].strip())
                except ValueError:
                    continue
                if message.get("event_id") != event_id:
                    continue
                kind = message.get("msg")
                if kind == "estimation":
                    if on_progress:
                        on_progress(None, "排队第 %d 位" % (int(message.get("rank") or 0) + 1))
                elif kind == "process_starts":
                    if on_progress:
                        on_progress(None, "开始合成…")
                elif kind == "progress":
                    if on_progress:
                        item = (message.get("progress_data") or [{}])[0]
                        on_progress(item.get("progress"), item.get("desc") or "合成中…")
                elif kind == "process_completed":
                    output = message.get("output") or {}
                    if not message.get("success"):
                        raise server_error(output.get("error"), self.base_url)
                    data = output.get("data")
                    if not data:
                        raise IndexTTSError(
                            "cancelled", "合成被取消（未拿到音频）", "重新运行即可"
                        )
                    return data
                elif kind == "unexpected_error":
                    raise server_error(str(message)[:400], self.base_url)
        raise IndexTTSError("interrupted", "与服务端的流提前结束", "检查 WebUI 日志后重试")

    def run(self, fn_index, data, session_hash=None, on_progress=None, interrupt_check=None):
        sh = session_hash or uuid.uuid4().hex
        event_id = self.start(fn_index, data, sh)
        return self.wait(event_id, sh, on_progress=on_progress, interrupt_check=interrupt_check)

    def cancel(self, session_hash, fn_index, event_id):
        """只释放队列槽位，不停 GPU（详见 docs/draft API 手册 §8.3）。"""
        payload = {"session_hash": session_hash, "fn_index": fn_index, "event_id": event_id}
        try:
            self.session.post(self._abs(self.prefix + "/cancel"), json=payload, timeout=self.timeout)
        except requests.exceptions.RequestException:
            pass

    def file_data(self, server_path, mime_type="audio/wav"):
        """构造 gradio 的 FileData（服务端只认已上传的文件）。"""
        return {
            "path": server_path,
            "url": self.base_url + self.prefix + "/file=" + server_path,
            "orig_name": os.path.basename(server_path),
            "mime_type": mime_type,
            "meta": {"_type": "gradio.FileData"},
        }

    def enable_experimental(self, session_hash, current_label):
        """同 session 打开「显示实验功能」，返回更新后的情感控制方式标签（通常 3 -> 4）。"""
        mapping = self.dependencies()
        if "on_experimental_change" not in mapping:
            return []
        data = self.run(
            mapping["on_experimental_change"],
            [True, current_label],
            session_hash=session_hash,
        )
        update = (data or [{}])[0] if data else {}
        choices = (update or {}).get("choices") or []
        labels = []
        for choice in choices:
            if isinstance(choice, (list, tuple)):
                labels.append(choice[0])
            else:
                labels.append(choice)
        return labels

    def first_file(self, data):
        """从回调返回值里取出文件 url/path（结果外面包了一层 value）。"""
        if not data:
            return None
        item = data[0]
        if isinstance(item, dict):
            value = item.get("value", item)
            if isinstance(value, dict):
                return value.get("url") or value.get("path")
            return value
        return item
