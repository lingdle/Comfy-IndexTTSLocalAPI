"""剧本配音（IndexTTSLocalScriptDubbing）—— ComfyUI 自定义节点。"""

from comfy_api.latest import ComfyExtension

from .core.version import VERSION
from .nodes import ScriptDubbingNode

__version__ = VERSION

__all__ = ["IndexTTSExtension", "comfy_entrypoint", "__version__"]


class IndexTTSExtension(ComfyExtension):
    async def get_node_list(self):
        return [ScriptDubbingNode]


async def comfy_entrypoint():
    return IndexTTSExtension()
