#!/usr/bin/env python3
"""隐私门：本仓库是公开的，而它的输入来自真实聊天数据库。

按**文件类型分级**扫描，避免误伤自己的产物：

  1. `spec/**`      —— **整体跳过**。它是第三方文档原文快照，完整性由 `SOURCES.sha256`
                       保证；对它套数字规则会把官方示例里的数字全判成违规。
  2. `*.sha256` / `LICENSE` —— 跳过「长十六进制串」规则：校验和文件按定义就是摘要，
                       许可正文按定义就是模板文本。
  3. 代码（`runner/**`、`scripts/**`）—— **只扫密钥前缀与绝对路径，不扫数字**。
                       否则 runner 自己的边界常量与正则字面量会被判死。
  4. 其余（用例、schema、解释记录、说明文档）—— 全规则：平台 id 形态、独立成词的
                       6–12 位数字、密钥形态、长十六进制串、绝对路径。

豁免：确需保留时在**同一行**写 allow-privacy 并说明理由。

用法：
    python scripts/check_privacy.py --tree     # 全量跟踪文件（CI 与收口核查）
    python scripts/check_privacy.py            # staged 新增内容（本地钩子用）

退出码：0 无命中；1 命中；2 扫描未执行（git 取文件列表失败）——**拒绝放行**。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ALLOW = "allow-privacy"

# 平台标识：微信 id 形态。
_R_PLATFORM_ID = re.compile(r"wxid_[A-Za-z0-9_-]{4,}")
# 独立成词的数字串（号码形态）。前后不能再接字母数字，否则会把版本号切一刀。
_R_NUMERIC_ID = re.compile(r"(?<![0-9A-Za-z_])[0-9]{6,12}(?![0-9A-Za-z_])")
# 全规则下的密钥形态：常见前缀、PEM 头、以及长十六进制串。
_R_KEY = re.compile(
    r"sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[0-9a-fA-F]{64}"
)
# 代码分级下只保留「密钥前缀与 PEM 头」：代码里的摘要字面量不该被拦。
_R_KEY_STRICT = re.compile(r"sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
# 本机绝对路径。
# 注意盘符形态前要挡住「字母 + 冒号」：URL 的协议部分会被误判成盘符。
# （示例一律写成占位形态——把真实的字面量写进注释，会被本规则自己命中。）
_R_ABS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![A-Za-z0-9])/(?:home|Users)/[A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    rule: str
    text: str


def _tier(path: str) -> str:
    """返回该文件适用的分级。"""
    p = path.replace("\\", "/")
    if p.startswith("spec/"):
        return "skip-spec"
    if p.endswith(".sha256") or p.startswith("LICENSE"):
        return "skip-digest"
    if p.startswith("runner/") or p.startswith("scripts/"):
        return "code"
    return "data"


def scan_text(path: str, text: str) -> list[Hit]:
    tier = _tier(path)
    if tier == "skip-spec":
        return []
    hits: list[Hit] = []
    # 只有 data 分级才启用「长十六进制串」规则：代码里的摘要字面量、以及校验和
    # 文件本身，都不该被它拦下。早先写反过一次，结果是校验和文件被自己的规则判死。
    key_re = _R_KEY if tier == "data" else _R_KEY_STRICT
    for lineno, line in enumerate(text.splitlines(), 1):
        if _ALLOW in line:
            continue
        if key_re.search(line) or _R_ABS_PATH.search(line):
            hits.append(Hit(path, lineno, "密钥/绝对路径", line.strip()))
            continue
        if tier == "data":
            if _R_PLATFORM_ID.search(line):
                hits.append(Hit(path, lineno, "平台标识", line.strip()))
            elif _R_NUMERIC_ID.search(line):
                hits.append(Hit(path, lineno, "号码形态数字", line.strip()))
    return hits


def _git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0:
        raise RuntimeError("git 命令失败：" + proc.stderr.strip())
    return proc.stdout


def repo_root() -> Path:
    return Path(_git(["rev-parse", "--show-toplevel"]).strip())


def scan_tree() -> list[Hit]:
    root = repo_root()
    hits: list[Hit] = []
    for rel in [f for f in _git(["ls-files"]).splitlines() if f]:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(scan_text(rel, text))
    return hits


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _added_lines(diff: str) -> dict[str, set[int]]:
    added: dict[str, set[int]] = {}
    current: str | None = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            raw = line[4:].strip()
            current = None if raw == "/dev/null" else raw.removeprefix("b/")
            if current is not None:
                added.setdefault(current, set())
            continue
        if line.startswith("@@"):
            m = _HUNK.match(line)
            lineno = int(m.group(1)) if m else 0
            continue
        if current is None or lineno == 0:
            continue
        if line.startswith("+"):
            added[current].add(lineno)
        if line.startswith(("+", " ")):
            lineno += 1
    return added


def scan_staged() -> list[Hit]:
    hits: list[Hit] = []
    for rel, lines in _added_lines(_git(["diff", "--cached", "--unified=0"])).items():
        if not lines:
            continue
        try:
            content = _git(["show", ":0:" + rel])
        except RuntimeError:
            continue
        hits.extend(h for h in scan_text(rel, content) if h.line in lines)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="隐私门（按文件类型分级）")
    ap.add_argument("--tree", action="store_true", help="扫描全部跟踪文件")
    args = ap.parse_args()
    try:
        hits = scan_tree() if args.tree else scan_staged()
    except (RuntimeError, OSError) as e:
        print("[隐私门] 扫描未执行，拒绝放行：" + str(e), file=sys.stderr)
        return 2
    if hits:
        print("检测到疑似隐私内容（" + str(len(hits)) + " 处）：")
        for h in hits:
            print("  " + h.path + ":" + str(h.line) + " [" + h.rule + "] " + h.text[:110])
        print("")
        print("确需保留时在同行写 allow-privacy 并说明理由。")
        return 1
    print("隐私门：无命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
