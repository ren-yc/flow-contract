"""一致性套件执行器：把共享用例跑在某个 base_url 上。

设计约束（决定了这里的形状）：
  * **纯 stdlib**——CI 与开发机都不装东西；
  * **断言逻辑不在这里**，在 invariants.py 的注册表里；本文件只负责「把用例的步骤
    翻译成 HTTP 调用与不变量求值」；
  * **失败要能定位**：每条失败都带用例 id 与「期望/实际」；
  * **skip 必须响亮**：跳过的用例进报告、进摘要，绝不静默通过。

用法：
    python runner/run.py --base-url URL --cases DIR --fixture FILE [--report FILE] [--token T]

退出码：0 全通过（可能含 skip，已列出）／1 断言失败／2 环境或用例非法。
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import invariants as inv  # noqa: E402
import report as rep  # noqa: E402
import schema as sch  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ENDPOINT_TPL = re.compile(r"^\{endpoints\.([a-z0-9_]+)\}$")
_VAR = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


class SetupError(Exception):
    """环境或用例非法——按退出码 2 处理，与断言失败区分开。"""


class SkipCase(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ── 取值与插值 ──

def dig(obj, path: str):
    """按 a.b.c 取值；取不到抛 KeyError（**不返回 None**——那会把「没有」当成「是 null」）。"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise KeyError(path)
    return cur


def resolve(text, ctx):
    """把 {var.path} 换成实际值。端点名与槽位名也走同一套变量表。"""
    if not isinstance(text, str):
        return text

    def sub(m):
        key = m.group(1)
        try:
            return str(dig(ctx.variables, key))
        except KeyError:
            raise SetupError("用例引用了未绑定的变量 {" + key + "}") from None

    return _VAR.sub(sub, text)


def endpoint_path(tpl: str, ctx, slot: str | None):
    m = _ENDPOINT_TPL.match(tpl)
    if not m:
        raise SetupError("端点写法应为 {endpoints.名字}，实际 " + repr(tpl))
    name = m.group(1)
    table = ctx.fixture.get("endpoints", {})
    if name not in table:
        raise SetupError("夹具没有声明端点 " + repr(name))
    path = table[name]
    if "{id}" in path:
        if not slot:
            raise SetupError("端点 " + name + " 的路径含 {id}，但这一步没给 slot")
        path = path.replace("{id}", str(ctx.variables.get("slot:" + slot, "")))
    return path


# ── HTTP ──

def _split_base(base_url: str):
    u = urllib.parse.urlsplit(base_url)
    if not u.scheme or not u.hostname:
        raise SetupError("base-url 不合法：" + repr(base_url))
    return u


def request(ctx, op, token: str | None):
    """执行一次 req。返回 (status, body)。"""
    req = op["req"]
    method = next((k for k in ("GET", "POST", "PUT", "DELETE", "PATCH") if k in req), None)
    if method is None:
        raise SetupError("req 缺方法键（GET/POST/…）：" + repr(req))
    slot = req.get("slot")
    path = endpoint_path(req[method], ctx, slot)
    query = {k: resolve(v, ctx) for k, v in (req.get("query") or {}).items()}
    if token:
        query.setdefault("access_token", token)
    if query:
        path = path + "?" + urllib.parse.urlencode(query)

    base = _split_base(ctx.fixture["_base_url"])
    conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=30)
    body = None
    headers = {}
    if "body" in req:
        body = json.dumps(req["body"])
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        status = resp.status
    finally:
        conn.close()
    ctx.requests += 1
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        raise SetupError("响应不是 JSON（HTTP " + str(status) + "）：" + raw[:200]) from None
    return status, parsed


# ── SSE ──

