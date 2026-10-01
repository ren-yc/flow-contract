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

print("未登记的名字必须被报出")
check("unknown() 能报出未登记项", inv.unknown(["envelope_five_blocks", "no_such_one"]) == ["no_such_one"])

print("")
print("注册表条数：" + str(len(inv.names())))
if FAILS:
    print("失败 " + str(len(FAILS)) + " 项：" + "；".join(FAILS))
    sys.exit(1)
print("全部通过")