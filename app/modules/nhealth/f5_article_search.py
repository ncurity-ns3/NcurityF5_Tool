"""Find the myF5 K article that names a CVE.

myF5 search is the public Coveo index the site uses. A hit is kept only when
that article text contains the CVE id.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import httpx

_ARTICLE_RE = re.compile(r"/article/(K\d{5,})", re.I)
_MYF5 = "https://my.f5.com/manage/s/"
_AURA = "https://my.f5.com/manage/s/sfsites/aura?r=1&aura.ApexAction.execute=1"
_SEARCH_HUB = "myF5"
_WORKERS = 8
_TOKEN: tuple[str, str, float] | None = None
_TOKEN_LOCK = threading.Lock()
_ADVISORY_QUERY = '@f5_document_type=="Security Advisory"'


@dataclass(frozen=True)
class KDocument:
    label: str
    url: str
    details: str
    title: str = ""


def document_for_cve(cve: str, results: list[dict]) -> KDocument | None:
    """Pick the K article whose own text names this CVE."""
    wanted = cve.upper()
    ranked: list[tuple[bool, bool, KDocument]] = []
    for item in results:
        document = document_from_item(item)
        if document is None:
            continue
        title = str(item.get("title") or "")
        excerpt = str(item.get("excerpt") or "")
        blob = f"{title} {excerpt} {document.details}".upper()
        if wanted not in blob:
            continue
        kind = _document_type(item)
        ranked.append((wanted in title.upper(), "security advisory" in kind, document))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def document_from_item(item: dict) -> KDocument | None:
    uri = str(item.get("clickUri") or item.get("uri") or "")
    match = _ARTICLE_RE.search(uri)
    if not match:
        return None
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    details = str(raw.get("sfdetails__c") or "")
    if not details:
        details = str(item.get("excerpt") or "")
    return KDocument(
        match.group(1).upper(),
        uri.split("?", 1)[0],
        details,
        str(item.get("title") or ""),
    )


def search_documents(query: str, *, aq: str = "", limit: int = 20) -> list[dict]:
    """Coveo hits for one query. Raises when the K index cannot be read."""
    platform, token = _coveo_token()
    collected: list[dict] = []
    first = 0
    total: int | None = None
    while first < limit and (total is None or first < total):
        body: dict[str, object] = {
            "q": query,
            "searchHub": _SEARCH_HUB,
            "numberOfResults": min(20, limit - first),
            "firstResult": first,
        }
        if aq:
            body["aq"] = aq
        response = httpx.post(
            platform.rstrip("/") + "/rest/search/v2",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=25.0,
        )
        if response.status_code != 200:
            raise RuntimeError(f"K 문서 검색에 실패했습니다. ({response.status_code})")
        payload = response.json()
        if not isinstance(payload, dict):
            break
        results = payload.get("results") or []
        if not isinstance(results, list) or not results:
            break
        collected.extend(item for item in results if isinstance(item, dict))
        total = int(payload.get("totalCount") or len(collected))
        first += len(results)
    return collected


def advisory_query() -> str:
    return _ADVISORY_QUERY


def article_from_results(cve: str, results: list[dict]) -> tuple[str, str]:
    wanted = cve.upper()
    for item in results:
        uri = str(item.get("clickUri") or item.get("uri") or "")
        match = _ARTICLE_RE.search(uri)
        if not match:
            continue
        blob = f"{item.get('title', '')} {item.get('excerpt', '')}".upper()
        if wanted not in blob:
            continue
        return match.group(1).upper(), uri.split("?", 1)[0]
    return "", ""


def find_f5_articles(
    cves: list[str],
    cache_dir: Path,
    on_progress=None,
) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    pending: list[str] = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for cve in dict.fromkeys(cves):
        cached = _read_cache(cache_dir / f"{cve}.json")
        if cached is None:
            pending.append(cve)
        else:
            found[cve] = cached
    if not pending:
        return found
    try:
        platform, token = _coveo_token()
    except Exception:
        return found
    total = len(cves)
    done = total - len(pending)
    if on_progress is not None and done:
        on_progress(done, total)

    def lookup(cve: str) -> tuple[str, tuple[str, str]]:
        try:
            label, url = _search_one(platform, token, cve)
        except Exception:
            return cve, ("", "")
        if label and url:
            _write_cache(cache_dir / f"{cve}.json", label, url)
        return cve, (label, url)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(lookup, cve) for cve in pending]
        for finished in as_completed(futures):
            cve, article = finished.result()
            if article[0]:
                found[cve] = article
            done += 1
            if on_progress is not None and (done == total or done % 8 == 0):
                on_progress(done, total)
    return found


def _search_one(platform: str, token: str, cve: str) -> tuple[str, str]:
    response = httpx.post(
        platform.rstrip("/") + "/rest/search/v2",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"q": f'"{cve}"', "searchHub": _SEARCH_HUB, "numberOfResults": 8},
        timeout=20.0,
    )
    if response.status_code != 200:
        return "", ""
    body = response.json()
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return "", ""
    return article_from_results(cve, results)


def _document_type(item: dict) -> str:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    kind = raw.get("f5_document_type") or ""
    if isinstance(kind, list):
        return " ".join(str(part) for part in kind).lower()
    return str(kind).lower()


def _coveo_token() -> tuple[str, str]:
    global _TOKEN
    with _TOKEN_LOCK:
        return _coveo_token_locked()


def _coveo_token_locked() -> tuple[str, str]:
    global _TOKEN
    now = time.time()
    if _TOKEN is not None and _TOKEN[2] > now + 60:
        return _TOKEN[0], _TOKEN[1]
    headers = {"User-Agent": "NcurityF5Tool"}
    with httpx.Client(headers=headers, timeout=25.0, follow_redirects=True) as client:
        page = client.get(_MYF5)
        context = _aura_context(page.text)
        if context is None:
            raise RuntimeError("myF5 search context is missing")
        action = {
            "id": "123;a",
            "descriptor": "aura://ApexActionController/ACTION$execute",
            "callingDescriptor": "UNKNOWN",
            "params": {
                "namespace": "",
                "classname": "HeadlessController",
                "method": "getHeadlessConfiguration",
                "params": {},
                "cacheable": False,
                "isContinuation": False,
            },
        }
        response = client.post(
            _AURA,
            data={
                "message": json.dumps({"actions": [action]}),
                "aura.context": json.dumps(context),
                "aura.pageURI": "/s/",
                "aura.token": "undefined",
            },
        )
    payload = response.json()
    raw = payload["actions"][0]["returnValue"]["returnValue"]
    config = json.loads(raw) if isinstance(raw, str) else raw
    platform = str(config["platformUrl"])
    token = str(config["accessToken"])
    _TOKEN = (platform, token, _token_expiry(token))
    return platform, token


def _aura_context(html: str) -> dict | None:
    for match in re.finditer(r'src="(/manage/s/sfsites/l/[^"]+)"', html or ""):
        blob = unquote(match.group(1).split("/l/", 1)[1])
        try:
            data, _end = json.JSONDecoder().raw_decode(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("fwuid") and data.get("loaded"):
            return data
    return None


def _token_expiry(token: str) -> float:
    try:
        part = token.split(".")[1]
        padded = part + "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return float(payload.get("exp") or 0)
    except Exception:
        return 0


def _read_cache(path: Path) -> tuple[str, str] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    label = str(loaded.get("label") or "")
    url = str(loaded.get("url") or "")
    if not label or not url:
        return None
    return label, url


def _write_cache(path: Path, label: str, url: str) -> None:
    path.write_text(json.dumps({"label": label, "url": url}), encoding="utf-8")
