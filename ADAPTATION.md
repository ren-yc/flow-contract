# 两仓最小适配层指南

本文件登记 `weflow-server` 与 `qqflow-server` 之间**有意保留**的差异，供跨仓客户端或适配层
使用。它不是 bug 清单：每条都是设计选择，改一边不会自动改另一边。

格式：**差异是什么 → 失败模式 → 两仓各自的回归位置**（测试函数名或可搜索断言）。

## 1. SNS（朋友圈）只有 weflow

- **差异**：weflow 有只读 SNS 面（`/api/v1/sns/timeline`、`usernames`、`stats`、`export*`、
  `media-proxy`）；qqflow 没有这一族（对 `qqflow-server` 的 `src` 执行 `grep -ri sns` 零命中）。
- **失败模式**：适配层把 SNS 当成两仓公共面，对 qqflow 也发 `/api/v1/sns/*`，得到 404 后误判
  「服务坏了」；或把 weflow 的 SNS 导出当成契约用例要求 qqflow 也通过。
- **回归位置**：weflow `tests/api_smoke.rs::sns_export_folds_traversal_usernames`、
  `sns_html_export_escapes_display_names_and_links`、
  `sns_json_export_carries_content_desc_the_html_export_must_read`、
  `sns_json_export_drops_credential_media_keys`；qqflow 无对应面（缺失本身就是断言）。

## 2. `messageCount` 是 qqflow 的条件键

- **差异**：qqflow 的 `group-members` 只在 `includeMessageCounts=1` 时给 `messageCount`；
  不带时**整个键省略**（不是 0）。weflow 的群成员面恒给计数。
- **失败模式**：适配层用 `messageCount == 0` 判「这个群没人发言」，把「没要计数」读成「零条」；
  或把键的存在性当成固定形状做 schema 校验。
- **回归位置**：qqflow `tests/api_smoke.rs::contacts_and_group_members`（要求计数时出现、
  不带时整键省略）；weflow `tests/api_smoke.rs::sessions_contacts_group_members`。

## 3. `meta.type` 的推导面

- **差异**：两仓都输出 `group` / `private`，但来源不同——weflow 由会话的 `SessionKind` 决定
  （SNS 不进这条面）；qqflow 由 `chat_type` ＋ talker 决定（非群会话归 `private`）。
- **失败模式**：适配层从 `id` 前缀或「有没有群号」自行推 `type`，在私聊/公众号/服务号上分叉；
  或把 `meta.type` 当成与原生消息 `type` 同一套编码。
- **回归位置**：weflow `tests/api_smoke.rs::chatlab_type_uses_the_canonical_enum` 与
  `chatlab_type_table_matches_the_published_enum`；qqflow
  `tests/api_smoke.rs::chatlab_type_is_the_chatlab_code_space_not_local_type`。

## 4. 默认端口 5033 / 5032

- **差异**：weflow 默认 `127.0.0.1:5033`，qqflow 默认 `127.0.0.1:5032`（两者都可用 `--port`
  覆盖；weflow 的 5033 是 WeFlow 契约端口，qqflow 的 5032 是 QQFlow 习惯端口）。
- **失败模式**：适配层把 `localhost:5033` 写死给两仓，或把端口当成服务身份的一部分。
- **回归位置**：两仓 `src/config.rs` 的默认值断言（weflow `config::tests` 的 `port == 5033`；
  qqflow 同位置的 `port == 5032`），以及两仓 api 文档的「环境变量／默认值」节。

## 5. SDK 命名与 ts 状态

- **差异**：Rust/Python SDK 的账号面方法名是对称的（`accounts` / `register` / `wait_ready`）；
  `clients/ts` **未发布到 npm**，只随源码分发，版本可能落后于服务端。
- **失败模式**：适配层假设 `npm install` 能拿到官方 TS 包，或假设 TS 的方法名与 Rust/Python
  完全一致；升级服务端后 TS 客户端静默停在旧形状。
- **回归位置**：`clients/rust/tests/behavior.rs` 与 `clients/python/tests/test_behavior.py`
  的账号/就绪测试；`clients/ts/README.md` 的「未发布、源码获取」声明。

---

**维护规则**：新增/删除跨仓差异时，先改本文件，再在两仓 api 文档各加一行指针；
两仓实现是否同步以各自的回归位置为准，不以本文档代替测试。
