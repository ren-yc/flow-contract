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

## 2. `messageCount` 是 qqflow 群成员面的条件键

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

## 6. 两仓 API 参考文档的标题体系不逐节对称

- **差异**：qqflow 的 api 参考文档用**编号节**体系（`§1.1` 式文内互引，端点节带 `1.1/3.2` 这类
  号）；weflow 用**语义标题**体系（`### GET /api/v1/xxx — 说明`，无编号）。qqflow 另有「使用
  示例」「注意事项」两节作为独立顶层节，weflow 把对应内容分散在各端点小节里。两仓的
  README／quickstart／mcp／architecture 骨架仍逐段对称，端点全集也都能在各仓 api 文档的端点
  区一眼看全。
- **失败模式**：跨仓搬运或核对文档时，把 `§1.1` 式引用照搬进 weflow（那里没有编号，引用无法
  解析）；或按 qqflow 骨架去找 weflow 的「使用示例」顶层节而找不到，误判「文档缺页」。
- **回归位置**：文档组织无自动化判据——两仓 `tests/docs_anchors.rs` 只保证**各自**锚点有效
  （含跨文件锚），不保证两仓骨架一致；跨仓引用只用「文件名＋语义标题」，不用编号。

## 7. 「不存在」与「存在但没有内容」：按面各自定型

> 本节描述 0.10.0 版「空会话 200 空页」与「未知群 404 守卫」两项落地后的实况。

- **差异**：两仓对「这个对象根本不在索引里」与「在，但一条内容都没有」都区分，但各面的
  取向由它自己的数据来源决定：
  - 消息面（`GET /api/v1/messages`、`GET /chatlab/messages`）：weflow 对未知会话返回 404
    统一信封，对「会话列表里有它、但一条消息都没索引到」返回 200 空页（`count:0`；判据是
    会话名册 ∪ 消息索引的并集；与群成员面的 404 守卫同批落地，此前这类会话一并 404）。
    qqflow 对未知 talker 返回 **200 空列表**（查不到会话直接交空页；参数校验只验
    `talker` 非空）——这是本节登记的**长期保留差异**：qqflow 的会话条目只由消息记录建立，
    没有「名册里有、内容为零」的输入形态，翻转它在它一侧结构上不可表达。
  - 拉取面（`GET /api/v1/sessions/{id}/messages`）：两仓一致，未知会话一律 404（套件用例
    钉住）。
  - 群成员面（`GET /api/v1/group-members`）：两仓一致，未知群号一律 404（weflow 的 404 守卫
    与「空会话 200 空页」同批落地；此前 weflow 该面不做存在性判定、未知群返回 200 空成员表）。
- **失败模式**：把「404」当致命错误的代码，在 qqflow 的消息面探测会话存在性时会静默得到
  空页；把「200 空列表」当「会话不存在」的判空，在 weflow 的消息面走不到那个分支（404 直接
  抛错）。唯一安全的跨仓写法是**先问名册面**（`/api/v1/sessions` 的 `messageCount`、群成员面
  的 404），再按内容面的 `count`/`hasMore` 读内容，不拿状态码当「有没有内容」的判据。
- **回归位置**：weflow `tests/api_smoke.rs::messages_contract`（未知会话 404）、
  `a_listed_session_without_messages_answers_an_empty_page`（列表里有、内容零条 ⇒ 200 空页，
  与守卫同批补）、`group_members_rejects_an_unknown_chatroom`（未知群 404，同批补）；qqflow
  `tests/api_smoke.rs::wrong_talker_returns_empty`（未知 talker ⇒ 空页）、群成员面 404 分支
  （`group_members.rs` 的「群聊不存在」；用例随 pin 升级同批补）。拉取面由用例
  `cursor-unknown-session-404` 与不变量 `unknown_session_404_envelope` 两仓共同钉住。

## 8. 同一个查询参数在两仓写法不同（群成员面的键名与布尔取值）

- **差异**：
  - 会话标识的键名：weflow 的 `GET /api/v1/group-members` **同时**接受 `chatroomId` 与
    `talker`（先取前者、再回落后者），参数面是未定型 map，未知键被忽略。qqflow 用类型化
    参数结构，键名 serde `camelCase`，只认 `chatroomId`／`includeMessageCounts`。
  - 后果是**报错形态**不同：qqflow 收到 snake_case 的 `chatroom_id` 不会说「参数名不对」，
    必填键保持缺席，得到 400「缺少必填参数 chatroomId」。
  - 布尔取值：weflow 认 `1/true/yes/on`，qqflow 只认 `1/true`。`media=yes` 在 qqflow 侧为假。
  - 媒体类型开关的**方向**相反：qqflow 五个开关是退出制（不传＝开，`image=0` 才关）；
    weflow 是请求制（`media=1` 不带子开关＝四类都要，带任一子开关＝只给白名单里的那些，
    文件附件两仓都不进导出）。
- **失败模式**：跨仓复用同一段请求构造代码时三种静默：snake_case 一侧收到 400 而它以为
  「参数被忽略了」；`yes` 一侧开关没生效、请求按默认形状返回；退出制一侧把「只要图片」写成
  别的形态，结果是全量导出。三者都不会在响应里点名原因。
- **回归位置**：weflow `tests/api_smoke.rs::sessions_contacts_group_members`（`chatroomId` 形态）、
  `group_members_accepts_the_talker_alias`（别名等价，待补）、
  `media_kind_whitelist_serves_only_requested_kinds`（请求制方向，待补）；qqflow
  `tests/api_smoke.rs::contacts_and_group_members`（camelCase 必填）、
  `group_members_rejects_a_snake_case_parameter_name`（snake_case 落 400，待补）、
  `messages_media_kind_switches_and_removed_aliases`（退出制方向）。布尔取值与参数键名以
  两仓 api 文档为准：weflow 见「通用查询参数」节与群成员参数行，qqflow 见各端点「参数」表
  （如群成员面的 `includeMessageCounts` 行）。

---

**维护规则**：新增/删除跨仓差异时，先改本文件，再在两仓 api 文档各加一行指针；
两仓实现是否同步以各自的回归位置为准，不以本文档代替测试。
