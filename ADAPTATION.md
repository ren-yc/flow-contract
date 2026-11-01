# 两仓最小适配层指南

本文件登记 `weflow-server` 与 `qqflow-server` 之间**有意保留**的差异，供跨仓客户端或适配层使用。它不是 bug 清单：每条都是设计选择，改一边不会自动改另一边。

格式：**差异是什么 → 失败模式 → 两仓各自的回归位置**（测试函数名或可搜索断言）。

## 1. SNS（朋友圈）只有 weflow

- **差异**：weflow 有只读 SNS 面（`/api/v1/sns/timeline`、`usernames`、`stats`、`export*`、`media-proxy`）；qqflow 没有这一族（对 qqflow 的 `src` 搜 `sns` 零命中）。
- **失败模式**：适配层把 SNS 当成两仓公共面，对 qqflow 也发 `/api/v1/sns/*` 得到 404 后误判「服务坏了」；或把 weflow 的 SNS 导出当成契约用例要求 qqflow 也通过。
- **回归位置**：weflow `tests/api_smoke.rs::sns_export_folds_traversal_usernames`、`sns_html_export_escapes_display_names_and_links`、`sns_json_export_carries_content_desc_the_html_export_must_read`、`sns_json_export_drops_credential_media_keys`；qqflow 无对应面（缺失本身就是断言）。

## 2. `messageCount` 是 qqflow 群成员面的条件键

- **差异**：qqflow 的 `group-members` 只在 `includeMessageCounts=1` 时给 `messageCount`；不带时**整个键省略**（不是 0）。weflow 的群成员面恒给计数。
- **失败模式**：适配层用 `messageCount == 0` 判「这个群没人发言」，把「没要计数」读成「零条」；或把键的存在性当成固定形状做 schema 校验。
- **回归位置**：qqflow `tests/api_smoke.rs::contacts_and_group_members`（要求计数时出现、不带时整键省略）；weflow `tests/api_smoke.rs::sessions_contacts_group_members`。

## 3. `meta.type` 的推导面

- **差异**：两仓都输出 `group` / `private`，但来源不同——weflow 由会话的 `SessionKind` 决定（SNS 不进这条面）；qqflow 由 `chat_type` ＋ talker 决定（非群会话归 `private`）。
- **失败模式**：适配层从 `id` 前缀或「有没有群号」自行推 `type`，在私聊/公众号/服务号上分叉；或把 `meta.type` 当成与原生消息 `type` 同一套编码。
- **回归位置**：weflow `chatlab_type_uses_the_canonical_enum` 与 `chatlab_type_table_matches_the_published_enum`；qqflow `chatlab_type_is_the_chatlab_code_space_not_local_type`（均在各自 `tests/api_smoke.rs`）。

## 4. 默认端口 5033 / 5032

- **差异**：weflow 默认 `127.0.0.1:5033`（WeFlow 契约端口），qqflow 默认 `127.0.0.1:5032`（QQFlow 习惯端口）；两者都可用 `--port` 覆盖。
- **失败模式**：适配层把 `localhost:5033` 写死给两仓，或把端口当成服务身份的一部分。
- **回归位置**：两仓 `src/config.rs` 的默认值断言（`port == 5033` / `port == 5032`），以及两仓 api 文档的「环境变量／默认值」节。

## 5. SDK 命名与 ts 状态

- **差异**：Rust/Python SDK 的账号面方法名是对称的（`accounts` / `register` / `wait_ready`）；`clients/ts` **未发布到 npm**，只随源码分发，版本可能落后于服务端。
- **失败模式**：适配层假设 `npm install` 能拿到官方 TS 包，或假设 TS 的方法名与 Rust/Python 完全一致；升级服务端后 TS 客户端静默停在旧形状。
- **回归位置**：`clients/rust/tests/behavior.rs` 与 `clients/python/tests/test_behavior.py` 的账号/就绪测试；`clients/ts/README.md` 的「未发布、源码获取」声明。

## 6. 两仓 API 参考文档：骨架已统一，仅内容有差异

- **差异**：两仓 api 参考文档的**骨架已统一**——端点一律用 `### <VERB> <路径> — 说明` 的语义标题体系，无编号节、无 `§1.1` 式文内互引；目录、六块端点模板（请求／参数／示例／响应）同构。真正的差异只在**内容**（哪些端点存在、字段与语义），登记在本文其余各条。
- **失败模式**：跨仓搬运或对照文档时**假设内容相同**——把 weflow 独有的 SNS 面、或两仓不同的字段与取值当成两边都有，照抄后在一侧解析不到，或悄悄拿到不同的形状。
- **回归位置**：两仓 `tests/docs_anchors.rs`（各自锚点与跨文件锚有效）与两仓的文档结构门禁（端点骨架、层级、形态检查）；内容差异以本文其余各条所列的具体测试函数名为准。

