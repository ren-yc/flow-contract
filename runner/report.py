"""报告：机器可读的 report.json + 人可读的摘要。

为什么两份都要：CI 里人先看摘要（一眼知道哪条挂了、为什么），
而 skip 的**数量与名单**必须落进机器可读的那份——skip 是「没验证」而不是「验证通过」，
它必须能被统计、被对比，否则「全绿」会掩盖一整片没跑的东西。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Result:
    case_id: str
    group: str = ""
    status: str = "pass"          # pass / fail / skip
    reasons: list[str] = field(default_factory=list)
    skip_reason: str = ""
    requests: int = 0


def write_report(
    path: str,
    results: list[Result],
    *,
    base_url: str,
    platform: str,
    contract_version: str,
    cases_total: int,
) -> None:
    payload = {
        "baseUrl": base_url,
        "platform": platform,
        "contractVersion": contract_version,
        "casesTotal": cases_total,
        "passed": sum(1 for r in results if r.status == "pass"),
        "failed": sum(1 for r in results if r.status == "fail"),
        "skipped": sum(1 for r in results if r.status == "skip"),
        "skippedIds": sorted(r.case_id for r in results if r.status == "skip"),
        "results": [
            {
                "id": r.case_id,
                "group": r.group,
                "status": r.status,
                "requests": r.requests,
                "reasons": r.reasons,
                "skipReason": r.skip_reason,
            }
            for r in results
        ],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def summarize(results: list[Result], cases_total: int) -> str:
    passed = sum(1 for r in results if r.status == "pass")
    failed = [r for r in results if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]
    lines = ["用例 " + str(passed) + "/" + str(cases_total) + " 通过，" + str(len(failed)) + " 失败，" + str(len(skipped)) + " 跳过"]
    for r in failed:
        lines.append("  ✗ " + r.case_id)
        for reason in r.reasons:
            lines.append("      " + reason)
    if skipped:
        lines.append("  跳过的用例（**这些没有被验证**）：")
        for r in skipped:
            lines.append("      - " + r.case_id + "：" + r.skip_reason)
    return chr(10).join(lines)
