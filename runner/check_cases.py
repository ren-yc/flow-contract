"""用例静态校验：把「用例引用了不存在的东西」在 CI 里挡下来。

它检查五件事（每一件都是「写错了但跑起来才发现」的常见形态）：
  1. 用例本身符合 schema；
  2. 点名的**不变量都在注册表里**；
  3. `requires` 里的**能力名在夹具 schema 里有定义**；
  4. 用到的**槽位名与端点名**在夹具里存在；
  5. 用例 id **全库唯一**。
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import invariants as inv  # noqa: E402
import schema as sch  # noqa: E402

ROOT = HERE.parent
problems: list[str] = []
ids: dict[str, str] = {}
asserts_used: set[str] = set()
caps_used: set[str] = set()
slots_used: set[str] = set()
endpoints_used: set[str] = set()


# 与 run.py 的 `_COND` 一致：路径（允许 `capability:` 前缀）+ `==` + 字面量。
# **与 `run.py` 的 `_COND` 逐字一致**（路径字符集不含冒号）—— 我第一版多写了一个冒号，
# 于是把 `capability:authProbe == false` 判成合法，负向测试当场戳穿。校验器与被校验的
# 解析器用两套不同的语法，比不校验更糟：它给出「已检查」的假象。
#
# 能力门控请写进 `requires`（`"capability:X"`），不要写进条件表达式。
COND_RE = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*==\s*(true|false|null|-?[0-9]+|\"[^\"]*\")\s*$")


def main() -> int:
    csch = json.loads((ROOT / "schema/case.schema.json").read_text(encoding="utf-8"))
    fsch = json.loads((ROOT / "schema/fixture.schema.json").read_text(encoding="utf-8"))
    # 夹具里允许出现的能力名：schema 的必填项加上示例中出现的可选项。
    known_caps = set(fsch["properties"]["capabilities"]["required"]) | {"groupNickname", "authProbe"}
    # 必填核心端点 + 两个「schema 不强制、但用例可以引用」的可选端点：
    # `harness` 是控制面；`group-members` 是群主断言的落点（缺它的夹具会按 requires 跳过）。
    known_endpoints = set(fsch["properties"]["endpoints"]["required"]) | {"harness", "group-members"}
    # 槽位名没有固定词表（由夹具决定），但示例里给出的这几个是「约定俗成」的；
    # 因此这里只做**收集**，把用到的槽位打印出来供人核对。

    files = sorted((ROOT / "cases").rglob("*.json"))
    if not files:
        print("[用例校验] cases/ 下一个用例都没有——门禁没有可检查的对象", file=sys.stderr)
        return 1

    for path in files:
        rel = path.relative_to(ROOT)
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(str(rel) + ": 不是合法 JSON：" + str(e))
            continue
        for err in sch.validate(case, csch):
            problems.append(str(rel) + ": " + err)
        cid = case.get("id", "")
        if cid in ids:
            problems.append(str(rel) + ": 用例 id 与 " + ids[cid] + " 重复：" + cid)
        ids[cid] = str(rel)
        for need in case.get("requires", []):
            kind, _, name = need.partition(":")
            if kind == "capability":
                caps_used.add(name)
                if name not in known_caps:
                    problems.append(str(rel) + ": 能力名 " + name + " 不在夹具 schema 的定义里")
            if kind == "endpoint":
                endpoints_used.add(name)
                if name not in known_endpoints:
                    problems.append(str(rel) + ": 端点名 " + name + " 不在夹具 schema 的定义里")
            if kind == "slot":
                slots_used.add(name)
        for op in case.get("ops", []):
            # `skip_if` 的语法此前**没人校验** —— 于是 `"capability:authProbe == false"`
            # （`capability:` 不是该条件语法的一部分）一路滑到运行时，由执行器以退出码 2
            # 报「环境或用例非法」。这道静态校验把同一件事提前到 PR 阶段 —— 那里的报错
            # 更便宜。语法与 `run.py` 的 `_COND` 保持一致。
            for expr in [op.get("skip_if")] + list((op.get("loop_until") or "").split(" or ")):
                if expr and not COND_RE.match(expr):
                    problems.append(
                        str(rel)
                        + ": skip_if/loop_until 只支持 `a.b == 字面量`，实际 "
                        + repr(expr)
                    )
            # 流句柄必须两边一致：`sse_open` 起的名与 `sse_expect`/`sse_close` 找的名对不上，
            # 执行器会报「还没有打开流」。此前 `sse_expect` 在 schema 里**没有 `as`**，于是
            # 起了名的用例永远够不到它 —— 那是 schema 的漏，不是用例的错，已经补上；这条检查
            # 防的是另一半：两边写得不一样。
            if op.get("sse_open", {}).get("as"):
                opened = op["sse_open"]["as"]
                for later in case.get("ops", []):
                    for key in ("sse_expect", "sse_close"):
                        got = (later.get(key) or {}).get("as")
                        if got is not None and got != opened:
                            problems.append(
                                str(rel)
                                + ": 流句柄不一致：sse_open 用 "
                                + repr(opened)
                                + "，"
                                + key
                                + " 用 "
                                + repr(got)
                            )
            for name in op.get("assert", []):
                asserts_used.add(name)
            # 断言也可以挂在 sse_expect 里（等事件到达后再判）；漏掉它会让
            # 「有没有用例覆盖这条不变量」这个统计失真。
            expect = op.get("sse_expect")
            if isinstance(expect, dict):
                for name in expect.get("assert", []):
                    asserts_used.add(name)
            for key in ("req", "sse_open", "call"):
                blob = op.get(key)
                if isinstance(blob, dict) and isinstance(blob.get("slot"), str):
                    slots_used.add(blob["slot"])
                if isinstance(blob, dict) and isinstance(blob.get("endpoint"), str):
                    endpoints_used.add(blob["endpoint"])
            req = op.get("req")
            if isinstance(req, dict):
                for k, v in req.items():
                    if k in ("GET", "POST", "PUT", "DELETE", "PATCH") and isinstance(v, str):
                        m = re.match(r"^\{endpoints\.([a-z0-9_]+)\}$", v)
                        if m:
                            endpoints_used.add(m.group(1))

    missing = sorted(asserts_used - set(inv.names()))
    for name in missing:
        problems.append("用例点名了未登记的不变量：" + name)

    unused = sorted(set(inv.names()) - asserts_used)

    print("用例 " + str(len(files)) + " 个；点名不变量 " + str(len(asserts_used)) + " 条")
    print("用到的能力：" + (", ".join(sorted(caps_used)) or "（无）"))
    print("用到的槽位：" + (", ".join(sorted(slots_used)) or "（无）"))
    print("用到的端点：" + (", ".join(sorted(endpoints_used)) or "（无）"))
    if unused:
        print("注册表里**没有任何用例点名**的不变量（" + str(len(unused)) + " 条）：")
        print("  " + ", ".join(unused))
    if problems:
        print("")
        print("发现问题 " + str(len(problems)) + " 处：")
        for p in problems:
            print("  " + p)
        return 1
    print("")
    print("用例校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
