"""一致性套件执行器：把共享用例跑在某个 base_url 上。

设计约束（决定了这里的形状）：
  * **纯 stdlib**——CI 与开发机都不装东西；
  * **断言逻辑不在这里**，在 invariants.py 的注册表里；本文件只负责「把用例的步骤
    翻译成 HTTP 调用与不变量求值」；
  * **失败要能定位**：每条失败都带用例 id 与「期望/实际」；
  * **skip 必须响亮**：跳过的用例进报告、进摘要，绝不静默通过。

用法：
    python runner/run.py --base-url URL --cases DIR --fixture FILE
                         [--report FILE] [--token T] [--case SUBSTR] [--fail-on-skip]

退出码：0 全通过（可能含 skip，已列出）／1 断言失败，或带 --fail-on-skip 时**有跳过**
        ／2 环境或用例非法（含：夹具的 contractVersion 与 VERSION 不一致，或 HEAD 所在的
        tag 与 VERSION 不一致）。

为什么要有 --fail-on-skip：**「跳过」与「通过」必须能被调用方区分**。默认仍是 0（skip
只进摘要，供人读），但那等于把「这条用例到底跑没跑」交给读者；门禁需要的是机器可判定的
信号——CI 带上本开关后，用例因缺端点/槽位/能力而被跳过时**直接失败**，而不是绿着过去。
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
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

# 端点名允许连字符（如 group-members）—— 与 case.schema 的模板模式保持同一字符集。
_ENDPOINT_TPL = re.compile(r"^\{endpoints\.([a-z0-9_-]+)\}$")
# 变量字符集含 `:` —— 槽位 id 以 `slot:名字` 存进变量表（fixture 装载处），
# 正则不放行冒号时它就引用不到，这与 resolve 的文档（「端点名与槽位名也走同一套变量表」）矛盾。
_VAR = re.compile(r"\{([a-zA-Z0-9_.:]+)\}")


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
    headers = {"Accept": "text/event-stream"}
    # `last_event_id` 可以是字面量，也可以是 "{var}" 形式的变量引用（比如注销前
    # 存下的最后事件号）：重放语义的用例必须能带着旧游标重连，否则「旧游标 + 注销」
    # 的组合永远测不到。
    last_id = spec.get("last_event_id")
    if last_id is not None:
        headers["Last-Event-ID"] = resolve(str(last_id), ctx)
    conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=60)
    conn.request("GET", path, headers=headers)
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
    event_id = None
    data_lines: list[str] = []
    while time.time() < deadline:
        line = resp.readline()
        if not line:
            raise SetupError("SSE 连接被对端关闭（读到 EOF）—— 流已结束，不是超时")
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if text == "":
            if event or data_lines:
                # `id:` 行与事件一起返回：重放语义的用例要把它存下来当重连游标。
                return event or "message", "\n".join(data_lines), event_id
            continue
        if text.startswith(":"):
            continue
        if text.startswith("event:"):
            event = text[6:].strip()
        elif text.startswith("id:"):
            event_id = text[3:].strip()
        elif text.startswith("data:"):
            data_lines.append(text[5:].strip())
    return None, None, None


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
        name, data, event_id = _read_event(resp, remaining)
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
    # `save` 的键落到变量表：`$event_id` 哨兵存本帧的 SSE id（重连游标），
    # 其余键按 dig 路径从事件体取。
    for var, path in (spec.get("save") or {}).items():
        if path == "$event_id":
            ctx.variables[var] = event_id
            continue
        try:
            ctx.variables[var] = dig(ctx.body, path)
        except KeyError:
            pass
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
                # **不要 `continue` 走掉**，而且断言在 `sse_expect` **里面**（`{sse_expect: {assert: […]}}`），
                # 不在 `op["assert"]` —— 只去掉 `continue` 是不够的：那样确实会走到 `_run_asserts`，
                # 但取的是**空键**，等于没跑（我第一次就是这么「修」的，反向验证当场戳穿）。
                #
                # 原来的写法直接 `continue`，于是这些断言**从未被执行** —— 用例看起来在验「通知帧只带
                # 元信息」，实际只验了「来了一帧」。与「`loop_until` 从不应用 `save`」同类：
                # **执行器少做一步，而用例看不出来**。
                spec = op["sse_expect"]
                sse_expect(ctx, op)
                if "assert" in spec:
                    _run_asserts(ctx, spec["assert"], result)
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
    ap.add_argument(
        "--fail-on-skip",
        action="store_true",
        help="有用例被跳过时返回 1（默认为 0，跳过只进摘要）。门禁应当带上它："
        "否则「夹具少声明一个端点」这类改动会让用例静默变成不跑，而 CI 仍是绿的。",
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

    # tag 自洽：**能读到 git 时**，HEAD 必须正好落在与 VERSION 同名的 tag 上。
    # 为什么值得单独查：夹具的 contractVersion 是上游手写的常量，而「上游到底 pin 了哪个
    # tag」只有 git 知道 —— 只改 conformance.pin 而忘了夹具（或反过来）在本地不会红，
    # 而 CI clone 的是 tag 指向的那份代码。上游 runner 因此不再只是「声称」校验 tag。
    #
    # 读不到 git（没有 .git、没装 git）或 HEAD 不在任何 tag 上时**只提示不失败**：
    # 开发工作副本天然领先于最近的 tag，把那种状态判成环境错误会让本地跑一遍变得没法用。
    if (here.parent / ".git").exists():
        tag = None
        try:
            tag = subprocess.run(
                ["git", "-C", str(here.parent), "describe", "--tags", "--exact-match", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            tag = None
        if tag is not None and tag.returncode == 0:
            name = tag.stdout.strip()
            if version and name not in (version, "v" + version):
                print("[一致性套件] HEAD 落在 tag " + repr(name) + " 上，而 VERSION="
                      + repr(version) + " —— 两者必须一致", file=sys.stderr)
                return 2
        else:
            print("[一致性套件] HEAD 不在任何 tag 上（或读不到 git）——跳过 tag 校验，"
                  "夹具与 VERSION 的比对已执行", file=sys.stderr)

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
    if any(r.status == "fail" for r in results):
        return 1
    skipped = [r for r in results if r.status == "skip"]
    if skipped and args.fail_on_skip:
        print(
            "[一致性套件] 有 " + str(len(skipped)) + " 条用例被跳过（--fail-on-skip 下按失败处理）："
            + "; ".join(str(r.case_id) + "：" + str(getattr(r, "skip_reason", "")) for r in skipped),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as e:
        print("[一致性套件] 环境或用例非法，按退出码 2 处理：" + str(e), file=sys.stderr)
        sys.exit(2)
