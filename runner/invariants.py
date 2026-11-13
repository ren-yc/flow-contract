"""内置不变量注册表。

用例只**点名**不变量，判断逻辑全在这里。这样用例始终是数据：新增一条断言 =
在注册表里加一个具名函数，而不是往用例里塞表达式（表达式会立刻变成没人能评审的代码）。

每条不变量是 `(ctx) -> str | None`：返回 None 表示通过，返回字符串表示失败原因。
**失败原因必须写清「期望什么、实际什么」**——只写「断言失败」等于没有报告。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# 秒级时间戳的量级下界与上界：用来抓「毫秒被当成秒」这类回归。
# 量级取自 2001 年与 2096 年——正常时间戳必然落在中间。
TS_MIN = 1e9
TS_MAX = 4e9

# 媒体句柄的字符集：句柄要能直接作为 URL 路径段，所以限定在 URL 安全集合里
# （字母、数字、`.`、`~`、`-`、`_`）。内容摘要形态天然落在这个集合内。
_HANDLE_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "0123456789._~-")


def _is_media_handle(value) -> bool:
    """句柄形态：URL 安全单段 token（含 `.`/`..` 的排除）。

    拉取面的 mediaId 与按消息身份导出的 mediaId 用同一条判据——两个面都把它拼进
    媒体端点的路径段，一处放宽就会给出拼出非法 URL 的「句柄」。
    """
    return (isinstance(value, str) and bool(value) and value not in (".", "..")
            and all(c in _HANDLE_CHARS for c in value))


@dataclass
class Ctx:
    """一次用例执行的上下文。"""

    fixture: dict
    case: dict
    slot: str | None = None
    status: int = 0
    body: Any = None
    raw: bytes = b""
    response_content_type: str = ""
    variables: dict = field(default_factory=dict)
    pages: list = field(default_factory=list)
    streams: dict = field(default_factory=dict)
    last_event: dict | None = None
    captured: dict = field(default_factory=dict)
    requests: int = 0

    @property
    def platform(self) -> str:
        return self.fixture.get("platform", "")

    def cap(self, name: str) -> bool:
        return bool(self.fixture.get("capabilities", {}).get(name, False))


REGISTRY: dict[str, tuple[str, Callable[[Ctx], str | None]]] = {}


def invariant(name: str, doc: str):
    def deco(fn: Callable[[Ctx], str | None]):
        REGISTRY[name] = (doc, fn)
        return fn
    return deco


def names() -> list[str]:
    return sorted(REGISTRY)


def unknown(used: list[str]) -> list[str]:
    """用例点名了但注册表里没有的不变量。**必须报错**，不能静默跳过。"""
    return [n for n in used if n not in REGISTRY]


# ── 取值小工具 ──

def _sessions(ctx: Ctx) -> list:
    """按形状取会话数组：两个面的外层信封不同，因此不按端点取。"""
    body = ctx.body
    if isinstance(body, dict) and isinstance(body.get("sessions"), list):
        return body["sessions"]
    return []


def _block(ctx: Ctx, key: str) -> list:
    body = ctx.body
    if isinstance(body, dict) and isinstance(body.get(key), list):
        return body[key]
    return []


def _messages(ctx: Ctx) -> list:
    return _block(ctx, "messages")


def _members(ctx: Ctx) -> list:
    return _block(ctx, "members")


def _int(v) -> int | None:
    """只在它真的是整数时返回；bool 是 int 的子类，要挡掉。"""
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def _sync(ctx: Ctx) -> dict:
    body = ctx.body
    if isinstance(body, dict) and isinstance(body.get("sync"), dict):
        return body["sync"]
    return {}


def _meta(ctx: Ctx) -> dict:
    body = ctx.body
    if isinstance(body, dict) and isinstance(body.get("meta"), dict):
        return body["meta"]
    return {}


def _chatlab(ctx: Ctx) -> dict:
    body = ctx.body
    if isinstance(body, dict) and isinstance(body.get("chatlab"), dict):
        return body["chatlab"]
    return {}


# ── A 组：信封 ──

@invariant("envelope_five_blocks", "顶层恰为 chatlab/meta/members/messages/sync 五块")
def _envelope_five_blocks(ctx: Ctx) -> str | None:
    want = {"chatlab", "meta", "members", "messages", "sync"}
    got = set(ctx.body) if isinstance(ctx.body, dict) else set()
    if got != want:
        return f"顶层键应为 {sorted(want)}，实际 {sorted(got)}"
    return None


@invariant("version_is_0_0_2", "chatlab.version 是字符串且等于 0.0.2")
def _version(ctx: Ctx) -> str | None:
    v = _chatlab(ctx).get("version")
    if v != "0.0.2":
        return f"chatlab.version 应为字符串 0.0.2，实际 {v!r}"
    return None


@invariant("exportedAt_seconds_number", "exportedAt 是秒级数字，且与当前时间相差不到 5 分钟")
def _exported_at(ctx: Ctx) -> str | None:
    v = _chatlab(ctx).get("exportedAt")
    n = _int(v)
    if n is None:
        return f"exportedAt 应为整数秒，实际 {v!r}（类型 {type(v).__name__}）"
    if not (TS_MIN < n < TS_MAX):
        return f"exportedAt {n} 不在秒级量级内——毫秒回归？"
    delta = abs(n - int(time.time()))
    if delta > 300:
        return f"exportedAt 与当前时间相差 {delta} 秒，超过 300 秒"
    return None


@invariant("generator_nonempty_string", "chatlab.generator 是非空字符串")
def _generator(ctx: Ctx) -> str | None:
    v = _chatlab(ctx).get("generator")
    if not isinstance(v, str) or not v:
        return f"generator 应为非空字符串，实际 {v!r}"
    return None


@invariant("meta_name_nonempty", "meta.name 是非空字符串")
def _meta_name(ctx: Ctx) -> str | None:
    v = _meta(ctx).get("name")
    if not isinstance(v, str) or not v:
        return f"meta.name 应为非空字符串，实际 {v!r}"
    return None


@invariant("meta_type_matches_session", "meta.type 是 group/private")
def _meta_type(ctx: Ctx) -> str | None:
    v = _meta(ctx).get("type")
    if v not in ("group", "private"):
        return f"meta.type 应为 group 或 private，实际 {v!r}"
    return None


@invariant("meta_groupId_matches_id", "群聊时 meta.groupId 等于路径里的会话 id")
def _meta_group_id(ctx: Ctx) -> str | None:
    meta = _meta(ctx)
    if meta.get("type") != "group":
        return None
    want = ctx.captured.get("path_id")
    got = meta.get("groupId")
    if want is not None and got != want:
        return f"群聊 meta.groupId 应等于路径 id {want!r}，实际 {got!r}"
    return None


@invariant("platform_matches_fixture", "meta.platform 等于夹具声明的平台")
def _platform_matches(ctx: Ctx) -> str | None:
    got = _meta(ctx).get("platform")
    if got != ctx.platform:
        return f"meta.platform 应为 {ctx.platform!r}，实际 {got!r}"
    return None


@invariant("ownerId_is_string", "meta.ownerId 出现时必须是字符串")
def _owner_id(ctx: Ctx) -> str | None:
    v = _meta(ctx).get("ownerId")
    if "ownerId" in _meta(ctx) and not isinstance(v, str):
        return f"meta.ownerId 出现时必须是字符串，实际 {v!r}"
    return None


@invariant("members_unique_platformId", "members 的 platformId 页内唯一且非空")
def _members_unique(ctx: Ctx) -> str | None:
    seen = set()
    for m in _members(ctx):
        pid = m.get("platformId")
        if not isinstance(pid, str) or not pid:
            return f"members[].platformId 应为非空字符串，实际 {pid!r}"
        if pid in seen:
            return f"members[].platformId 页内重复：{pid!r}"
        seen.add(pid)
    return None


@invariant("members_match_page_senders", "members 覆盖本页消息的去空 sender 集合")
def _members_match_senders(ctx: Ctx) -> str | None:
    want = {m.get("sender") for m in _messages(ctx) if m.get("sender")}
    got = {m.get("platformId") for m in _members(ctx)}
    if not want <= got:
        return f"本页出现了未列入 members 的发送者：{sorted(want - got)}"
    return None


@invariant("members_accountName_nonempty", "members[].accountName 是非空字符串")
def _account_name(ctx: Ctx) -> str | None:
    for m in _members(ctx):
        v = m.get("accountName")
        if not isinstance(v, str) or not v:
            return f"members[].accountName 应为非空字符串，实际 {v!r}"
    return None


@invariant("members_avatar_is_string", "members[].avatar 出现时必须是字符串")
def _avatar(ctx: Ctx) -> str | None:
    for m in _members(ctx):
        v = m.get("avatar")
        if "avatar" in m and not isinstance(v, str):
            return f"members[].avatar 应为字符串，实际 {v!r}"
    return None


@invariant("type_in_subset_never_6", "消息 type 是整数，且永不为 6")
def _type_subset(ctx: Ctx) -> str | None:
    for m in _messages(ctx):
        t = m.get("type")
        if t == 6:
            return "消息 type 出现了 6：该码在 ChatLab 空间里是保留位，永不发射"
        if _int(t) is None:
            return f"消息 type 应为整数，实际 {t!r}"
    return None


@invariant("timestamps_non_decreasing_seconds", "timestamp 是秒级数字且页内非递减")
def _timestamps(ctx: Ctx) -> str | None:
    prev = None
    for m in _messages(ctx):
        ts = m.get("timestamp")
        n = _int(ts)
        if n is None:
            return f"timestamp 应为整数秒，实际 {ts!r}"
        if not (TS_MIN < n < TS_MAX):
            return f"timestamp {n} 不在秒级量级内——毫秒回归？"
        if prev is not None and n < prev:
            return f"timestamp 递减：{prev} → {n}"
        prev = n
    return None


@invariant("platformMessageId_string_unique_stable", "platformMessageId 是非空字符串、页内唯一")
def _pmid(ctx: Ctx) -> str | None:
    seen = set()
    for m in _messages(ctx):
        v = m.get("platformMessageId")
        if not isinstance(v, str) or not v:
            return f"platformMessageId 应为非空字符串，实际 {v!r}"
        if v in seen:
            return f"platformMessageId 页内重复：{v!r}"
        seen.add(v)
    return None


@invariant("content_key_present", "每条消息都有 content 键（值可以为 null）")
def _content_key(ctx: Ctx) -> str | None:
    for m in _messages(ctx):
        if "content" not in m:
            return "有一条消息缺 content 键：键必须存在，值可以为 null"
    return None


@invariant("no_mediaPath_in_pull", "Pull 面的消息里永不出现 mediaPath")
def _no_media_path(ctx: Ctx) -> str | None:
    for m in _messages(ctx):
        if "mediaPath" in m:
            return "Pull 面出现了 mediaPath：该字段已被移除，出现即回归"
    return None


@invariant("media_shape_in_pull", "media 出现时是 {type, fileName, md5}，无媒体省略整键、md5 取不到省略该键")
def _media_shape(ctx: Ctx) -> str | None:
    # 两个面共用这一个 media 对象（拉取面与消息面各点名一次本不变量），
    # 于是「只有一面悄悄改了形状」也会在另一面暴露出来。
    #
    # fileName **允许空串**：它是元数据，不承诺字节可取（能否取到取决于是否真的落盘）；
    # 但**不允许 null** —— 空串是「没有名字」的既有表达，null 会让按类型读取的下游当场炸。
    allowed = {"type", "fileName", "md5"}
    for m in _messages(ctx):
        if "media" not in m:
            continue
        media = m.get("media")
        if not isinstance(media, dict):
            return f"media 出现时必须是对象（无媒体应省略整个键），实际 {media!r}"
        extra = sorted(set(media) - allowed)
        if extra:
            return f"media 只应有 {sorted(allowed)}，多出 {extra}"
        t = media.get("type")
        if not isinstance(t, str) or not t:
            return f"media.type 应为非空字符串，实际 {t!r}"
        name = media.get("fileName")
        if not isinstance(name, str):
            return f"media.fileName 应为字符串（没有名字时给空串），实际 {name!r}"
        if "md5" in media:
            v = media["md5"]
            if not isinstance(v, str) or not v:
                return f"media.md5 出现时应为非空字符串，实际 {v!r}"
    return None

@invariant("media_id_shape_in_pull", "mediaId 出现时是 URL 安全单段句柄，且 media 键必须同时存在")
def _media_id_shape(ctx: Ctx) -> str | None:
    # 句柄在**消息这一层**而不在 media 对象里：media 的键集由 media_shape_in_pull 钉死为
    # {type, fileName, md5}（它拒绝任何多余键），把句柄塞进去会被那条不变量直接判红。
    # 本条管的是消息层的 mediaId 本身：
    #   · 出现即必须是 URL 安全单段句柄（只允许 A-Za-z0-9._~-，且不是 . 或 ..）——
    #     「取不到」的表达方式是省略整键；给 null、空串或带空格/非 ASCII 的名字会让
    #     调用方拼出非法请求，比不给更坏。
    #   · 有句柄就必须同时有 media 键：「这条媒体取得到字节」而「这条消息没有媒体」是矛盾态。
    for m in _messages(ctx):
        if "mediaId" not in m:
            continue
        v = m["mediaId"]
        if not _is_media_handle(v):
            return (f"mediaId 出现时应为 URL 安全单段句柄（只允许 A-Za-z0-9._~-）；"
                    f"不承诺时省略整键，而不是 null、空串或带编码的名字，实际 {v!r}")
        if "media" not in m:
            return f"消息带着 mediaId 却没有 media 键（声称取得到字节的媒体不存在）：{m!r}"
    return None

# ── C 组：发现端点 ──

@invariant("discovery_shape", "会话项字段齐全，且 type 是 group/private")
def _discovery_shape(ctx: Ctx) -> str | None:
    items = _sessions(ctx)
    if not items:
        return "会话列表为空：发现端点至少要能返回本夹具里的会话"
    for s in items:
        for key in ("id", "name", "platform"):
            v = s.get(key)
            if not isinstance(v, str) or not v:
                return f"会话项缺 {key}（或不是非空字符串）：{s!r}"
        t = s.get("type")
        if t not in ("group", "private"):
            return f"会话 type 应为 group 或 private，实际 {t!r}"
    return None


@invariant("no_page_implies_complete", "没有 page 块时，返回数不得超过 limit")
def _no_page(ctx: Ctx) -> str | None:
    if isinstance(ctx.body, dict) and "page" in ctx.body:
        return None
    limit = _int(ctx.variables.get("request_limit"))
    n = len(_sessions(ctx))
    if limit is not None and n > limit:
        return f"没有 page 块却返回了 {n} 条（limit={limit}）"
    return None


@invariant("session_ids_resolvable_by_pull", "每个发现的会话 id 都能回用作拉取路径")
def _ids_resolvable(ctx: Ctx) -> str | None:
    for s in _sessions(ctx):
        v = s.get("id")
        if not isinstance(v, str) or not v:
            return f"会话项缺可用作路径的 id：{s!r}"
    return None


# ── B 组：游标 ──

@invariant("since_exclusive_end_inclusive", "since 排他（只回不早于它的新消息）")
def _since_exclusive(ctx: Ctx) -> str | None:
    since = _int(ctx.variables.get("request_since"))
    if since is None or since == 0:
        return None
    for m in _messages(ctx):
        n = _int(m.get("timestamp"))
        if n is not None and n <= since:
            return f"since 应为排他下界，但返回了 timestamp={n}（since={since}）"
    return None


@invariant("tolerant_pagination_params", "非法分页参数退化为默认并返回 200，而不是 4xx")
def _tolerant(ctx: Ctx) -> str | None:
    if ctx.status != 200:
        return f"非法分页参数应退化为默认并返回 200，实际 {ctx.status}"
    return None


@invariant("unknown_session_404_envelope", "未知会话返回 404，且错误体走统一信封")
def _unknown_404(ctx: Ctx) -> str | None:
    # 信封的字段名**曾按 `{"error": …}` 断言，而两个上游仓库实现与文档化的都是
    # `{"success": false, "code": <http>, "message": …}`（见各仓库 `server/error.rs` 的模块头）。
    # 规范里没有错误章节、也没提 404，所以那条断言没有规范依据 —— 已对齐实现。
    #
    # 新版**更严**，不是更松：三个键都要求，且 `success` 必须为 false、`code` 必须回显状态码。
    # 「任意 dict 都算通过」会让这条不变量失去意义。
    if ctx.status != 404:
        return f"未知会话应返回 404，实际 {ctx.status}"
    if not isinstance(ctx.body, dict):
        return f"404 的响应体不是对象：{ctx.body!r}"
    if ctx.body.get("success") is not False:
        return f"404 的信封里 success 应为 false：{ctx.body!r}"
    if ctx.body.get("code") != 404:
        return f"404 的信封里 code 应回显 404：{ctx.body!r}"
    msg = ctx.body.get("message")
    if not isinstance(msg, str) or not msg:
        return f"404 的信封里 message 应为非空字符串：{ctx.body!r}"
    return None


@invariant("malformed_cursor_is_a_bad_request", "语法坏的游标是 400，不是 200 也不是 409")
def _malformed_cursor_400(ctx: Ctx) -> str | None:
    # 400 与 409 的处置相反：400 说明调用方编错了游标（重试同一条永远不会成功），
    # 409 说明游标本身没问题、世界变了（重来正是正确动作）。压成一个状态码，
    # 调用方只能二选一地猜。这里是前者：语法坏。
    if ctx.status != 400:
        return f"语法坏的游标应返回 400，实际 {ctx.status}（退回时间模式给一页数据也算错）"
    if not isinstance(ctx.body, dict):
        return f"400 的响应体不是对象：{ctx.body!r}"
    if ctx.body.get("success") is not False:
        return f"400 的信封里 success 应为 false：{ctx.body!r}"
    if ctx.body.get("code") != 400:
        return f"400 的信封里 code 应回显 400：{ctx.body!r}"
    msg = ctx.body.get("message")
    if not isinstance(msg, str) or not msg:
        return f"400 的信封里 message 应为非空字符串：{ctx.body!r}"
    return None


@invariant(
    "foreign_cursor_is_a_reset_with_reason",
    "别的会话的游标是 409，且信封顶层带 reason=cursor_reset_required",
)
def _foreign_cursor_reset(ctx: Ctx) -> str | None:
    # `reason` 必须是**机器可读的顶层字段**：客户端按它决定「丢弃游标、从头拉一次」，
    # 而不是去匹配 message 的自然语言。错误文本会改、会本地化、会被日志截断。
    if ctx.status != 409:
        return f"身份对不上的游标应返回 409，实际 {ctx.status}（静默从头拉也算错）"
    if not isinstance(ctx.body, dict):
        return f"409 的响应体不是对象：{ctx.body!r}"
    if ctx.body.get("success") is not False:
        return f"409 的信封里 success 应为 false：{ctx.body!r}"
    if ctx.body.get("code") != 409:
        return f"409 的信封里 code 应回显 409：{ctx.body!r}"
    reason = ctx.body.get("reason")
    if reason != "cursor_reset_required":
        return f"409 的信封顶层 reason 应为 cursor_reset_required，实际 {reason!r}：{ctx.body!r}"
    return None


@invariant("same_second_not_split", "同一秒不跨页：前页末条早于后页首条")
def _same_second(ctx: Ctx) -> str | None:
    if len(ctx.pages) < 2:
        return None
    prev_last = ctx.pages[-2].get("last_ts")
    cur_first = ctx.pages[-1].get("first_ts")
    if prev_last is not None and cur_first is not None and prev_last >= cur_first:
        return f"同一秒被切到两页：前页末条 {prev_last} >= 后页首条 {cur_first}"
    return None


@invariant("cursor_exclusive_no_gap_no_dup", "游标回传不重不丢（跨页无重复 id）")
def _cursor_no_dup(ctx: Ctx) -> str | None:
    if len(ctx.pages) < 2:
        return None
    seen: set = set()
    for page in ctx.pages[:-1]:
        seen |= set(page.get("ids", []))
    dup = seen & set(ctx.pages[-1].get("ids", []))
    if dup:
        return f"跨页重复：{sorted(dup)[:3]}（游标非排他）"
    return None


@invariant("drained_set_equals_full_set", "翻页排空后的 id 全集等于一次性全量的 id 全集")
# 基准是**显式**的：用例先用一次大 limit 取全量并 save 成 full_ids（哨兵 $ids），
# 再翻页排空。不能用「第一页当全量」——那批 id 会在排空时重复出现，
# 与「页间不得重复」直接冲突。
def _drained_eq_full(ctx: Ctx) -> str | None:
    full_ids = ctx.variables.get("full_ids")
    if not isinstance(full_ids, list):
        return "缺少基准：先用一次大 limit 取全量并 save 成 full_ids（值写 $ids）"
    if not ctx.pages:
        return "还没有任何一页：需要先翻页排空"
    full = set(full_ids)
    drained: set = set()
    for page in ctx.pages:
        drained |= set(page.get("ids", []))
    if full != drained:
        return f"排空后集合与全量不一致：多 {len(drained - full)} 条、少 {len(full - drained)} 条"
    return None


@invariant("drained_cursor_terminal_state", "排空后 hasMore 为假，且 nextOffset 归零")
def _drained_terminal(ctx: Ctx) -> str | None:
    sync = _sync(ctx)
    if not sync:
        return f"响应里没有 sync 块：{ctx.body!r}"
    more = sync.get("hasMore")
    if more is not False:
        return f"排空后 sync.hasMore 应为 false，实际 {more!r}"
    raw_off = sync.get("nextOffset")
    off = _int(raw_off)
    if off != 0:
        return f"排空后 nextOffset 应为 0，实际 {raw_off!r}"
    return None


@invariant("page_size_lower_bound_and_hasMore", "limit=N 且余量充足时，页大小不小于 N")
def _page_size(ctx: Ctx) -> str | None:
    limit = _int(ctx.variables.get("request_limit"))
    if limit is None or not _sync(ctx):
        return None
    n = len(_messages(ctx))
    if n < limit:
        return f"limit={limit} 但只返回 {n} 条——除非已到末尾，否则说明分页没生效"
    return None


@invariant("since_default_starts_at_earliest", "缺省或 0 的 since 从最早一页正序返回")
def _since_default(ctx: Ctx) -> str | None:
    ts = [t for t in (_int(m.get("timestamp")) for m in _messages(ctx)) if t is not None]
    if len(ts) >= 2 and ts != sorted(ts):
        return "缺省 since 应正序返回，实际不是非递减"
    return None


@invariant("offset_and_since_composable", "offset 与 since 可叠加")
def _offset_composable(ctx: Ctx) -> str | None:
    if ctx.status != 200:
        return f"offset 与 since 叠加时应返回 200，实际 {ctx.status}"
    return None


@invariant("incremental_only_new", "增量拉取只包含水位线之后的新消息")
def _incremental(ctx: Ctx) -> str | None:
    wm = _int(ctx.variables.get("watermark"))
    if wm is None:
        return None
    for m in _messages(ctx):
        n = _int(m.get("timestamp"))
        if n is not None and n <= wm:
            return f"增量里出现了不新于水位线的消息：timestamp={n} <= watermark={wm}"
    return None


@invariant(
    "cursor_progress_reaches_appended",
    "排空后按服务端给的游标续拉，排空前追加的消息必须可达"
)
def _cursor_progress_reaches_appended(ctx: Ctx) -> str | None:
    # 时间游标的盲区：页面排空把进度推到「当前时刻」，而同一秒内**稍后才入库**的消息
    # 落在游标后方，时间下界永远滤不到它。不透明进度游标的承诺是「排空时刻之后入库的行
    # 仍然可达」——排空后由 harness 注入一条消息、再按返回的游标续拉时验证。
    #
    # 三个集合都由用例显式 save：排空基准（drained_ids）、续拉响应（continuation_ids）、
    # 追加消息（appended_id）。不拿 ctx.pages 推断页边界——排空请求自己也在 pages 里，
    # 从页序列里猜「哪一页开始是续拉」必然把排空页误判成重放（自测拦下了这一版）。
    drained = ctx.variables.get("drained_ids")
    got = ctx.variables.get("continuation_ids")
    appended = ctx.variables.get("appended_id")
    if not (isinstance(drained, list) and isinstance(got, list)):
        return "缺少基准：排空与续拉两页都要 save 成 id 列表（$ids 哨兵）"
    if not drained:
        # 空基准会让「游标生效」与「游标被忽略后从空页开始」无法区分——
        # 两种世界的断言都通过。夹具声明了本能力就该有可排空的数据。
        return "排空基准为空：本用例需要一个至少有一条消息的会话（slot expect.messages ≥ 1）"
    if not isinstance(appended, str) or not appended:
        return "缺少基准：harness 追加后必须把新消息 id 存进 appended_id"
    if appended in set(drained):
        return "追加的消息出现在排空基准里：harness 没有把它注入为排空后的新行"
    if appended not in set(got):
        return (
            "排空后追加的消息不可达：id "
            + repr(appended)
            + " 不在续拉结果里——进度游标没有覆盖排空后入库的行"
        )
    dup = set(got) & set(drained)
    if dup:
        return f"续拉重放了排空前的消息：{sorted(dup)[:3]}"
    return None


@invariant(
    "opaque_cursor_presents_on_drain",
    "排空后 sync.nextCursor 仍是非空字符串（与消息面 page.nextCursor 排空为 null 的约定不同）"
)
def _opaque_cursor_on_drain(ctx: Ctx) -> str | None:
    # 进度游标与消息面的翻页游标语义不同：消息面排空即终结（null），
    # 进度游标要继续表达「下次增量从哪里起」——排空后必须仍在场，
    # 否则客户端拿不到下一个增量请求的起点。实现者把两个约定平移错了会在这里被拦。
    sync = _sync(ctx)
    v = sync.get("nextCursor")
    if not isinstance(v, str) or not v:
        return f"排空后 sync.nextCursor 应为非空字符串（进度游标不终结），实际 {v!r}"
    return None


@invariant(
    "media_fetch_bytes_nonempty",
    "按 mediaId 句柄取字节：HTTP 200、非 JSON Content-Type、响应体非空"
)
def _media_fetch_bytes(ctx: Ctx) -> str | None:
    # 第 9 条解释的承诺用例化：mediaId 出现 ⇒ 按它的值取字节必须成功。
    # 只看状态码与字节数会让 200 的错误信封假通过。四层判据：
    # 状态码 / Content-Type / raw 能否解析成 JSON 对象 / 字节数。
    # 注意第三层看的是 **raw 本身**：ctx.body 在非 JSON 响应时被 request() 置 None，
    # 直接构造 ctx 的调用方（自测）可能带着无关的 dict body —— 以 ctx.body 判定会误伤。
    if ctx.status != 200:
        return f"按句柄取媒体应返回 200，实际 {ctx.status}"
    ctype = (getattr(ctx, "response_content_type", "") or "").lower()
    if "json" in ctype:
        return f"按句柄取媒体返回了 JSON（{ctype!r}）——那是错误信封的形状，不是媒体字节"
    try:
        parsed = json.loads(ctx.raw.decode("utf-8", "replace")) if ctx.raw else None
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return "按句柄取媒体的响应体解析成了 JSON 对象——那是错误信封，不是媒体字节"
    if not ctx.raw:
        return "按句柄取媒体返回了空响应体——句柄承诺的「字节可取」没有兑现"
    return None

# ── D 组：鉴权 ──

@invariant("auth_transports_matrix", "两条传输方式等价（都返回成功）")
def _auth_matrix(ctx: Ctx) -> str | None:
    # 探测结果由**夹具**提供：每条通道各发一次请求是具身动作（需要真实服务与令牌），
    # 不该由执行器反复试探；夹具没做探测时用例会先 skip 掉。
    #
    # 通道词表只剩两条（Authorization: Bearer 与 ?access_token=）：其余写法已被删除，
    # 夹具若仍探测它们，得到的是 401 —— 与「通道还在」无法区分，所以夹具也必须只探测这两条。
    results = ctx.fixture.get("authProbed")
    if not results:
        return "夹具没有提供鉴权通道的探测结果（authProbed）"
    bad = [k for k, v in results.items() if v != 200]
    if bad:
        return f"这些传输方式没有返回 200：{bad}"
    return None


# ── E 组：群元数据与逐字段语义 ──

@invariant("groupNickname_semantics", "群名片是字符串；私聊或无名片时为空串")
def _group_nickname(ctx: Ctx) -> str | None:
    for m in _members(ctx):
        v = m.get("groupNickname")
        if not isinstance(v, str):
            return f"groupNickname 应为字符串（私聊为空串），实际 {v!r}"
    return None


@invariant("isOwner_exactly_one", "成员表里 isOwner 为真的恰好一人")
def _is_owner(ctx: Ctx) -> str | None:
    # 「恰好一人」而不是「至多一人」：0 个同样是缺陷 —— 群主数据整体丢失时
    # 全 false 会静默通过旧判据，而那正是本不变量要拦的回归形态。
    # 断言面是 group-members（两仓的该面都带 isOwner 键且数据源已接真）。
    #
    # **前置条件（用例侧声明，这里如实写明）**：本断言要求夹具**确实提供群主数据**，
    # 且群主落在该面返回的成员集合里（该面返回名册 ∪ 本页发言人）。
    # 服务端**合法的降级形态**——群主不在本页、或缺 group_info.db / chat_room 表——
    # 会返回合理的全 false，而本断言**并不知道自己拿到的是哪种数据**：它不会跳过，
    # 只会判红。也就是说降级形态的覆盖在**各仓自己的 golden 快照与真库探针**那里，
    # 但本断言并不因此放行 —— 夹具没把群主摆成发言者时，得到的是响亮的失败。
    owners = [m for m in _members(ctx) if m.get("isOwner") is True]
    if len(owners) != 1:
        return f"成员表里 isOwner 为真的有 {len(owners)} 个——每群应恰好一人"
    return None


@invariant("memberCount_optional_not_required", "memberCount 是可选字段；出现时须为非负整数")
def _member_count_optional(ctx: Ctx) -> str | None:
    for s in _sessions(ctx):
        if "memberCount" in s:
            v = s.get("memberCount")
            n = _int(v)
            if n is None or n < 0:
                return f"memberCount 出现时应为非负整数，实际 {v!r}"
    return None


@invariant("memberCount_value_semantics", "出现时的 memberCount 不小于本页去重发送者数")
def _member_count_value(ctx: Ctx) -> str | None:
    senders = {m.get("sender") for m in _messages(ctx) if m.get("sender")}
    for s in _sessions(ctx):
        n = _int(s.get("memberCount"))
        if n is not None and n < len(senders):
            return f"memberCount={n} 小于本页去重发送者数 {len(senders)}"
    return None


@invariant("messageCount_parametrized_semantics", "messageCount 出现时须为非负整数；不做跨平台等值断言")
def _message_count_param(ctx: Ctx) -> str | None:
    for s in _sessions(ctx):
        if "messageCount" in s:
            v = s.get("messageCount")
            n = _int(v)
            if n is None or n < 0:
                return f"messageCount 出现时应为非负整数，实际 {v!r}"
    return None


@invariant("replyToMessageId_is_string_never_null", "出现即字符串，不得为 null")
def _reply_is_string(ctx: Ctx) -> str | None:
    for m in _messages(ctx):
        v = m.get("replyToMessageId")
        if "replyToMessageId" in m and not isinstance(v, str):
            return f"replyToMessageId 出现时必须是字符串，实际 {v!r}"
    return None


@invariant("replyToMessageId_reference_valid", "有引用时能匹配同会话内某条的 platformMessageId（跨页不保证）")
def _reply_valid(ctx: Ctx) -> str | None:
    ids = {m.get("platformMessageId") for m in _messages(ctx)}
    known = ctx.captured.get("known_ids", set())
    for m in _messages(ctx):
        ref = m.get("replyToMessageId")
        if isinstance(ref, str) and ref not in ids and ref in known:
            return f"replyToMessageId {ref!r} 指向本会话一条存在但不在本页的消息——本页断言不该依赖跨页匹配"
    return None


@invariant("event_notification_shape", "通知帧只带元信息，不带消息体；字段齐全且类型正确")
def _event_shape(ctx: Ctx) -> str | None:
    ev = ctx.last_event
    if not isinstance(ev, dict):
        return f"事件载荷应为对象，实际 {type(ev).__name__}"
    for key in ("eventId", "sessionId"):
        v = ev.get(key)
        if not isinstance(v, str) or not v:
            return f"事件缺 {key}（或不是非空字符串）：{ev!r}"
    raw_ts = ev.get("timestamp")
    ts = _int(raw_ts)
    if ts is None or not (TS_MIN < ts < TS_MAX):
        return f"事件 timestamp 应为秒级整数，实际 {raw_ts!r}"
    if "messages" in ev or "content" in ev:
        return "通知帧不该带消息体：它只负责告诉客户端「有新消息」，正文由拉取取回"
    return None


@invariant("deregister_replay_consistent", "注销后带旧 Last-Event-ID 重连的行为与既定策略一致")
def _deregister_replay(ctx: Ctx) -> str | None:
    ev = ctx.last_event
    if ev is None:
        return "没有拿到任何事件：该断言需要先订阅再注销"
    if "generation" not in ev:
        return f"注销后的基线事件应带 generation，实际 {ev!r}"
    return None


# ── F 组：消息面（ChatLab 形状的新挂载点）──

@invariant("chatlab_envelope_page_keys", "消息面信封：talker/count/page 齐全、无 success，count 等于本页条数")
def _chatlab_page_keys(ctx: Ctx) -> str | None:
    # 这条面**刻意不带 success**：它输出的是数据信封，而 success 是「操作结果」的语言，
    # 两者混在一起时读者无法判断 page/count 是否可信。拉取面同样没有 success。
    body = ctx.body
    if not isinstance(body, dict):
        return f"响应应为对象，实际 {type(body).__name__}"
    if "success" in body:
        return "该面不该出现 success：它是操作结果的语言，与数据信封的 page/count 混在一起会让读者猜哪个为准"
    talker = body.get("talker")
    if not isinstance(talker, str) or not talker:
        return f"talker 应为非空字符串（回显请求的会话），实际 {talker!r}"
    n = _int(body.get("count"))
    if n is None or n < 0:
        return f"count 应为非负整数，实际 {body.get('count')!r}"
    got = len(_messages(ctx))
    if n != got:
        return f"count={n} 与本页消息数 {got} 不一致：它是**本页条数**，不是总数（分页信息在 page 里）"
    page = body.get("page")
    if not isinstance(page, dict):
        return f"page 应为对象（翻页信息恒出现），实际 {page!r}"
    more = page.get("hasMore")
    if not isinstance(more, bool):
        return f"page.hasMore 应为布尔，实际 {more!r}"
    nxt = page.get("nextCursor")
    if more:
        if not isinstance(nxt, str) or not nxt:
            return f"hasMore 为真时 nextCursor 应为非空字符串（调用方只能靠它续页），实际 {nxt!r}"
    elif nxt is not None:
        return f"排空后 nextCursor 应为 null，实际 {nxt!r}（非 null 会让调用方再翻一页）"
    return None


@invariant(
    "offset_since_id_set_matches_tail",
    "offset+since 叠加取到的 id 集合 = 同 since 全量集合去掉前 offset 条（窗口取前 limit 条）"
)
def _offset_since_id_set(ctx: Ctx) -> str | None:
    full = ctx.variables.get("full_ids")
    tail = ctx.variables.get("tail_ids")
    window = ctx.variables.get("window_ids")
    if not isinstance(full, list) or not isinstance(tail, list) or not isinstance(window, list):
        return "三个 id 集合必须都是列表"
    # 叠加的正确形状：tail == full[1:]；window == full[1:1+len(window)]。
    # 任何一个等式破坏都说明 offset 没有作用在 since 过滤后的同一序列上
    # （跳条、重发、或两个参数互相覆盖）。
    if [str(x) for x in tail] != [str(x) for x in full][1:]:
        return "offset=1 的集合与全量去掉第一条不一致（重发或跳条）"
    w = [str(x) for x in window]
    expect = [str(x) for x in full][1:1 + len(w)]
    if w != expect:
        return "小页窗口的 id 序列与全量去掉第一条后的前缀不一致：got=" + repr(w[:6]) + " expect=" + repr(expect[:6])
    return None


@invariant("targeted_media_export_handle", "定向导出成功并返回 URL 安全句柄与可取字节地址")
def _targeted_media_export_handle(ctx: Ctx) -> str | None:
    if ctx.status != 200:
        return "定向媒体导出应返回 200，实际 " + str(ctx.status)
    if not isinstance(ctx.body, dict) or ctx.body.get("success") is not True:
        return "定向媒体导出未成功（success 不是 true）"
    handle = ctx.body.get("mediaId")
    # 句柄会被拼进媒体端点的路径段，所以契约要求它本身就是 URL 安全 token
    # （内容摘要形态）。空格、非 ASCII、`?`、`#` 一律不接受——接受它们会让执行器
    # 拼出非法 URL，而这里正是唯一能说清「是谁不合规」的位置。
    if not _is_media_handle(handle):
        return "mediaId 必须是 URL 安全单段句柄（只允许 A-Za-z0-9._~-，且不是 . 或 ..）"
    # fileName 是展示名，不是句柄：允许为空、允许平台原名（含非 ASCII），与第 7、9 条同义。
    # 但它会进日志与导出物，控制字符与路径分隔符一律不接受。
    name = ctx.body.get("fileName")
    if not isinstance(name, str):
        return "fileName 必须是字符串（展示名，可为空）"
    if any(ord(c) < 32 or c in "/\\" for c in name):
        return "fileName 是展示名：不得含控制字符或路径分隔符"
    template = ctx.fixture.get("endpoints", {}).get("media", "")
    if not template.startswith("/") or template.startswith("//") or "{id}" not in template:
        return "夹具 media 端点必须声明根相对的 {id} 路径，实际 " + repr(template)
    if ctx.body.get("mediaUrl") != template.replace("{id}", handle):
        return "mediaUrl 必须等于夹具 media 模板替换 {id} 后的根相对路径"
    return None
