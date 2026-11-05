from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.f5os_client import F5osClient


def test_first_admin_show_tries_vlan_aliases() -> None:
    client = F5osClient("192.168.1.1", 443, "admin", "secret")
    client._token = "tok"
    calls: list[str] = []

    def fake_run(cmd: str) -> str:
        calls.append(cmd)
        if cmd == "show vlan":
            return "VLAN\nID    INTERFACE\n30    1.0\n"
        return ""

    with patch.object(client, "run_admin_show_command", side_effect=fake_run):
        text = client.first_admin_show("show vlan", "show vlans")

    assert "30    1.0" in text
    assert calls == ["show vlan"]


def test_run_admin_show_command_tries_context_body() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"f5-system-cli:output": "psu-1 ok"}'
    mock_response.json.return_value = {"f5-system-cli:output": "psu-1 ok"}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.post.return_value = mock_response

    client = F5osClient("192.168.1.1", 443, "admin", "secret")
    client._token = "tok"

    with patch("app.core.f5os_client.httpx.Client", return_value=mock_client):
        text = client.run_admin_show_command("show system health summary")

    assert "psu-1" in text
    assert mock_client.post.called
