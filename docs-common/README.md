# docs-common：跨仓公共文档模板

本目录放「两个上游仓库共享、只允许一处事实源」的文档模板。目前只有发布手册一份。

两份 `docs/release-runbook.md` 归一化后**仅约十行不同**，差异只在少数几处仓库名、稀疏索引前缀、打包体积数字与一段「yanked 条目」的事故归属。把这部分上提成模板、两仓各用自己的变量渲染，就把「改一处、两边同步」变成机器可验证的重生，而不是靠人记得去两边各改一遍。

## 机制

- **模板**：`docs-common/release-runbook.tpl.md`，公共正文逐字，仓库差异写成 `{{占位符}}`。
- **变量**：各仓的 `docs/release-runbook.vars.toml`（`key = "值"` 的极简形态，注释以 `#` 起）。
- **渲染器**：各仓 `scripts/render_docs_common.py`（两仓同副本），读模板（默认从 `conformance/docs-common/`，随所 pin 的 tag 克隆而来）与变量，写 `docs/release-runbook.md`。
- **防漂移**：CI 跑 `python scripts/render_docs_common.py --check`——把文件与「模板＋变量」重新渲染的结果逐字比对，不同即红。它比逐字哈希更适应本文件（变量随发版而变），且仍能挡住只手改一边。

## 变量清单

| 变量 | 含义 | weflow 值 | qqflow 值 |
|---|---|---|---|
| `SERVER` | 服务 crate 名 | `weflow-server` | `qqflow-server` |
| `CLIENT` | 客户端 crate 名 | `weflow-client` | `qqflow-client` |
| `SDK` | Python 发行包名 | `weflow-sdk` | `qqflow-sdk` |
| `SDK_MOD` | Python 模块名（`src/` 下的包目录） | `weflow_sdk` | `qqflow_sdk` |
| `ENVP` | 环境变量前缀 | `WEFLOW` | `QQFLOW` |
| `IDX_PREFIX` | crates 稀疏索引前四字符（`aa/bb`） | `we/fl` | `qq/fl` |
| `SIBLING` | 姊妹仓名的词干 | `qqflow` | `weflow` |
| `SDIST_ENTRIES` | 本仓 sdist 条目数（每次发版实测填） | `67` | `62` |
| `SDIST_BYTES` | 本仓 wheel 字节数（每次发版实测填） | `129,161` | `121,965` |
| `SIB_ENTRIES` | 姊妹仓 sdist 条目数 | `62` | `67` |
| `SIB_BYTES` | 姊妹仓 wheel 字节数 | `121,965` | `129,161` |
| `CHACHA_NOTE` | 「yanked 条目」那条的事故归属陈述 | 见 vars | 见 vars |
| `CHACHA_IT` | 事故归属后的代词（空 / `它`） | 空 | `它` |

`SDIST_ENTRIES` / `SDIST_BYTES` 每次发版都会变：**发版清单第 1 步就是更新本仓 vars 并重渲染**，否则 `--check` 会在 CI 红。它们不是敏感数字（公开的包体积），进模板变量只是为了让它随变量走而不是手改正文。

## 两仓侧要做的

1. `docs/release-runbook.vars.toml`：填上表中本仓列的值。
2. 渲染：`python scripts/render_docs_common.py` 生成 `docs/release-runbook.md`。
3. CI：`python scripts/render_docs_common.py --check`（失败即红）。

## flow-contract 自己要自证

模板若只在「两仓升 pin」时才被渲染，一个写坏的模板会先绿着进 tag、再在两个仓库同时炸。故本仓库 CI 有一步「双 profile 渲染冒烟」：用 `docs-common/samples/` 下的两份样例变量各渲染一遍，断言无未替换占位符、无空节。

```bash
python scripts/render_docs_common.py --smoke \
  --template docs-common/release-runbook.tpl.md \
  --vars docs-common/samples/weflow.vars.toml
python scripts/render_docs_common.py --smoke \
  --template docs-common/release-runbook.tpl.md \
  --vars docs-common/samples/qqflow.vars.toml
```

## 改模板

改 `release-runbook.tpl.md` 后：① 用两份 samples 冒烟（本仓库 CI 会拦）→ ② 打新 tag → ③ 两仓升 pin 并重渲染。**不要**在两仓里直接改 `docs/release-runbook.md`——那会被 `--check` 判红。
