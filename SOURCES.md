# 规范来源与校验和

`spec/*.md` 是**上游规范的原文快照**，不是链接。四份都钉在**同一个上游 commit** 上，
以保证「两个上游仓库跑的是同一版规范」。

## 上游

| 项 | 值 |
|---|---|
| 项目 | [ChatLab/ChatLab](https://github.com/ChatLab/ChatLab) |
| 钉住的 commit | `3e0e0fbbfb2b80051d261d34bf8349d64ab4c6e8`（2026-09-24） |
| 抓取日期 | 2026-09-26 |
| 许可 | **AGPL-3.0** —— 见 [`spec/NOTICE`](spec/NOTICE) |

## 快照

| 文件 | 上游路径 | 字节 | 行 | SHA256（前 16 位） |
|---|---|---|---|---|
| `chatlab-format.en.md` | `docs/en/standard/chatlab-format.md` | 11515 | 322 | `aea32885edd056d6` |
| `chatlab-format.cn.md` | `docs/cn/standard/chatlab-format.md` | 13708 | 399 | `ad973a7818b743bf` |
| `chatlab-pull.en.md` | `docs/en/standard/chatlab-pull.md` | 14754 | 351 | `39e6c3acb8a3008f` |
| `chatlab-pull.cn.md` | `docs/cn/standard/chatlab-pull.md` | 15476 | 351 | `a35850933654538c` |

完整校验和在同目录的 `SOURCES.sha256`。

## 怎么核验

```bash
# Linux / CI
sha256sum -c SOURCES.sha256
```

```powershell
# Windows（无 sha256sum 时）
Get-Content SOURCES.sha256 | ForEach-Object {
  $parts = $_ -split '\s+', 2
  $actual = (Get-FileHash (Join-Path 'spec' ($parts[1] -replace '^\*','')) -Algorithm SHA256).Hash.ToLower()
  if ($actual -ne $parts[0]) { "不匹配: $($parts[1])" }
}
```

## 怎么更新

1. **换文件**（用新的 commit 重抓，而不是手改内容）；
2. 更新本文件的 commit / 日期 / 字节 / 校验和，并重新生成 `SOURCES.sha256`；
3. 在 PR 里说明**规范改了什么**——只说「更新快照」等于没说；
4. 打新 tag，并升两个上游仓库的 pin。

## 许可分层

- **`spec/**`**：第三方内容，**AGPL-3.0**（见 [`spec/NOTICE`](spec/NOTICE)）；
- **本仓库其余内容**（用例、schema、runner、解释记录、脚本）：**MIT**，见 [`LICENSE`](LICENSE)。

---

> 快照要改内容时必须走这条流程，**不允许直接编辑 `spec/*.md`**：
> 它是原文快照，改了就不再是「上游说了什么」的证据。规范本身的歧义写进
> [`INTERPRETATION.md`](INTERPRETATION.md)。