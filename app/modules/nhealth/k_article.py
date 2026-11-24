"""Read a BIG-IP version's status from an F5 K article, not a release note."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.modules.nhealth.release_catalog import version_sort_key

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:\.\d+)?")
_SEVERITY_RE = re.compile(r"\b(Critical|High|Medium|Low)\b", re.IGNORECASE)
_SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


@dataclass(frozen=True)
class BigipRow:
    product: str
    vulnerable: str
    fixes: str
    severity: str


def article_judgment(details_html: str, version: str) -> tuple[str, str, str]:
    """Return (해당 여부, severity, 해결 버전) from one K article.

    BIG-IP module rows, including BIG-IP APM, are all read. A version still
    inside the vulnerable range is 해당됨. The fix and hotfix lines for that
    train go into the remedy. A selected version that already includes the
    fix is "{fix} Fixed".
    """
    judged = _judged_rows(details_html, version)
    if not judged:
        if products_not_affected(details_html):
            return "해당 없음", "", ""
        return "확인 불가", "", ""
    affected = [item for item in judged if item[0] == "해당됨"]
    if affected:
        return "해당됨", _highest(affected), _join_remedy(affected) or "해결 버전 미출 시"
    fixed = [item for item in judged if item[0].endswith(" Fixed")]
    if fixed:
        best = max(fixed, key=lambda item: version_sort_key(item[0].removesuffix(" Fixed")))
        return best[0], _highest(fixed), _join_remedy(fixed)
    return "해당 없음", _highest(judged), ""


def _judged_rows(details_html: str, version: str) -> list[tuple[str, str, str]]:
    judged: list[tuple[str, str, str]] = []
    for row in bigip_rows(details_html):
        status = _row_status(version, row)
        if not status:
            continue
        judged.append((status, row.severity, _remedy(version, row)))
    return judged


def _remedy(version: str, row: BigipRow) -> str:
    train = _train(version)
    lines: list[str] = []
    for line in row.fixes.split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip()
        cleaned = re.sub(r"(?<=[A-Za-z])\d+$", "", cleaned)
        if re.fullmatch(r"none|n/a|not applicable|will not fix|-", cleaned, re.I):
            continue
        versions = _VERSION_RE.findall(cleaned)
        if versions and any(_train(item) == train for item in versions):
            lines.append(cleaned)
    if not lines:
        return ""
    return f"{row.product}: " + " / ".join(lines)


def _join_remedy(items: list[tuple[str, str, str]]) -> str:
    lines: list[str] = []
    for _status, _severity, remedy in items:
        if remedy and remedy not in lines:
            lines.append(remedy)
    return "\n".join(lines)


def cve_summaries(details_html: str) -> dict[str, str]:
    """English blurb that follows each CVE id in the article."""
    text = re.sub(r"<br\s*/?>", "\n", details_html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    found = list(_CVE_RE.finditer(text))
    summaries: dict[str, str] = {}
    for index, match in enumerate(found):
        start = match.end()
        end = found[index + 1].start() if index + 1 < len(found) else start + 500
        chunk = text[start:end]
        chunk = re.split(
            r"Security Advisory Status|Impact There is no impact",
            chunk,
            maxsplit=1,
        )[0]
        summaries.setdefault(match.group(0).upper(), " ".join(chunk.split()))
    return summaries


def cve_ids(details_html: str) -> list[str]:
    found: list[str] = []
    for match in _CVE_RE.finditer(details_html):
        cve = match.group(0).upper()
        if cve not in found:
            found.append(cve)
    return found


def products_not_affected(details_html: str) -> bool:
    text = re.sub(r"<[^>]+>", " ", details_html)
    text = re.sub(r"\s+", " ", text).lower()
    return (
        "f5 products are not affected" in text
        or "no f5 products were found to be vulnerable" in text
    )


def bigip_rows(details_html: str) -> list[BigipRow]:
    parser = _Tables()
    parser.feed(details_html)
    rows: list[BigipRow] = []
    for table in parser.tables:
        expanded = _expand(table)
        header = next(
            (
                cells
                for cells in expanded
                if any("fixes introduced" in cell.lower() for cell in cells)
                and any("vulnerable" in cell.lower() for cell in cells)
            ),
            None,
        )
        if header is None:
            continue
        columns = [cell.lower() for cell in header]
        product_at = _column(columns, "product")
        vulnerable_at = _column(columns, "known to be vulnerable")
        fixes_at = _column(columns, "fixes introduced")
        severity_at = _column(columns, "severity")
        for cells in expanded[expanded.index(header) + 1 :]:
            product = _at(cells, product_at)
            if not _is_bigip(product):
                continue
            rows.append(
                BigipRow(
                    product=product,
                    vulnerable=_at(cells, vulnerable_at),
                    fixes=_at(cells, fixes_at),
                    severity=_severity(_at(cells, severity_at)),
                )
            )
    return rows


def _row_status(version: str, row: BigipRow) -> str:
    fixes = [
        item
        for item in _versions(row.fixes)
        if _train(item) == _train(version) and version_sort_key(item) <= version_sort_key(version)
    ]
    if fixes:
        return f"{max(fixes, key=version_sort_key)} Fixed"
    if any(_in_span(version, start, end) for start, end in _spans(row.vulnerable)):
        return "해당됨"
    if re.search(r"not vulnerable", f"{row.fixes} {row.severity}", re.IGNORECASE):
        return "해당 없음"
    return ""


def _versions(cell: str) -> list[str]:
    found: list[str] = []
    for line in cell.split("\n"):
        if "hotfix" in line.lower():
            continue
        match = re.fullmatch(r"(\d+\.\d+\.\d+(?:\.\d+)?)", line.strip())
        if match:
            found.append(match.group(1))
    return found


def _spans(cell: str) -> list[tuple[str, str]]:
    spans: list[tuple[str, str]] = []
    for line in cell.split("\n"):
        if re.search(r"not applicable|not vulnerable|^none$", line.strip(), re.IGNORECASE):
            continue
        versions = _VERSION_RE.findall(line)
        if len(versions) >= 2 and "-" in line:
            spans.append((versions[0], versions[1]))
        elif len(versions) == 1:
            spans.append((versions[0], versions[0]))
    return spans


def _in_span(version: str, start: str, end: str) -> bool:
    selected = version_sort_key(version)
    width = max(len(version_sort_key(start)), len(version_sort_key(end)))
    return version_sort_key(start)[:width] <= selected[:width] <= version_sort_key(end)[:width]


def _train(version: str) -> tuple[int, int]:
    major, minor, *_rest = version.split(".")
    return int(major), int(minor)


def _is_bigip(product: str) -> bool:
    lowered = product.lower()
    return "big-ip" in lowered and "next" not in lowered and "ebpf" not in lowered


def _severity(cell: str) -> str:
    match = _SEVERITY_RE.search(cell)
    if match is None:
        return ""
    return match.group(1).capitalize()


def _highest(items: list[tuple[str, str, str]]) -> str:
    ranked = [item[1] for item in items if item[1] in _SEVERITY_RANK]
    if not ranked:
        return ""
    return min(ranked, key=_SEVERITY_RANK.__getitem__)


def _column(header: list[str], needle: str) -> int:
    for index, cell in enumerate(header):
        if needle in cell:
            return index
    return -1


def _at(cells: list[str], index: int) -> str:
    if index < 0 or index >= len(cells):
        return ""
    return cells[index]


def _expand(rows: list[list[tuple[str, int, int]]]) -> list[list[str]]:
    pending: dict[int, tuple[str, int]] = {}
    expanded: list[list[str]] = []
    for row in rows:
        out: list[str] = []
        column = 0
        index = 0
        while index < len(row) or column in pending:
            if column in pending:
                text, left = pending.pop(column)
                out.append(text)
                if left > 1:
                    pending[column] = (text, left - 1)
                column += 1
                continue
            text, rowspan, colspan = row[index]
            index += 1
            for _offset in range(max(colspan, 1)):
                out.append(text)
                if rowspan > 1:
                    pending[column] = (text, rowspan - 1)
                column += 1
        expanded.append(out)
    return expanded


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, int, int]]]] = []
        self._table: list[list[tuple[str, int, int]]] | None = None
        self._row: list[tuple[str, int, int]] | None = None
        self._cell: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {
                "text": [],
                "rowspan": _span(attr.get("rowspan", "")),
                "colspan": _span(attr.get("colspan", "")),
            }
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append("\n")  # type: ignore[index]

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = "".join(self._cell["text"])  # type: ignore[arg-type]
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r" *\n *", "\n", text).strip()
            self._row.append((text, int(self._cell["rowspan"]), int(self._cell["colspan"])))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)  # type: ignore[index]


def _span(value: str) -> int:
    try:
        return max(int(value), 1)
    except ValueError:
        return 1
