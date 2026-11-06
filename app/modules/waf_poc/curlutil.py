"""Rewrite lab curl lines onto a caller-supplied target. No shell."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

SAMPLE_HOST = "curl.ncurity.com"
SAMPLE_IP = "192.168.41.91"

_HOST_RE = re.compile(r"[A-Za-z0-9.-]{1,253}")


@dataclass(frozen=True)
class Target:
    ip: str
    host: str
    scheme: str
    port: int

    @classmethod
    def parse(cls, ip: str, host: str, scheme: str, port: int) -> Target:
        try:
            addr = ipaddress.ip_address(ip.strip())
        except ValueError as exc:
            raise ValueError("IP 주소를 확인해 주세요.") from exc
        cleaned_host = host.strip()
        if _HOST_RE.fullmatch(cleaned_host) is None:
            raise ValueError("Host는 영문, 숫자, 점, 하이픈만 사용할 수 있습니다.")
        if (
            cleaned_host.startswith((".", "-"))
            or cleaned_host.endswith((".", "-"))
            or ".." in cleaned_host
        ):
            raise ValueError("Host 형식을 확인해 주세요.")
        if scheme not in ("http", "https"):
            raise ValueError("프로토콜은 HTTP 또는 HTTPS여야 합니다.")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("포트는 1부터 65535까지입니다.")
        rendered_ip = str(addr)
        return cls(ip=rendered_ip, host=cleaned_host, scheme=scheme, port=port)

    @property
    def resolve_address(self) -> str:
        addr = ipaddress.ip_address(self.ip)
        if addr.version == 6:
            return f"[{addr}]"
        return str(addr)

    @property
    def authority(self) -> str:
        if (self.scheme == "http" and self.port == 80) or (
            self.scheme == "https" and self.port == 443
        ):
            return self.host
        return f"{self.host}:{self.port}"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.authority}"


def rewrite_curl_line(line: str, target: Target) -> str:
    """Replace the lab host, resolve IP, scheme, and port. Payload text stays."""
    resolved = f"{target.host}:{target.port}:{target.resolve_address}"
    for old_port in ("80", "443"):
        line = line.replace(f"{SAMPLE_HOST}:{old_port}:{SAMPLE_IP}", resolved)
    for scheme in ("http", "https"):
        line = line.replace(f"{scheme}://{SAMPLE_HOST}", target.origin)
    return line


def split_bash(command: str) -> list[str]:
    """Split a bash-style command. Inside double quotes, only $ ` " \\ and newline escape."""
    args: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(command)

    def flush() -> None:
        if buf:
            args.append("".join(buf))
            buf.clear()

    while i < n:
        ch = command[i]
        if quote is None:
            if ch in " \t\r\n":
                flush()
                i += 1
                continue
            if ch == "\\":
                if i + 1 < n:
                    buf.append(command[i + 1])
                    i += 2
                    continue
                buf.append(ch)
                i += 1
                continue
            if ch in "\"'":
                quote = ch
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                buf.append(ch)
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and command[i + 1] in "$`\"\\\n":
                nxt = command[i + 1]
                if nxt != "\n":
                    buf.append(nxt)
                i += 2
                continue
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            quote = None
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quote is not None:
        raise ValueError("curl 명령의 따옴표가 닫히지 않았습니다.")
    flush()
    return args


def build_curl_argv(line: str, target: Target, curl_bin: str) -> tuple[str, list[str]]:
    rewritten = rewrite_curl_line(line, target)
    args = split_bash(rewritten)
    if not args or args[0] != "curl":
        raise ValueError("curl 명령만 보낼 수 있습니다.")
    argv = [
        curl_bin,
        "--max-time",
        "20",
        "--connect-timeout",
        "8",
        "-sS",
        "-i",
        "-w",
        "\n[http %{http_code}]\n",
        *args[1:],
    ]
    return rewritten, argv