def sse_open(ctx, op, token: str | None):
    spec = op["sse_open"]
    name = spec["endpoint"]
    table = ctx.fixture.get("endpoints", {})
    if name not in table:
        raise SetupError("夹具没有声明端点 " + repr(name))
    base = _split_base(ctx.fixture["_base_url"])
    path = table[name]
    if token:
        path = path + "?" + urllib.parse.urlencode({"access_token": token})
    conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=60)
    conn.request("GET", path, headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()
    handle = spec.get("as", "stream")
    ctx.streams[handle] = (conn, resp)
    return handle


def _read_event(resp, within_s: float):
    """读一帧 SSE；返回 (event_name, data_str)。

    超时与**连接被对端关闭**都会返回 (None, None)，但二者的含义完全不同（一个是「还没来」，
    一个是「流没了」），所以关闭那一侧额外抛出 —— 报错里混着说会让人去查错方向。
    """
    import time
    deadline = time.time() + within_s
    event = None
    data_lines: list[str] = []
    while time.time() < deadline:
        line = resp.readline()
        if not line:
            raise SetupError("SSE 连接被对端关闭（读到 EOF）—— 流已结束，不是超时")
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if text == "":
            if event or data_lines:
                return event or "message", "\n".join(data_lines)
            continue
        if text.startswith(":"):
            continue
        if text.startswith("event:"):
            event = text[6:].strip()
        elif text.startswith("data:"):
            data_lines.append(text[5:].strip())
    return None, None


def sse_expect(ctx, op):
    spec = op["sse_expect"]
    handle = spec.get("as", "stream")
    if handle not in ctx.streams:
        raise SetupError("还没有打开流 " + repr(handle) + "：sse_expect 之前必须先 sse_open")
    _, resp = ctx.streams[handle]
    # **等待直到**期望的事件，而不是「下一帧必须是它」。
    #
    # 为什么：规范把 SSE 定义为**通知通道** ——「ChatLab 不假设 SSE 事件可靠送达」，客户端
    # 按事件类型过滤（它只对 `message.new` 有反应，其余帧直接忽略）。数据源在连接建立时
    # 发一条基线帧（本项目的实现发的是 `ready`）是完全正常的，而「下一帧必须是 X」会把这条
    # 合规的基线判成失败 —— 两个上游仓库都卡在这里，正是这个原因。
    #
    # `within_s` 的语义不变：它是**总的等待上限**，不是单帧的读超时。
    #
    # 跳过的事件名会记下来并写进超时报错：否则「跳过」会退化成「静默吞掉任何东西」，
    # 一个疯狂发帧的数据源和一个正常的数据源在报告里就分不出来了。
    import time
    deadline = time.time() + float(spec["within_s"])
    skipped: list[str] = []
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise SetupError(
                "在 "
                + str(spec["within_s"])
                + " 秒内没有收到事件 "
                + repr(spec["event"])
                + "（期间跳过 "
                + str(len(skipped))
                + " 帧："
                + repr(skipped[:10])
                + "）"
            )
        name, data = _read_event(resp, remaining)
        if name is None:
            raise SetupError(
                "在 "
                + str(spec["within_s"])
                + " 秒内没有收到事件 "
                + repr(spec["event"])
                + "（期间跳过 "
                + str(len(skipped))
                + " 帧："
                + repr(skipped[:10])
                + "）"
            )
        if name == spec["event"]:
            break
        skipped.append(name)
    try:
        ctx.body = json.loads(data) if data else None
    except json.JSONDecodeError:
        raise SetupError("事件 " + name + " 的 data 不是 JSON：" + data[:200]) from None
    ctx.last_event = ctx.body if isinstance(ctx.body, dict) else None
    ctx.status = 200
    return name


# ── 条件 ──

_COND = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*==\s*(true|false|null|-?[0-9]+|\"[^\"]*\")\s*$")


def eval_condition(expr: str, ctx) -> bool:
    m = _COND.match(expr)
    if not m:
        raise SetupError("条件只支持 a.b == 字面量，实际 " + repr(expr))
    path, lit = m.group(1), m.group(2)
    if path.startswith("capability:"):
        left = ctx.cap(path.split(":", 1)[1])
    else:
        try:
            left = dig(ctx.body if path.startswith("sync.") or path.startswith("page.") else ctx.variables, path)
        except KeyError:
            return False
    if lit == "true":
        right = True
    elif lit == "false":
        right = False
    elif lit == "null":
        right = None
    elif lit.startswith(chr(34)):
        right = lit[1:-1]
    else:
        right = int(lit)
    return left == right


# ── 用例执行 ──

def run_case(case, ctx, token: str | None) -> rep.Result:
    result = rep.Result(case_id=case["id"], group=case.get("group", ""))
    try:
        for need in case.get("requires", []):
            kind, _, name = need.partition(":")
            if kind == "capability" and not ctx.cap(name):
                raise SkipCase("本平台不具备能力 " + name)
            if kind == "endpoint" and name not in ctx.fixture.get("endpoints", {}):
                raise SkipCase("夹具没有声明端点 " + name)
            if kind == "slot" and name not in ctx.fixture.get("slots", {}):
                raise SkipCase("夹具没有声明槽位 " + name)

        for op in case["ops"]:
            if "skip_if" in op:
                if eval_condition(op["skip_if"], ctx):
                    raise SkipCase("满足 skip_if：" + op["skip_if"])
                continue
            if "sse_open" in op:
                sse_open(ctx, op, token)
                continue
            if "sse_expect" in op:
                # **不要 `continue` 走掉**：这一支和下面的 `req` 支一样要跑 `save` 与 `assert`。
                # 原来它直接 `continue`，于是 `sse_expect` 里写的 `assert` **从未被执行** —— 用例看起来
                # 在验「通知帧只带元信息」，实际只验了「来了一帧」。症状是「断言绿了但没在验东西」，
                # 与「`loop_until` 从不应用 `save`」是同一类：**执行器少做一步，而用例看不出来**。
                sse_expect(ctx, op)
            elif "sse_close" in op:
                handle = op["sse_close"].get("as", "stream")
                pair = ctx.streams.pop(handle, None)
                if pair:
                    pair[0].close()
                continue
            if "call" in op:
                _harness_call(ctx, op, token)
                continue
            if "loop_until" in op:
                _loop(ctx, op, token, result, case)
                continue
            if "req" in op:
                status, body = request(ctx, op, token)
                ctx.status, ctx.body = status, body
                ctx.pages.append(_page_summary(body))
                ctx.variables["request_limit"] = (op["req"].get("query") or {}).get("limit")
                ctx.variables["request_since"] = (op["req"].get("query") or {}).get("since")
            _apply_save(ctx, op, case)
            if "assert" in op:
                _run_asserts(ctx, op["assert"], result)
        return result
    except SkipCase as e:
        result.status = "skip"
        result.skip_reason = e.reason
        return result


# 每一页都记下 id 与时间戳：跨页断言（不重不丢、排空等于全量、同秒不切页）
# 全部靠这些摘要，不需要用例额外声明什么——声明越少，用例越不容易写错。
def _page_summary(body):
    msgs = body.get("messages", []) if isinstance(body, dict) else []
    ts = [m.get("timestamp") for m in msgs if isinstance(m.get("timestamp"), int)]
    ids = [m.get("platformMessageId") for m in msgs if isinstance(m.get("platformMessageId"), str)]
    return {
        "first_ts": ts[0] if ts else None,
        "last_ts": ts[-1] if ts else None,
        "ids": ids,
        "n": len(msgs),
    }


def _run_asserts(ctx, names_used, result):
    missing = inv.unknown(list(names_used))
    if missing:
        raise SetupError("用例点名了未登记的不变量：" + ", ".join(missing))
    for name in names_used:
        doc, fn = inv.REGISTRY[name]
        reason = fn(ctx)
        if reason:
            result.status = "fail"
            result.reasons.append("[" + name + "] " + reason)


def _apply_save(ctx, op, case):
    """把本 op 的 `save` 落到变量表。

    **循环里的每一轮都要调用它**：`loop_until` 的游标通常就是靠同一条 op 的 `save` 推进的
    （`since: {s1}` ＋ `save: {s1: sync.nextSince}`）。此前 `_loop` 只发请求、从不应用 save，
    于是游标永不更新、同一页取满 `max` 次后报「loop_until 在 N 次内没有满足」—— 症状像是
    翻页实现有问题，实际是执行器少做了一步。
    """
    for var, path in (op.get("save") or {}).items():
        # 哨兵 $ids：存本页的 platformMessageId 列表。
        # 需要它的原因：跨页对比要有**显式基准**，而「把第一页当全量」
        # 与「页间不得重复」是互相矛盾的（同一批 id 必然重复出现）。
        if path == "$ids":
            ctx.variables[var] = _page_summary(ctx.body)["ids"]
            continue
        try:
            ctx.variables[var] = dig(ctx.body, path)
        except KeyError:
            raise SetupError("save 取不到 " + path + "（用例 id：" + case.get("id", "?") + "）") from None


def _loop(ctx, op, token, result, case):
    spec = op["loop_until"]
    limit = op.get("max")
    if not isinstance(limit, int) or limit < 1:
        raise SetupError("loop_until 必须给 max（否则翻页可能死循环）")
    for _ in range(limit):
        status, body = request(ctx, {"req": op["req"]}, token)
        ctx.status, ctx.body = status, body
        ctx.pages.append(_page_summary(body))
        _apply_save(ctx, op, case)
        if "assert" in op:
            _run_asserts(ctx, op["assert"], result)
        if eval_condition(spec, ctx):
            return
    raise SetupError("loop_until 在 " + str(limit) + " 次内没有满足：" + spec)


def _harness_call(ctx, op, token):
    table = ctx.fixture.get("endpoints", {})
    if "harness" not in table:
        raise SkipCase("夹具没有声明 harness 端点——该仓库的 harness 不提供控制动作")
    payload = {"action": op["call"], "args": op.get("args", {})}
    base = _split_base(ctx.fixture["_base_url"])
    conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=30)
    try:
        conn.request("POST", table["harness"], body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        if resp.status >= 400:
            raise SetupError("harness 动作 " + op["call"] + " 返回 " + str(resp.status))
    finally:
        conn.close()


# ── 入口 ──

def load_cases(directory: str):
    files = sorted(Path(directory).rglob("*.json"))
    cases = []
    for f in files:
        try:
            cases.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise SetupError("用例不是合法 JSON：" + str(f) + "：" + str(e)) from None
    return cases


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="一致性套件执行器")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--token", default=os.environ.get("CONFORMANCE_TOKEN", ""))
    ap.add_argument("--schemas", default=None, help="schema 目录，默认取 runner 的同级 schema/")
    ap.add_argument(
        "--case",
        action="append",
        default=None,
        help="只跑 id 含这些子串的用例（可重复）。用于把一条用例单独拉出来查："
        "一整套跑下来时，报错本身往往不足以定位到是哪条路径出的问题。",
    )
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    schema_dir = Path(args.schemas) if args.schemas else here.parent / "schema"

    try:
        fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        cases = load_cases(args.cases)
    except (OSError, json.JSONDecodeError, SetupError) as e:
        print("[一致性套件] 读不到夹具或用例，按环境问题处理：" + str(e), file=sys.stderr)
        return 2

    # 先校验格式再执行：非法用例是 setup error，不该与断言失败混在一起。
    problems: list[str] = []
    try:
        fsch = json.loads((schema_dir / "fixture.schema.json").read_text(encoding="utf-8"))
        csch = json.loads((schema_dir / "case.schema.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print("[一致性套件] 读不到 schema：" + str(e), file=sys.stderr)
        return 2
    # 校验**全部**用例（含被 --case 过滤掉的那些）：过滤是为了调试，不该顺带削弱门禁。
    all_cases = cases
    problems += ["fixture: " + e for e in sch.validate(fixture, fsch)]
    for c in cases:
        problems += [str(c.get("id", "<无 id>")) + ": " + e for e in sch.validate(c, csch)]
    if problems:
        print("[一致性套件] 夹具或用例不合法（" + str(len(problems)) + " 处）：", file=sys.stderr)
        for p in problems[:20]:
            print("  " + p, file=sys.stderr)
        return 2

    # 版本自洽：夹具声明的契约版本必须与 VERSION 一致
    try:
        version = (here.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    if version and fixture.get("contractVersion") != version:
        print("[一致性套件] 夹具的 contractVersion=" + repr(fixture.get("contractVersion"))
              + " 与 VERSION=" + repr(version) + " 不一致", file=sys.stderr)
        return 2

    fixture["_base_url"] = args.base_url

    if args.case:
        wanted = args.case
        cases = [c for c in all_cases if any(w in c.get("id", "") for w in wanted)]
        if not cases:
            print(
                "[一致性套件] --case 没有匹配到任何用例：" + repr(wanted),
                file=sys.stderr,
            )
            return 2
        print("[一致性套件] --case 过滤后只跑 " + str(len(cases)) + " 条："
              + ", ".join(c.get("id", "?") for c in cases))

    results = []
    for case in cases:
        ctx = inv.Ctx(fixture=fixture, case=case)
        for slot, spec in (fixture.get("slots") or {}).items():
            ctx.variables["slot:" + slot] = spec.get("id", "")
        # 执行期的 SetupError 在这里补上用例名再抛：否则顶层只报「loop_until 在 80 次内没有满足」
        # 之类的话，**看不出是哪条用例**，而契约套件里有 33 条、其中多条用同一个不变量。
        try:
            result = run_case(case, ctx, args.token or None)
        except SetupError as e:
            raise SetupError("用例 " + repr(case.get("id", "?")) + "：" + str(e)) from None
        result.requests = ctx.requests
        results.append(result)

    print(rep.summarize(results, len(cases)))
    if args.report:
        rep.write_report(args.report, results,
                         base_url=args.base_url,
                         platform=fixture.get("platform", ""),
                         contract_version=fixture.get("contractVersion", ""),
                         cases_total=len(cases))
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as e:
        print("[一致性套件] 环境或用例非法，按退出码 2 处理：" + str(e), file=sys.stderr)
        sys.exit(2)
