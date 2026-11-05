from __future__ import annotations

import httpx

K7727_ARTICLE_URL = "https://my.f5.com/manage/s/article/K7727"


def is_internet_available(*, timeout: float = 4.0) -> bool:
    """K7727 License Check Date 확인용 — my.f5.com 접근 가능 여부."""
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=True,
        ) as client:
            response = client.head(K7727_ARTICLE_URL)
            if response.status_code < 500:
                return True
            response = client.get(K7727_ARTICLE_URL)
            return response.status_code < 500
    except Exception:
        return False
