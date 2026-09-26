# flow-contract

这个仓库是**只放数据**的跨上游契约：上游规范快照、歧义解释记录、断言用例与它们的 schema。
两个上游服务仓库把它以某个 tag clone 到 `./conformance`，在各自的 CI 里执行**同一份用例**。

**仓库里没有可执行产品**：没有 Rust crate、没有 `Cargo.toml`、没有生成代码。
两个上游仓库不依赖它，只是 clone 它。

## 契约的构成（五层）

「契约」不是一份文档，而是**五层各有事实源与强制手段的东西**。改动前先看自己在动哪一层：

| 层 | 回答什么 | 载体 | 事实源 | 怎么强制 |
|---|---|---|---|---|
| ① **规范** | 对齐规范的哪一版？歧义怎么解释？ | `spec/` ＋ [`INTERPRETATION.md`](INTERPRETATION.md) | 上游原文快照（见 [`SOURCES.md`](SOURCES.md)） | tag pin ＋ 校验和 |
| ② **结构** | 有哪些端点 / 字段 / 类型？ | 各上游仓库的 `/openapi.json` | **代码**（从类型定义生成） | schema 校验接入 CI |
| ③ **行为** | 门控 / 幂等 / 游标排他性 / 错误语义 | `cases/` ＋ 各仓库的不变量注册表 | **本仓库** | 两个仓库跑同一份用例 |
| ④ **夹具** | 假库必须提供什么 | [`schema/fixture.schema.json`](schema/fixture.schema.json) | **本仓库** | 各仓库产出的夹具按它校验 |
| ⑤ **客户端** | 下游可以依赖哪些保证 | 各仓库的 SDK | 真实消费方的实践 | SDK 类型 ＋ 测试 |

**两条关键性质**：

- **② 一仓库一份**——两个仓库的端点与字段本来就不同（路由、平台字段、类型码语义）。
  它管**允许不同**的部分。
- **①③④ 必须逐字一致**——它们放本仓库，以 tag pin。它们管**必须相同**的部分。

两者之间还有一份「**允许差异清单**」：哪些地方允许不一样，**本身也是契约的一部分**。
它的机器可读载体是夹具里的 `capabilities`（见下）：缺失的能力由用例**跳过**而不是判失败。

## 三个契约文件

### ① `fixture.json`（每个上游仓库各产出一份，**绝不入库**）

它把**逻辑槽位名**绑定到该平台上的真实会话，于是共享用例里**不出现任何真实标识**。
它还声明端点映射、能力开关，以及（可选的）五通道鉴权探测结果。
格式见 [`schema/fixture.schema.json`](schema/fixture.schema.json)；它含真实平台标识，
因此由各仓库的 harness 在临时目录生成、只喂给执行器，**从不提交**。

### ② `cases/**/*.json`（共享，声明式）

用例是**数据，不是代码**：只做「选哪个不变量 ＋ 绑哪个变量 ＋ 必要时调哪个 harness 动作」。
判断逻辑一律在各仓库执行器的**不变量注册表**里。新增一条断言 = 加一个具名不变量，
而不是往用例里塞表达式。

九个操作：`req` / `save` / `assert` / `loop_until` / `skip_if` / `call` /
`sse_open` / `sse_expect` / `sse_close`。格式见 [`schema/case.schema.json`](schema/case.schema.json)。

**断言只比较结构与关系**——类型、键存在性、集合相等、单调性、唯一性——
**绝不比较具体值**。这一条同时买到两样东西：隐私安全，以及同一份用例可跨平台复用。

### ③ `schema/*.json`

前两者自身的格式定义，供 CI 先校验再执行。

## 怎么用

```bash
# 上游仓库的 CI（公共仓库，HTTPS 直接可拉，无需凭据）
git clone --depth 1 --branch <tag> https://github.com/ren-yc/flow-contract.git conformance

# 本机开发可用 SSH，便于推送
git clone --depth 1 --branch <tag> git@github.com:ren-yc/flow-contract.git conformance
```

`./conformance` 应当进上游仓库的 `.gitignore`。执行方式见各仓库的一致性测试。

## 版本与 pin

- [`VERSION`](VERSION) 与 git tag **必须一致**（tag = `v` ＋ 该文件内容）。
- 执行器会校验所 pin 的 tag 与 `VERSION` 一致，**不一致直接失败**——
  因此不可能只升一边。
- 变更流程：① 在本仓库提 PR → ② 打 tag → ③ **两个上游仓库各一个 PR** 同步升 pin。
- 破坏性契约变更（改断言、改 schema、改能力清单）需要 minor 或 major 级的 tag。

## 许可

- **`spec/**`**：第三方内容，**AGPL-3.0**，版权归上游项目所有——见 [`spec/NOTICE`](spec/NOTICE)；
- **其余内容**（用例、schema、执行器、解释记录、脚本）：**MIT**——见 [`LICENSE`](LICENSE)。

## 目录

```text
flow-contract/
├─ VERSION              # 与 git tag 一致
├─ AGENTS.md            # 仓库自有规则
├─ AGENTS-common.md     # 公共段权威副本（两个上游仓库内嵌同一份）
├─ INTERPRETATION.md    # 规范歧义的解释记录
├─ SOURCES.md           # 快照来源与校验和
├─ SOURCES.sha256       # 四份快照的摘要
├─ spec/                # 上游规范原文快照（AGPL-3.0）
├─ cases/               # 断言用例（数据）
├─ schema/              # 用例与夹具的格式定义
├─ runner/              # 纯 stdlib Python 的执行器、不变量注册表与校验工具
└─ scripts/             # 仓库自身的门禁脚本
```

## 本仓库自己的门禁

CI 只做三件事（这里不跑任何产品代码）：

1. **快照完整性**——`spec/` 必须与 `SOURCES.sha256` 逐字一致；手改快照会让「上游说了什么」
   这个证据失效，规范歧义应当写进 `INTERPRETATION.md`；
2. **隐私门**——按文件类型分级扫描，见 [`scripts/check_privacy.py`](scripts/check_privacy.py) 头部；
3. **执行器自测与用例静态校验**——不变量注册表是判断逻辑的唯一出处，它自己写错了没有
   任何东西会拦；用例校验则把「引用了不存在的不变量/能力/端点」提前挡下。

```bash
python runner/selftest.py       # 不变量：该过的过、该拦的拦
python runner/check_cases.py    # 用例：引用的东西都存在、id 唯一
python scripts/check_privacy.py --tree
```
