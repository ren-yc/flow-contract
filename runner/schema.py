"""极简 JSON Schema 校验器（stdlib only）。

为什么自己写而不用第三方库：契约仓库与两个上游仓库的 CI 都**不能引入依赖**——
runner 是纯 stdlib Python，加一个 jsonschema 会让「零安装」这条消失，
而它换来的是一个我们只用到很小一部分的规范实现。

支持的子集（够用即可）：type / enum / pattern / minimum / properties /
patternProperties / additionalProperties / required / minProperties / items /
minItems / oneOf / anyOf / 本地 $ref。

**不认识的关键字会在结果里提示**——静默忽略一个约束，等于给了一份假的保证。
"""

from __future__ import annotations

import re
from typing import Any

_KNOWN = {
    "$schema", "$id", "title", "description", "type", "enum", "pattern", "minimum",
    "properties", "patternProperties", "additionalProperties", "required", "minProperties",
    "items", "minItems", "oneOf", "anyOf", "$ref", "$defs",
}


def _type_ok(value: Any, want: str) -> bool:
    if want == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want == "boolean":
        return isinstance(value, bool)
    if want == "object":
        return isinstance(value, dict)
    if want == "array":
        return isinstance(value, list)
    if want == "string":
        return isinstance(value, str)
    if want == "null":
        return value is None
    return True


def _resolve(ref: str, root: dict) -> dict | None:
    if not ref.startswith("#/"):
        return None
    target: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(target, dict) or part not in target:
            return None
        target = target[part]
    return target if isinstance(target, dict) else None


def validate(instance: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """返回错误列表（空 = 通过）。path 用 JSON 记法，便于定位。"""
    root = root if root is not None else schema
    errors: list[str] = []

    ref = schema.get("$ref")
    if isinstance(ref, str):
        target = _resolve(ref, root)
        if target is None:
            return [path + ": $ref " + repr(ref) + " 解析不到"]
        return validate(instance, target, root, path)

    unknown = set(schema) - _KNOWN
    if unknown:
        errors.append(path + ": 校验器不认识这些关键字 " + repr(sorted(unknown)) + "——约束未被检查")

    want = schema.get("type")
    if isinstance(want, str) and not _type_ok(instance, want):
        errors.append(path + ": 期望 " + want + "，实际 " + type(instance).__name__)
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(path + ": 取值应为 " + repr(schema["enum"]) + " 之一，实际 " + repr(instance))

    if isinstance(instance, str) and "pattern" in schema:
        if not re.search(schema["pattern"], instance):
            errors.append(path + ": " + repr(instance) + " 不符合模式 " + repr(schema["pattern"]))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool) and "minimum" in schema:
        if instance < schema["minimum"]:
            errors.append(path + ": " + str(instance) + " 小于下界 " + str(schema["minimum"]))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(path + ": 缺必填键 " + repr(key))
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(path + ": 至少要有 " + str(schema["minProperties"]) + " 个键，实际 " + str(len(instance)))
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            matched = False
            if key in props:
                errors += validate(value, props[key], root, path + "." + key)
                matched = True
            for pat, sub in patterns.items():
                if re.search(pat, key):
                    errors += validate(value, sub, root, path + "." + key)
                    matched = True
            if not matched:
                if extra is False:
                    errors.append(path + ": 不允许出现键 " + repr(key))
                elif isinstance(extra, dict):
                    errors += validate(value, extra, root, path + "." + key)

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(path + ": 至少要有 " + str(schema["minItems"]) + " 项，实际 " + str(len(instance)))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors += validate(item, item_schema, root, path + "[" + str(i) + "]")

    for kw in ("oneOf", "anyOf"):
        branches = schema.get(kw)
        if not isinstance(branches, list):
            continue
        hits = sum(1 for b in branches if not validate(instance, b, root, path))
        if kw == "oneOf" and hits != 1:
            errors.append(path + ": oneOf 要求恰好命中一个分支，实际命中 " + str(hits) + " 个")
        if kw == "anyOf" and hits == 0:
            errors.append(path + ": anyOf 一个分支都没命中")

    return errors
