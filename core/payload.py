"""按服务端 /info 的参数表组装 payload：一律按名字，不按位置。"""

PARAM_LABEL_SEMANTICS = {
    "do_sample": "do_sample",
    "top_p": "top_p",
    "top_k": "top_k",
    "temperature": "temperature",
    "length_penalty": "length_penalty",
    "num_beams": "num_beams",
    "repetition_penalty": "repetition_penalty",
    "max_mel_tokens": "max_mel_tokens",
}


def parameters(spec):
    return (spec or {}).get("parameters") or []


def semantic_name(param):
    name = (param or {}).get("parameter_name") or ""
    if name.startswith("param_"):
        return PARAM_LABEL_SEMANTICS.get(((param or {}).get("label") or "").strip(), name)
    return name


def parameter_names(spec):
    return [semantic_name(item) for item in parameters(spec)]


def index_of(spec, name):
    for index, item in enumerate(parameters(spec)):
        if semantic_name(item) == name:
            return index
    return None


def build_payload(spec, values):
    """按 /info 的顺序生成 data[]；没给的用服务端默认值。"""
    return [values.get(semantic_name(item), item.get("parameter_default")) for item in parameters(spec)]


def enum_of(spec, name):
    index = index_of(spec, name)
    if index is None:
        return []
    type_info = parameters(spec)[index].get("type") or {}
    return list(type_info.get("enum") or [])


def emotion_labels(spec):
    return enum_of(spec, "emo_control_method")


def default_of(spec, name, fallback=None):
    index = index_of(spec, name)
    if index is None:
        return fallback
    value = parameters(spec)[index].get("parameter_default")
    return fallback if value is None else value