## 7. 「不存在」与「存在但没有内容」：按面各自定型

- **差异**：两仓对「这个对象根本不在索引里」与「在，但一条内容都没有」都区分，但各面的取向由它自己的数据来源决定：
  - 消息面（`GET /api/v1/messages`、`GET /chatlab/messages`）：weflow 对未知会话返回 404 统一信封，对「会话列表里有它、但一条消息都没索引到」返回 200 空页（判据是会话名册 ∪ 消息索引的并集）。qqflow 对未知 talker 返回 **200 空列表**（参数校验只验 `talker` 非空，查不到会话直接交空页）——这是本节登记的**长期保留差异**：qqflow 的会话条目只由消息记录建立，没有「名册里有、内容为零」的输入形态，翻转它在它一侧结构上不可表达。
  - 拉取面（`GET /api/v1/sessions/{id}/messages`）：两仓一致，未知会话一律 404（套件用例钉住）。
  - 群成员面（`GET /api/v1/group-members`）：两仓一致，未知群号一律 404。
- **失败模式**：把「404」当致命错误的代码，在 qqflow 的消息面探测会话存在性时会静默得到空页；把「200 空列表」当「会话不存在」的判空，在 weflow 的消息面走不到那个分支（404 直接抛错）。唯一安全的跨仓写法是**先问名册面**（`/api/v1/sessions` 的 `messageCount`、群成员面的 404），再按内容面的 `count`/`hasMore` 读内容，不拿状态码当「有没有内容」的判据。
- **回归位置**：weflow `tests/api_smoke.rs::messages_contract`、`a_listed_session_without_messages_answers_an_empty_page`、`group_members_rejects_an_unknown_chatroom`；qqflow `tests/api_smoke.rs::wrong_talker_returns_empty`，群成员面 404 分支在 `src/server/handlers/group_members.rs`（实现存在，无独立测试函数钉住），未知会话的 404 信封由 `tests/downstream_client.rs::downstream_client_real_db` 覆盖。拉取面由用例 `cursor-unknown-session-404` 与不变量 `unknown_session_404_envelope` 两仓共同钉住。

## 8. 同一个查询参数在两仓写法不同（群成员面的键名与布尔取值）

- **差异**：
  - 会话标识的键名：weflow 的 `GET /api/v1/group-members` **同时**接受 `chatroomId` 与 `talker`（先取前者、再回落后者），参数面是未定型 map，未知键被忽略。qqflow 用类型化参数结构，键名 serde `camelCase`，只认 `chatroomId`／`includeMessageCounts`。
  - 后果是**报错形态**不同：qqflow 收到 snake_case 的 `chatroom_id` 不会说「参数名不对」，必填键保持缺席，得到 400「缺少必填参数 chatroomId」。
  - 布尔取值：weflow 认 `1/true/yes/on`，qqflow 只认 `1/true`。`media=yes` 在 qqflow 侧为假。
  - 媒体类型开关的**方向**相反：qqflow 五个开关是退出制（不传＝开，`image=0` 才关）；weflow 是请求制（`media=1` 不带子开关＝四类都要，带任一子开关＝只给白名单里的那些，文件附件两仓都不进导出）。
- **失败模式**：跨仓复用同一段请求构造代码时三种静默：snake_case 一侧收到 400 而它以为「参数被忽略了」；`yes` 一侧开关没生效、请求按默认形状返回；退出制一侧把「只要图片」写成别的形态，结果是全量导出。三者都不会在响应里点名原因。
- **回归位置**：weflow `tests/api_smoke.rs::sessions_contacts_group_members`、`group_members_accepts_the_talker_alias`、`media_kind_whitelist_serves_only_requested_kinds`；qqflow `tests/api_smoke.rs::contacts_and_group_members`、`messages_media_kind_switches_and_removed_aliases`，`talker` 别名删除（snake_case/别名落 400）由 `tests/downstream_client.rs::downstream_client_real_db` 覆盖。布尔取值与参数键名以两仓 api 文档为准：weflow 见「通用查询参数」节，qqflow 见各端点「参数」表。

---

**维护规则**：新增/删除跨仓差异时，先改本文件，再在两仓 api 文档各加一行指针；两仓实现是否同步以各自的回归位置为准，不以本文档代替测试。
