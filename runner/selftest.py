"""不变量自测：不需要真实服务，用合成响应体检注册表本身。

为什么要有它：注册表是「判断逻辑的唯一出处」，它自己写错了没有任何东西会拦。
每条不变量至少验两件事：**该过的过、该拦的拦**——只验前者等于没验。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import invariants as inv  # noqa: E402

FAILS = []


def check(label, cond):
    if cond:
        print("  ✓ " + label)
    else:
        print("  ✗ " + label)
        FAILS.append(label)


def ctx_with(body, **kw):
    f = {"platform": "wechat", "capabilities": {"sse": True, "roles": False}}
    c = inv.Ctx(fixture=f, case={}, body=body)
    c.variables.update(kw.get("variables", {}))
    c.captured.update(kw.get("captured", {}))
    return c


def envelope(**over):
    body = {
        "chatlab": {"version": "0.0.2", "exportedAt": 1790000000, "generator": "harness"},
        "meta": {"name": "群甲", "platform": "wechat", "type": "group", "groupId": "G1"},
        "members": [{"platformId": "M1", "accountName": "甲", "groupNickname": "", "isOwner": True}],
        "messages": [{"platformMessageId": "P1", "sender": "M1", "timestamp": 1790000001,
                      "type": 1, "content": "hi"}],
        "sync": {"hasMore": False, "nextSince": 1790000001, "nextOffset": 0},
    }
    body.update(over)
    return body


def run(name, ctx):
    return inv.REGISTRY[name][1](ctx)


print("A 组：信封")
c = ctx_with(envelope())
c.captured["path_id"] = "G1"
for n in ("envelope_five_blocks", "version_is_0_0_2", "generator_nonempty_string",
          "meta_name_nonempty", "meta_type_matches_session", "meta_groupId_matches_id",
          "platform_matches_fixture", "members_unique_platformId",
          "members_match_page_senders", "members_accountName_nonempty",
          "type_in_subset_never_6", "timestamps_non_decreasing_seconds",
          "platformMessageId_string_unique_stable", "content_key_present",
          "no_mediaPath_in_pull", "groupNickname_semantics", "isOwner_exactly_one"):
    check(n + " 通过合法响应", run(n, c) is None)

print("A 组：应当拦住的")
b = envelope()
b["chatlab"]["version"] = "0.0.3"
check("version 不是 0.0.2 被拦", run("version_is_0_0_2", ctx_with(b)) is not None)
b = envelope()
b["messages"][0]["timestamp"] = 1790000001000
check("毫秒时间戳被拦", run("timestamps_non_decreasing_seconds", ctx_with(b)) is not None)
b = envelope()
b["messages"][0]["type"] = 6
check("类型 6 被拦", run("type_in_subset_never_6", ctx_with(b)) is not None)
b = envelope()
b["messages"][0]["sender"] = "M9"
check("未列入 members 的发送者被拦", run("members_match_page_senders", ctx_with(b)) is not None)
b = envelope()
b["messages"][0]["platformMessageId"] = "P1"
b["messages"].append(dict(b["messages"][0]))
check("重复 platformMessageId 被拦", run("platformMessageId_string_unique_stable", ctx_with(b)) is not None)
b = envelope()
del b["meta"]
check("缺 meta 块被拦", run("envelope_five_blocks", ctx_with(b)) is not None)

print("B 组：游标")
c = ctx_with(envelope(), variables={"request_since": 1790000000})
c.pages = [{"ids": ["P1"]}, {"ids": ["P2"]}]
for n in ("since_exclusive_end_inclusive", "drained_cursor_terminal_state",
          "since_default_starts_at_earliest", "cursor_exclusive_no_gap_no_dup"):
    check(n + " 通过合法响应", run(n, c) is None)
c = ctx_with(envelope(), variables={"full_ids": ["P1", "P2"]})
c.pages = [{"ids": ["P1"]}, {"ids": ["P2"]}]
check("drained_set_equals_full_set 通过合法响应", run("drained_set_equals_full_set", c) is None)
b = envelope()
b["messages"][0]["timestamp"] = 1789999999
check("早于 since 的消息被拦", run("since_exclusive_end_inclusive",
      ctx_with(b, variables={"request_since": 1790000000})) is not None)
b = envelope()
b["sync"]["nextOffset"] = 5
check("排空后 nextOffset 非零被拦", run("drained_cursor_terminal_state", ctx_with(b)) is not None)
c = ctx_with(envelope(), variables={"full_ids": ["P1"]})
c.pages = [{"ids": ["P1"]}, {"ids": ["P2"]}]
check("排空集合与全量不一致被拦", run("drained_set_equals_full_set", c) is not None)

print("C 组：发现端点")
c = ctx_with({"sessions": [{"id": "G1", "name": "群甲", "platform": "wechat", "type": "group"}],
              "count": 1}, variables={"request_limit": 10})
for n in ("discovery_shape", "no_page_implies_complete", "session_ids_resolvable_by_pull"):
    check(n + " 通过合法响应", run(n, c) is None)
c = ctx_with({"sessions": [{"id": "G1", "name": "群甲", "platform": "wechat", "type": "room"}]})
check("非法会话 type 被拦", run("discovery_shape", c) is not None)

print("E 组：逐字段语义")
b = envelope()
b["messages"][0]["replyToMessageId"] = None
check("replyToMessageId 为 null 被拦", run("replyToMessageId_is_string_never_null", ctx_with(b)) is not None)
b = envelope()
b["members"].append({"platformId": "M2", "accountName": "乙", "groupNickname": "", "isOwner": True})
check("两个群主被拦", run("isOwner_exactly_one", ctx_with(b)) is not None)
b = envelope()
b["members"][0]["isOwner"] = False
check("没有群主被拦（0 同样是缺陷）", run("isOwner_exactly_one", ctx_with(b)) is not None)
b = envelope()
b["members"][0].pop("isOwner")
check("没有 isOwner 键也被拦", run("isOwner_exactly_one", ctx_with(b)) is not None)
b = envelope()
b["members"].append({"platformId": "M2", "accountName": "乙", "groupNickname": "", "isOwner": False})
check("两成员恰一真通过（正常形状）", run("isOwner_exactly_one", ctx_with(b)) is None)


print("补：其余不变量（该过的过、该拦的拦）")
b = envelope()
b["members"][0]["avatar"] = "http://127.0.0.1/x.png"
check("avatar 是字符串时通过", run("members_avatar_is_string", ctx_with(b)) is None)
b["members"][0]["avatar"] = 123
check("avatar 非字符串被拦", run("members_avatar_is_string", ctx_with(b)) is not None)

c = ctx_with({})
c.status = 200
check("非法分页参数返回 200 时通过", run("tolerant_pagination_params", c) is None)
c = ctx_with({})
c.status = 400
check("非法分页参数返回 400 被拦", run("tolerant_pagination_params", c) is not None)

c = ctx_with({"success": False, "code": 404, "message": "session not found"})
c.status = 404
check("404 + 统一信封时通过", run("unknown_session_404_envelope", c) is None)
c.status = 200
check("404 却返回 200 被拦", run("unknown_session_404_envelope", c) is not None)
c = ctx_with({"error": {"code": "not_found", "message": "no such session"}})
c.status = 404
check("旧的 error 形状不再被当作统一信封", run("unknown_session_404_envelope", c) is not None)
c = ctx_with({"success": False, "code": 404})
c.status = 404
check("缺 message 被拦", run("unknown_session_404_envelope", c) is not None)

c = ctx_with(envelope())
c.pages = [{"last_ts": 100}, {"first_ts": 100}]
check("同一秒跨页被拦", run("same_second_not_split", c) is not None)
c.pages = [{"last_ts": 99}, {"first_ts": 100}]
check("跨页边界正常时通过", run("same_second_not_split", c) is None)

# P1 在两页里都出现 → 游标不排他，应被拦
c = ctx_with(envelope())
c.pages = [{"ids": ["P1"]}, {"ids": ["P1"]}]
check("跨页重复 id 被拦", run("cursor_exclusive_no_gap_no_dup", c) is not None)
c = ctx_with(envelope())
c.pages = [{"ids": ["P1"]}, {"ids": ["P2"]}]
check("两页无重叠时通过", run("cursor_exclusive_no_gap_no_dup", c) is None)

c = ctx_with(envelope())
c.status = 200
check("offset 与 since 叠加返回 200 时通过", run("offset_and_since_composable", c) is None)

c = ctx_with(envelope(), variables={"watermark": 1790000005})
check("增量里出现旧消息被拦", run("incremental_only_new", c) is not None)
c = ctx_with(envelope(), variables={"watermark": 1790000000})
check("增量只含新消息时通过", run("incremental_only_new", c) is None)

print("B 组补：排空后追加可达（不透明进度游标）")
c = ctx_with(envelope(), variables={"appended_id": "PA", "drained_ids": ["P1"], "continuation_ids": ["PA"]})
check("排空后追加的消息可达时通过", run("cursor_progress_reaches_appended", c) is None)
c = ctx_with(envelope(), variables={"appended_id": "PA", "drained_ids": ["P1"], "continuation_ids": []})
check("追加消息不在续拉结果被拦", run("cursor_progress_reaches_appended", c) is not None)
c = ctx_with(envelope())
check("缺全部基准被拦", run("cursor_progress_reaches_appended", c) is not None)
c = ctx_with(envelope(), variables={"drained_ids": ["P1"], "continuation_ids": ["PA"]})
check("缺 appended_id 基准被拦", run("cursor_progress_reaches_appended", c) is not None)
c = ctx_with(envelope(), variables={"appended_id": "PA", "drained_ids": [], "continuation_ids": []})
check("排空基准为空被拦（两种世界不可区分）",
      run("cursor_progress_reaches_appended", c) is not None)
c = ctx_with(envelope(), variables={"appended_id": "P1", "drained_ids": ["P1"], "continuation_ids": ["P1"]})
check("追加消息出现在排空基准里被拦（harness 注入失败）",
      run("cursor_progress_reaches_appended", c) is not None)
c = ctx_with(envelope(), variables={"appended_id": "PA", "drained_ids": ["P1"], "continuation_ids": ["PA", "P1"]})
check("续拉重放排空前的旧页被拦", run("cursor_progress_reaches_appended", c) is not None)

print("B 组补：排空后进度游标在场")
c = ctx_with(envelope(sync={"hasMore": False, "nextSince": 1790000001, "nextOffset": 0, "nextCursor": "opaque-1"}))
check("排空后 nextCursor 非空时通过", run("opaque_cursor_presents_on_drain", c) is None)
c = ctx_with(envelope())
check("排空后 nextCursor 缺失被拦", run("opaque_cursor_presents_on_drain", c) is not None)
c = ctx_with(envelope(sync={"hasMore": False, "nextSince": 1790000001, "nextOffset": 0, "nextCursor": None}))
check("排空后 nextCursor 为 null 被拦（消息面约定不可平移）",
      run("opaque_cursor_presents_on_drain", c) is not None)
c = ctx_with(envelope(sync={"hasMore": False, "nextSince": 1790000001, "nextOffset": 0, "nextCursor": ""}))
check("排空后 nextCursor 为空串被拦", run("opaque_cursor_presents_on_drain", c) is not None)

print("媒体句柄取字节")
c = ctx_with({})
c.status = 200
c.raw = b"\x00\x01\x02binary"
c.response_content_type = "application/octet-stream"
check("200 且非空字节时通过", run("media_fetch_bytes_nonempty", c) is None)
c = ctx_with({})
c.status = 404
check("404 被拦（承诺未兑现）", run("media_fetch_bytes_nonempty", c) is not None)
c = ctx_with({})
c.status = 200
c.response_content_type = "application/octet-stream"
check("200 但空响应体被拦", run("media_fetch_bytes_nonempty", c) is not None)
c = ctx_with({})
c.status = 200
c.raw = b'{"success": false}'
c.response_content_type = "application/json"
check("200 的 JSON 错误信封被拦（假通过防线）",
      run("media_fetch_bytes_nonempty", c) is not None)
c = ctx_with({})
c.status = 200
c.raw = b'{"success": false}'
c.response_content_type = "text/plain"
check("text/plain 包装的 JSON 信封也被拦（body 判据）",
      run("media_fetch_bytes_nonempty", c) is not None)
c = ctx_with({})
c.status = 200
c.raw = b"\x00\x01\x02binary"
check("无 Content-Type 的非空字节通过（content-type 判据只拒 json）",
      run("media_fetch_bytes_nonempty", c) is None)
c = ctx_with({})
c.status = 200
c.raw = b"\x00\x01\x02binary"
c.response_content_type = "application/octet-stream"
check("octet-stream 字节时通过", run("media_fetch_bytes_nonempty", c) is None)

c = ctx_with({})
c.fixture["authProbed"] = {"bearer": 200, "access_token": 200}
check("两条通道全 200 时通过", run("auth_transports_matrix", c) is None)
c = ctx_with({})
c.fixture["authProbed"] = {"bearer": 200, "access_token": 401}
check("有一条通道没返回 200 被拦", run("auth_transports_matrix", c) is not None)

c = ctx_with({})
c.last_event = {"generation": 3, "watermarks": []}
check("注销基线带 generation 时通过", run("deregister_replay_consistent", c) is None)
c.last_event = {"watermarks": []}
check("注销基线缺 generation 被拦", run("deregister_replay_consistent", c) is not None)

print("F 组：消息面信封与媒体形状")


def page_body(**over):
    body = {
        "talker": "G1",
        "count": 1,
        "page": {"hasMore": True, "nextCursor": "1"},
        "messages": [{"platformMessageId": "P1", "sender": "M1", "timestamp": 1790000001, "type": 1,
                      "content": "hi", "media": {"type": "image", "fileName": "a.jpg", "md5": "aa"}}],
    }
    body.update(over)
    return body


c = ctx_with(page_body())
for n in ("chatlab_envelope_page_keys", "media_shape_in_pull"):
    check(n + " 通过合法响应", run(n, c) is None)

check("信封里出现 success 被拦",
      run("chatlab_envelope_page_keys", ctx_with(page_body(success=True))) is not None)
check("count 与本页条数不一致被拦",
      run("chatlab_envelope_page_keys", ctx_with(page_body(count=3))) is not None)
check("缺 page 块被拦",
      run("chatlab_envelope_page_keys", ctx_with(page_body(page=None))) is not None)
check("hasMore 为真却没有 nextCursor 被拦",
      run("chatlab_envelope_page_keys",
          ctx_with(page_body(page={"hasMore": True, "nextCursor": None}))) is not None)
check("排空后 nextCursor 非 null 被拦",
      run("chatlab_envelope_page_keys",
          ctx_with(page_body(page={"hasMore": False, "nextCursor": "1"}))) is not None)
check("排空后 nextCursor 为 null 时通过",
      run("chatlab_envelope_page_keys",
          ctx_with(page_body(page={"hasMore": False, "nextCursor": None}))) is None)

b = page_body()
b["messages"][0]["media"] = {"type": "image", "fileName": "a.jpg", "md5": None}
check("media.md5 为 null 被拦", run("media_shape_in_pull", ctx_with(b)) is not None)
b = page_body()
b["messages"][0]["media"] = {"type": "image", "fileName": "a.jpg", "size": 12}
check("media 多出未约定的键被拦", run("media_shape_in_pull", ctx_with(b)) is not None)
b = page_body()
b["messages"][0]["media"] = None
check("media 为 null 被拦（无媒体应省略整键）", run("media_shape_in_pull", ctx_with(b)) is not None)
b = page_body()
b["messages"][0].pop("media")
check("无 media 键时通过", run("media_shape_in_pull", ctx_with(b)) is None)
b = page_body()
b["messages"][0]["media"] = {"type": "image", "fileName": ""}
check("fileName 为空串时通过（没有名字不等于形状错）",
      run("media_shape_in_pull", ctx_with(b)) is None)

print("mediaId 的键集与值形")
b = page_body()
b["messages"][0]["mediaId"] = "deadbeef.jpg"
check("mediaId 与非空 media 键并存时通过", run("media_id_shape_in_pull", ctx_with(b)) is None)
b = page_body()
check("不带 mediaId 时通过（可选键）", run("media_id_shape_in_pull", ctx_with(b)) is None)
b = page_body()
b["messages"][0]["mediaId"] = None
check("mediaId 为 null 被拦（应省略整键）", run("media_id_shape_in_pull", ctx_with(b)) is not None)
b = page_body()
b["messages"][0]["mediaId"] = ""
check("mediaId 为空串被拦", run("media_id_shape_in_pull", ctx_with(b)) is not None)
b = page_body()
b["messages"][0]["mediaId"] = True
check("mediaId 为 bool 被拦（bool 是 int 子类、也要挡）", run("media_id_shape_in_pull", ctx_with(b)) is not None)
b = page_body()
b["messages"][0].pop("media")
b["messages"][0]["mediaId"] = "x.jpg"
check("有 mediaId 却无 media 键被拦（矛盾态）", run("media_id_shape_in_pull", ctx_with(b)) is not None)


print("未登记的名字必须被报出")
check("unknown() 能报出未登记项", inv.unknown(["envelope_five_blocks", "no_such_one"]) == ["no_such_one"])

print("执行器端到端（桩 harness）：执行器少做一步时用例必须能看见")
# 直接调不变量函数看不见执行器的缺陷——「call 分支丢回显」正是这样溜过两道门的。
# 这里用桩 harness 走一遍完整的 run_case：断言两个世界的差异都被如实报告。
import http.server
import json
import threading
import run as runner_mod


def _stub_body(**over):
    """桩的固定 GET 响应：合法信封 + 进度游标在场（模拟已声明 opaqueCursor 的服务）。"""
    body = envelope()
    body["sync"] = {"hasMore": False, "nextSince": 1790000001, "nextOffset": 0,
                    "nextCursor": "opaque-stub-1"}
    body.update(over)
    return body


def _run_case_against_stub(case_ops, responses, fixture_over=None, post_responses=None, seen=None, requires=None):
    """对桩跑一条完整用例。responses：请求路径（不含查询串）→ 响应字典
    （缺省 _stub_body），供各「坏世界」注入畸形响应。fixture_over 覆盖夹具段，
    post_responses 按路径回固定 JSON（缺省仍走 harness 动作桩），seen 收集实际请求，
    requires 原样带进用例（跳过条件的回归靠它）。返回 (result, ctx)。"""

    class _Stub(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n))
            path = self.path.split("?")[0]
            if seen is not None:
                seen.append(("POST", path, payload))
            if post_responses and path in post_responses:
                out = post_responses[path]
            else:
                out = {"success": True}
                if payload.get("action") == "harness.append_message_at_cursor":
                    out["id"] = "PA"
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if seen is not None:
                seen.append(("GET", path, None))
            spec = responses.get(path, {})
            if "raw" in spec:
                body = spec["raw"]
                ctype = spec.get("ctype", "application/octet-stream")
                status = spec.get("status", 200)
            else:
                body = json.dumps(spec.get("body", _stub_body())).encode()
                ctype = "application/json"
                status = 200
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        fx = {
            "contractVersion": (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip(),
            "platform": "wechat",
            "endpoints": {"pull": "/pull", "harness": "/__harness", "media": "/media/{id}"},
            "slots": {"exported_media": {"id": "whatever"}},
            "capabilities": {"opaqueCursor": True, "mediaById": True},
            "_base_url": "http://127.0.0.1:" + str(port),
        }
        for key, value in (fixture_over or {}).items():
            fx[key] = value
        case = {"id": "stub", "ops": case_ops}
        if requires:
            case["requires"] = requires
        ctx = inv.Ctx(fixture=fx, case=case)
        for slot, spec in fx["slots"].items():
            ctx.variables["slot:" + slot] = spec["id"]
        return runner_mod.run_case(case, ctx, None), ctx
    finally:
        srv.shutdown()


# 世界一：合法形状——call 回显 save 生效；桩的 GET 恒回 _stub_body，续拉页不含 PA，
# 断言如实报「不可达」。这里验证的是**报得出来**（fail + 原因可定位），
# 而不是桩环境里的通过——通过形态由上游真服务验证。
ops = [
    {"req": {"GET": "{endpoints.pull}", "slot": "g", "query": {"limit": "5000"}},
     "save": {"drained_ids": "$ids", "cursor": "sync.nextCursor"},
     "assert": ["opaque_cursor_presents_on_drain"]},
    {"call": "harness.append_message_at_cursor",
     "args": {"slot": "g", "cursor": "{cursor}"},
     "save": {"appended_id": "id"}},
    {"req": {"GET": "{endpoints.pull}", "slot": "g", "query": {"cursor": "{cursor}", "limit": "5000"}},
     "save": {"continuation_ids": "$ids"},
     "assert": ["cursor_progress_reaches_appended"]},
]
r, _ = _run_case_against_stub(ops, {})
check("执行器路径下 call 回显 save 生效、不可达被如实报出",
      r.status == "fail" and any("不在续拉结果里" in x for x in r.reasons))

# 世界二（M3 回归）：call 的 save 取不到回显键——必须是**用例级 fail**，
# 不能静默 pass（旧执行器在这里直接漏掉），也不能 exit 2。
r3, _ = _run_case_against_stub(
    [{"call": "harness.append_message_at_cursor", "args": {}, "save": {"appended_id": "missing_key"}}],
    {},
)
check("call 的 save 落空转用例 fail（不静默 pass、不 exit 2）",
      r3.status == "fail" and any("save 取不到" in x for x in r3.reasons))

# 世界三（M2 回归）：服务端把 cursor 声明为 null——op1 记 save miss + fail，
# op2 引用 {cursor} 走 CaseError（用例级失败），**不再 exit 2 陪葬整套**。
null_world = {"body": dict(_stub_body(), sync={"hasMore": False, "nextSince": 1, "nextOffset": 0,
                                               "nextCursor": None})}
r4, _ = _run_case_against_stub(
    [
        {"req": {"GET": "{endpoints.pull}", "slot": "g", "query": {"limit": "5000"}},
         "save": {"drained_ids": "$ids", "cursor": "sync.nextCursor"},
         "assert": ["opaque_cursor_presents_on_drain"]},
        {"call": "harness.append_message_at_cursor", "args": {"slot": "g", "cursor": "{cursor}"}},
    ],
    {"/pull": null_world},
)
check("cursor 为 null 时用例级 fail（排空断言 + CaseError，报告完整）",
      r4.status == "fail"
      and any(x.startswith("[exec]") and "None" in x for x in r4.reasons)
      and any(x.startswith("[opaque_cursor_presents_on_drain]") for x in r4.reasons))

# 世界四（M2 回归 · 键在值 null 的变体）：键存在但值是 null——dig 不抛 KeyError、
# 无 save miss，但 op2 的 {cursor} 仍要被 CaseError 拦住，而不是拼出字面量 "None"。
r5, _ = _run_case_against_stub(
    [
        {"req": {"GET": "{endpoints.pull}", "slot": "g", "query": {"limit": "5000"}},
         "save": {"cursor": "sync.nextCursor"}},
        {"req": {"GET": "{endpoints.pull}", "slot": "g",
                 "query": {"cursor": "{cursor}", "limit": "10"}}},
    ],
    {"/pull": null_world},
)
check("键在值 null 时引用它的 op 是用例级 fail（不拼出字面量 None）",
      r5.status == "fail" and any("None" in x for x in r5.reasons))

# 世界五（M4 回归）：同 op 多 save，第一个键落空——第二个变量照常绑定，
# 后续引用不出现「未绑定变量」的 exit 2。
r6, _ = _run_case_against_stub(
    [
        {"req": {"GET": "{endpoints.pull}", "slot": "g", "query": {"limit": "5000"}},
         "save": {"gone": "no.such.key", "cursor": "sync.nextCursor"}},
        {"req": {"GET": "{endpoints.pull}", "slot": "g",
                 "query": {"cursor": "{cursor}", "limit": "10"}}},
    ],
    {},
)
check("同 op 多 save 首键落空不影响其余变量绑定（M4）",
      r6.status == "fail"
      and any("save 取不到" in x for x in r6.reasons)
      and not any("未绑定" in x for x in r6.reasons))

# 世界六（expect: bytes 回归）：media 端点返回真实字节——非 JSON 响应走字节断言，
# 不是 SetupError；Content-Type 为 JSON 的错误信封被不变量拦下。
media_ops = [
    {"req": {"GET": "{endpoints.media}", "slot": "exported_media", "expect": "bytes"},
     "assert": ["media_fetch_bytes_nonempty"]},
]
r7, _ = _run_case_against_stub(media_ops, {"/media/whatever": {"raw": b"\x89PNG\r\n\x1a\n"}})
check("expect:bytes 的非 JSON 响应走字节断言并通过", r7.status == "pass")
r8, _ = _run_case_against_stub(media_ops, {"/media/whatever": {"raw": b'{"success": false}',
                                                              "ctype": "application/json"}})
check("expect:bytes 下 200 的 JSON 错误信封被字节不变量拦下",
      r8.status == "fail" and any("JSON" in x for x in r8.reasons))

# 世界七（fail 优先回归）：op1 断言 fail，op2 触发 SkipCase——最终状态必须是
# fail 而不是被 skip 覆盖。桩缺 harness 端点即可制造后续 SkipCase；
# op1 的 fail 由排空游标缺失产生（桩回没有 nextCursor 的 sync）。
no_harness_fx_ops = [
    {"req": {"GET": "{endpoints.pull}", "slot": "g", "query": {"limit": "5000"}},
     "save": {"cursor": "sync.nextCursor"},
     "assert": ["opaque_cursor_presents_on_drain"]},
    {"call": "harness.append_message_at_cursor", "args": {"slot": "g"}},
]
class _NoHarnessStub(http.server.BaseHTTPRequestHandler):
    """只有 pull、没有 harness 控制端点的桩：call 走 SkipCase。"""
    def log_message(self, *a):
        pass
    def do_GET(self):
        body = json.dumps({"chatlab": {}, "meta": {}, "members": [], "messages": [],
                           "sync": {"hasMore": False, "nextSince": 1, "nextOffset": 0}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

_srv9 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _NoHarnessStub)
_port9 = _srv9.server_address[1]
threading.Thread(target=_srv9.serve_forever, daemon=True).start()
try:
    fx9 = {"contractVersion": (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip(), "platform": "wechat",
           "endpoints": {"pull": "/pull"}, "slots": {},
           "capabilities": {"opaqueCursor": True},
           "_base_url": "http://127.0.0.1:" + str(_port9)}
    ctx9 = inv.Ctx(fixture=fx9, case={"id": "s9", "ops": no_harness_fx_ops})
    r9 = runner_mod.run_case({"id": "s9", "ops": no_harness_fx_ops}, ctx9, None)
finally:
    _srv9.shutdown()
check("op1 fail 后 op2 SkipCase 不覆盖失败状态（fail 优先）",
      r9.status == "fail"
      and any("nextCursor" in x for x in r9.reasons)
      # skip_reason 必须还在：证明 op2 确实走了 SkipCase（缺 harness 端点），
      # 而不是某处提前 return 让用例「自然结束」——那样这条回归就验了个空。
      and "harness" in (r9.skip_reason or ""))


print("")
print("注册表条数：" + str(len(inv.names())))
print("定向媒体导出")
# 句柄要拼进路径段，所以契约限定它是 URL 安全 token；展示名 fileName 可以是平台原名或空串。
b = {"success": True, "mediaId": "digest-abc123.png", "fileName": "语音.png",
     "mediaUrl": "/api/v1/media/digest-abc123.png"}
c = ctx_with(b)
c.fixture["endpoints"] = {"media": "/api/v1/media/{id}"}
c.status = 200
check("定向句柄合法（展示名允许平台原名）", run("targeted_media_export_handle", c) is None)
c.body = {**b, "fileName": ""}
check("展示名为空串也合法", run("targeted_media_export_handle", c) is None)
for wrong in ("", " ", "  .  ", "..", "../bad", "语音.png", "a b.png", "%2e%2e%2fetc", "a&b", "a/b"):
    c.body = {**b, "mediaId": wrong}
    check("拒绝不合规句柄 " + repr(wrong), run("targeted_media_export_handle", c) is not None)
for key, wrong in [("fileName", 7), ("success", False), ("mediaId", None),
                   ("mediaUrl", "https://example.test/media/x?token=secret"),
                   ("mediaUrl", "/api/v1/media/other.png")]:
    c.body = {**b, key: wrong}
    check("拒绝 " + key + "=" + repr(wrong), run("targeted_media_export_handle", c) is not None)
c.body = b
c.status = 500
check("非 200 被拦并报出实际状态", "500" in (run("targeted_media_export_handle", c) or ""))
c.status = 200
for tpl in ("api/v1/media/{id}", "//api/v1/media/{id}", "/api/v1/media/x"):
    c.fixture["endpoints"] = {"media": tpl}
    check("拒绝不可用的 media 模板 " + repr(tpl), run("targeted_media_export_handle", c) is not None)
c.fixture["endpoints"] = {"media": "/api/v1/media/{id}"}

print("JSON body 变量解析")
import run as runner
c.variables = {"target": {"timestamp": 123, "sender": "sample", "a-b": 456}}
check("完整引用保留整数类型", runner.resolve_body({"timestamp": "{target.timestamp}"}, c) == {"timestamp": 123})
check("完整引用保留嵌套对象", runner.resolve_body({"t": "{target}"}, c) == {"t": {"timestamp": 123, "sender": "sample", "a-b": 456}})
check("内嵌引用按字符串替换", runner.resolve_body({"id": "id-{target.sender}"}, c) == {"id": "id-sample"})
check("变量名允许连字符（与 schema 的 varRef 一致）", runner.resolve_body({"n": "{target.a-b}"}, c) == {"n": 456})
check("列表逐项解析", runner.resolve_body(["{target.sender}"], c) == ["sample"])
for bad in ("{missing}", "{target.absent}"):
    try:
        runner.resolve_body(bad, c)
        check("拒绝缺失变量 " + bad, False)
    except runner.CaseError as exc:
        check("拒绝缺失变量 " + bad + " 且报出变量名", bad.strip("{}") in str(exc))
c.variables["target"]["none"] = None
try:
    runner.resolve_body("{target.none}", c)
    check("拒绝 None 值", False)
except runner.CaseError as exc:
    check("拒绝 None 值且报出变量名", "target.none" in str(exc))

c.variables["slot:handle"] = "digest-abc123.png"
for tpl in ("/media/a b/{id}", "/media/语音/{id}"):
    c.fixture["endpoints"] = {"media": tpl}
    try:
        runner.endpoint_path("{endpoints.media}", c, "handle")
        check("坏模板按环境错误报出 " + repr(tpl), False)
    except runner.SetupError:
        check("坏模板按环境错误报出 " + repr(tpl), True)

print("定向导出用例端到端（桩）")
media_case = json.loads((Path(__file__).resolve().parents[1] / "cases/lifecycle/targeted-media-export-fetch.json")
                        .read_text(encoding="utf-8"))
media_fixture = {
    "endpoints": {"media": "/media/{id}", "media_export": "/media/export", "harness": "/__harness"},
    "slots": {"targeted_media": {"id": "@chatroom", "expect": {
        "platformMessageId": "m-1", "sender": "wxid_a", "timestamp": 1700000000}}},
    "capabilities": {"mediaExportByMessage": True, "mediaById": True},
}
seen = []
res, _ctx = _run_case_against_stub(
    media_case["ops"],
    {"/media/digest-abc123.png": {"raw": b"\x89PNG\r\n\x1a\npayload", "ctype": "image/png"}},
    fixture_over=media_fixture,
    post_responses={"/media/export": {"success": True, "mediaId": "digest-abc123.png",
                                      "fileName": "语音.png", "mediaUrl": "/media/digest-abc123.png"}},
    seen=seen,
    requires=media_case["requires"],
)
check("定向导出用例通过（原因 " + repr(res.reasons) + "）", res.status == "pass")
payload = next((pl for (m, _p, pl) in seen if m == "POST"), {})
check("只 POST 导出端点一次", [p for (m, p, _pl) in seen if m == "POST"] == ["/media/export"])
check("请求体保留整数 timestamp", isinstance(payload.get("timestamp"), int)
      and payload.get("timestamp") == 1700000000)
check("请求体带齐三个身份字段", payload.get("talker") == "@chatroom"
      and payload.get("platformMessageId") == "m-1" and payload.get("sender") == "wxid_a")
check("取字节用返回的句柄", [p for (m, p, _pl) in seen if m == "GET"] == ["/media/digest-abc123.png"])

# 只有导出能力、没有按句柄取字节的夹具必须整条跳过，而不是跑到第二步才红。
res, _ctx = _run_case_against_stub(
    media_case["ops"], {}, fixture_over={**media_fixture, "capabilities": {"mediaExportByMessage": True}},
    post_responses={}, seen=[], requires=media_case["requires"],
)
check("缺 mediaById 时整条用例跳过", res.status == "skip")

# 非合规句柄：断言层报错、路径段被编码、第二步照跑（执行器不崩）。
seen = []
res, _ctx = _run_case_against_stub(
    media_case["ops"],
    {},
    fixture_over=media_fixture,
    post_responses={"/media/export": {"success": True, "mediaId": "语音.png",
                                      "fileName": "语音.png", "mediaUrl": "/media/语音.png"}},
    seen=seen,
    requires=media_case["requires"],
)
check("非合规句柄被判负", res.status == "fail"
      and any("targeted_media_export_handle" in reason for reason in res.reasons))
check("非合规句柄仍编码成合法 URL 再发", [p for (m, p, _pl) in seen if m == "GET"]
      == ["/media/%E8%AF%AD%E9%9F%B3.png"])
check("第二步照跑并各自报错", any("media_fetch_bytes_nonempty" in reason for reason in res.reasons))

# 孤立代理字符：`quote` 会抛 UnicodeEncodeError，必须落在用例层而不是崩掉执行器。
seen = []
res, _ctx = _run_case_against_stub(
    media_case["ops"], {}, fixture_over=media_fixture,
    post_responses={"/media/export": {"success": True, "mediaId": "\ud800",
                                      "fileName": "", "mediaUrl": "/media/x"}},
    seen=seen, requires=media_case["requires"],
)
check("孤立代理字符不崩执行器", res.status == "fail"
      and any("不是合法 URL" in reason for reason in res.reasons))
check("孤立代理字符的取字节请求没有发出", not [p for (m, p, _pl) in seen if m == "GET"])

if FAILS:
    print("失败 " + str(len(FAILS)) + " 项：" + "；".join(FAILS))
    sys.exit(1)
print("全部通过")
