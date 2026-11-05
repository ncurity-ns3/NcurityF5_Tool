from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.f5os_client import F5osClient


def test_f5os_authenticate_uses_api_root() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"X-Auth-Token": "test-token"}
    mock_response.content = b'{"ietf-restconf:restconf":{}}'
    mock_response.json.return_value = {"ietf-restconf:restconf": {"data": {}}}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.get.return_value = mock_response

    with patch("app.core.f5os_client.httpx.Client", return_value=mock_client):
        client = F5osClient("192.168.1.1", 443, "admin", "secret")
        body = client.authenticate()

    mock_client.get.assert_called_once()
    called_url = mock_client.get.call_args[0][0]
    assert called_url.endswith("/api")
    assert client._token == "test-token"
    assert "ietf-restconf" in str(body)
