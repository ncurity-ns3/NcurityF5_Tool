from __future__ import annotations
__doc__ = 'Extract bigip.conf text from qkview, UCS, tar, zip, gzip, or raw conf.'
import gzip
import io
import tarfile
import zipfile
from pathlib import Path
CONF_NAMES = {'bigip.conf.gz', 'bigip_user.conf.gz', 'bigip_user.conf', 'bigip.conf'}
SKIP_PATH_MARKERS = ('/diffversions/', '/diffversion/', '.bak', '/backup/', '.old', '/var/log/', '/var/core/', '/shared/images/', '/shared/core/', '/proc/', '/dev/', '/sys/', '/ts/log/')
JUNK_SUFFIXES = ('.so', '.a', '.bin', '.exe', '.dll', '.rpm', '.iso', '.img', '.ko', '.deb', '.zip', '.tgz', '.pcap', '.core', '.out')
def _normalized_path(name: str) -> str:
    return ('/' + name.replace('\\', '/').lower().lstrip('./'))
def _is_snapshot_copy(name: str) -> bool:
    n = _normalized_path(name)
    if ('diffversion' in n):
        return True
    return any(((marker in n) for marker in SKIP_PATH_MARKERS))
def _conf_rank(name: str) -> tuple[int, int, str] | None:
    if _is_snapshot_copy(name):
        return
    n = _normalized_path(name)
    base = n.split('/')[-1]
    depth = n.count('/')
    if (base in frozenset({'bigip.conf.gz', 'bigip.conf'})):
        return (0, depth, n)
    if base.startswith('bigip.conf'):
        return (1, depth, n)
    if (base in frozenset({'bigip_user.conf.gz', 'bigip_user.conf'})):
        return (3, depth, n)
    return (2, depth, n)
def _conf_richness(text: str) -> tuple[int, int, int]:
    return (text.count('ltm virtual '), text.count('ltm rule '), text.count('apm policy '))
