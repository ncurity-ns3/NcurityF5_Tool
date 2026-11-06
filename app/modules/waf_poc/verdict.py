"""Classify a WAF PoC response and roll the counts up by category."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HTTP_CODE = re.compile(r"\[http (\d{3})\]")
_BLOCK_CODES = {403, 406, 429}
_BLOCK_MARKERS = (
    "request rejected",
    "the requested url was rejected",
    "support id",
)


@dataclass(frozen=True)
class RequestResult:
    group: str
    title: str
    command: str
    http_code: int | None
    outcome: str
    output: str


def classify_response(output: str, *, timed_out: bool, return_code: int) -> tuple[str, int | None]:
    """Return (blocked|passed|failed, http status or None)."""
    codes = [int(match) for match in _HTTP_CODE.findall(output or "")]
    http_code = codes[-1] if codes else None
    if timed_out or http_code is None:
        return "failed", http_code
    folded = (output or "").casefold()
    if http_code in _BLOCK_CODES or any(marker in folded for marker in _BLOCK_MARKERS):
        return "blocked", http_code
    if return_code not in (0, None) and http_code == 0:
        return "failed", http_code
    return "passed", http_code


def summary_rows(results: list[RequestResult]) -> list[tuple[str, int, int, int, int]]:
    """Rows of (group, sent, blocked, passed, failed), plus a total row."""
    order: list[str] = []
    buckets: dict[str, list[int]] = {}
    for item in results:
        if item.group not in buckets:
            order.append(item.group)
            buckets[item.group] = [0, 0, 0, 0]
        counts = buckets[item.group]
        counts[0] += 1
        if item.outcome == "blocked":
            counts[1] += 1
        elif item.outcome == "passed":
            counts[2] += 1
        else:
            counts[3] += 1
    rows = [(name, *buckets[name]) for name in order]
    if rows:
        total = [sum(row[index] for row in rows) for index in range(1, 5)]
        rows.append(("합계", *total))
    return rows


def format_report(results: list[RequestResult]) -> str:
    labels = {"blocked": "차단", "passed": "통과", "failed": "실패"}
    blocks: list[str] = []
    for index, item in enumerate(results, start=1):
        code = "-" if item.http_code is None else str(item.http_code)
        blocks.append(
            "\n".join(
                [
                    f"[{index}] {item.group} · {item.title}",
                    f"결과  {labels.get(item.outcome, item.outcome)}  HTTP {code}",
                    item.command,
                    item.output or "(응답 없음)",
                ]
            )
        )
    return "\n\n".join(blocks)