def prefer_live_confs(confs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    ranked = []
    for (name, text) in confs:
        rank = _conf_rank(name)
        if rank is None:
            continue
        richness = _conf_richness(text)
        ranked.append((rank[0], rank[1], (-(richness[0]), -(richness[1]), -(richness[2])), rank[2], name, text))
    if not (ranked):
        live = [(name, text) for (name, text) in confs if not (_is_snapshot_copy(name))]
        if live:
            return live[:1]
        return list(confs[:1])
    ranked.sort()
    _group = ranked[0][0]
    _depth = ranked[0][1]
    _rich = ranked[0][2]
    _path = ranked[0][3]
    name = ranked[0][4]
    text = ranked[0][5]
    return [(name, text)]
def _maybe_gunzip(data: bytes) -> bytes:
    if (len(data) >= 2):
        if (data[:2] == b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                pass
                return gz.read()
    return data
def _is_probably_text_conf(data: bytes) -> bool:
    if not (data):
        return False
    if (b'\x00' in data[:2048]):
        return False
    text = data[:200000].decode('utf-8', errors='ignore')
    return (('apm policy' in text) or (('ltm virtual' in text) or (('ltm rule ' in text) or text.lstrip().startswith('#TMSH'))))
def _looks_like_conf_name(name: str) -> bool:
    n = name.replace('\\', '/').lower()
    base = n.split('/')[-1]
    if (base in CONF_NAMES):
        return True
    if ('bigip.conf' in base):
        return True
    return (n.endswith('/bigip.conf') or n.endswith('/bigip.conf.gz'))
def _should_read_member(name: str, size: int, named_only: bool) -> bool:
    if (size <= 0):
        return False
    named = _looks_like_conf_name(name)
    limit = (512000000 if named else 80000000)
    if (size > limit):
        return False
    if _is_snapshot_copy(name):
        return False
    n = _normalized_path(name)
    if any((n.endswith(suffix) for suffix in JUNK_SUFFIXES)):
        return False
    if named_only:
        return named
    base = n.split('/')[-1]
    return (base.endswith('.conf') or (base.endswith('.conf.gz') or base.endswith('.txt')))
def _decode_conf(raw: bytes, named_conf: bool=False) -> str | None:
    data = _maybe_gunzip(raw)
    if not data or b'\x00' in data[:2048]:
        return None
    if named_conf or _is_probably_text_conf(data):
        return data.decode('utf-8', errors='replace')
    return None
def _open_tar(source):
    if isinstance(source, (bytes, bytearray)):
        return tarfile.open(fileobj=io.BytesIO(source), mode='r:*')
    return tarfile.open(source, mode='r:*')
def _member_text(tar: tarfile.TarFile, member: tarfile.TarInfo) -> str | None:
    extracted = tar.extractfile(member)
    if extracted is None:
        return
    name = member.name.replace('\\', '/')
    return _decode_conf(extracted.read(), named_conf=_looks_like_conf_name(name))
def _is_live_bigip(name: str) -> bool:
    rank = _conf_rank(name)
    return bool((rank and (rank[0] == 0)))
def _from_tar(source) -> list[tuple[str, str]]:
    named = []
    scanned = []
    found_live = False
    with _open_tar(source) as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name.replace('\\', '/')
            path = _normalized_path(name)
            if found_live and not path.startswith('/config/'):
                break
            if _should_read_member(name, member.size, named_only=True):
                text = _member_text(tar, member)
                if text:
                    named.append((name, text))
                    if _is_live_bigip(name):
                        found_live = True
                continue
            if named:
                continue
            if not _should_read_member(name, member.size, named_only=False):
                continue
            text = _member_text(tar, member)
            if not text or 'apm policy access-policy' not in text:
                continue
            scanned.append((name, text))
    return named or scanned
def _from_zip(source) -> list[tuple[str, str]]:
    out = []
    opener = (io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    with zipfile.ZipFile(opener) as zf:
        for name in zf.namelist():
            if not (_looks_like_conf_name(name)):
                continue
            text = _decode_conf(zf.read(name), named_conf=True)
            if not (text):
                continue
            out.append((name, text))
    return out
def extract_conf_texts(data: bytes, filename: str='') -> list[tuple[str, str]]:
    if not (data):
        return []
    lower = (filename or '').lower()
    archive_ext = lower.endswith(('.qkview', '.ucs', '.tar', '.tgz', '.gz', '.zip'))
    if not (archive_ext):
        if _is_probably_text_conf(data):
            return [((filename or 'bigip.conf'), data.decode('utf-8', errors='replace'))]
    if not (archive_ext):
        if (data[:2] == b'\x1f\x8b'):
            unpacked = _maybe_gunzip(data)
            if _is_probably_text_conf(unpacked):
                return [((filename or 'bigip.conf'), unpacked.decode('utf-8', errors='replace'))]
    for loader in (_from_tar, _from_zip):
        try:
            found = loader(data)
        except Exception:
            continue
        if found:
            return found
    if (data[:2] == b'\x1f\x8b'):
        if (len(data) <= 8000000):
            unpacked = _maybe_gunzip(data)
            if _is_probably_text_conf(unpacked):
                return [((filename or 'bigip.conf'), unpacked.decode('utf-8', errors='replace'))]
    return []
def extract_conf_texts_from_path(path: str | Path) -> list[tuple[str, str]]:
    p = Path(path)
    for loader in (_from_tar, _from_zip):
        try:
            found = loader(p)
        except Exception:
            continue
        if found:
            return found
    with p.open('rb') as handle:
        head = handle.read(16384)
    if _is_probably_text_conf(_maybe_gunzip(head)):
        return extract_conf_texts(p.read_bytes(), p.name)
    return extract_conf_texts(head, p.name)
def _model_from_confs(confs: list[tuple[str, str]], filename: str='') -> dict:
    from .parser import parse_apm_config
    confs = prefer_live_confs(confs)
    if not (confs):
        raise ValueError('qkview/UCS에서 bigip.conf를 찾지 못했습니다.')
    combined = '\n'.join((text for (_name, text) in confs))
    model = parse_apm_config(combined)
    model['source'] = (filename or confs[0][0])
    model['extracted_files'] = [name for (name, _) in confs]
    return model
def build_model_from_upload(data: bytes, filename: str='') -> dict:
    return _model_from_confs(extract_conf_texts(data, filename), filename)
def build_model_from_path(path: str | Path, filename: str='') -> dict:
    p = Path(path)
    return _model_from_confs(extract_conf_texts_from_path(p), (filename or p.name))
