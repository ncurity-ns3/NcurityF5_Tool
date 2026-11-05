import os
import tempfile
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from .archive import build_model_from_path, build_model_from_upload
MAX_UPLOAD_BYTES = 17179869184
def resource_dir() -> Path:
    import sys
    here = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "vpe_viewer"
        if (bundled / "static").is_dir():
            return bundled
    return here
app = Flask(__name__, static_folder=str((resource_dir() / 'static')), static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES
app.config['MAX_FORM_MEMORY_SIZE'] = 16777216
app.config['MAX_FORM_PARTS'] = 32
STATE = {'model': None}
def _store(model: dict):
    STATE['model'] = model
    return model
def _policy_stub(pol: dict) -> dict:
    return {'name': pol.get('name'), 'caption': pol.get('caption'), 'type': pol.get('type'), 'macros': (pol.get('macros') or []), 'virtuals': (pol.get('virtuals') or []), 'start_item': pol.get('start_item')}
def _public_policy(pol: dict) -> dict:
    return {key: value for (key, value) in pol.items() if (key != 'items')}
def _first_policy_name(model: dict) -> (str | None):
    name = model.get('preferred_policy')
    if name:
        return name
    for profile in (model.get('profiles') or []):
        if not (profile.get('virtuals')):
            continue
        return (profile.get('access_policy') or profile.get('name'))
    for pol in (model.get('policies') or []):
        if not (pol.get('type') != 'macro'):
            continue
        if not (pol.get('name')):
            continue
        return pol.get('name')
    return
def _used_objects(policies: list, objects: dict) -> dict:
    used = {}
    for pol in policies:
        for node in (pol.get('nodes') or []):
            for item in ((node.get('irules') or []) + (node.get('references') or [])):
                if not (isinstance(item, dict)):
                    continue
                key = item.get('name')
                if not (key):
                    continue
                if not (key in objects):
                    continue
                if not (key not in used):
                    continue
                used[key] = objects[key]
            for detail in (node.get('agent_details') or []):
                if not (isinstance(detail, dict)):
                    continue
                for key in ('server', 'sso-config', 'resource'):
                    name = detail.get(key)
                    if not (name):
                        continue
                    if not (name in objects):
                        continue
                    if not (name not in used):
                        continue
                    used[name] = objects[name]
    return used
def _client_model(model: dict) -> dict:
    first = _first_policy_name(model)
    bundle = (_policy_bundle(model, first) if first else None)
    bundled = {pol.get('name') for pol in ((bundle or {}).get('policies') or [])}
    policies = []
    for pol in (model.get('policies') or []):
        if (pol.get('name') in bundled):
            policies.append(_public_policy(pol))
            continue
        policies.append(_policy_stub(pol))
    _collected = {}
    for (name, obj) in (model.get('objects') or {}).items():
        if isinstance(obj, dict):
            _collected[name] = obj
    return {'source': model.get('source'), 'extracted_files': (model.get('extracted_files') or []), 'summary': model.get('summary'), 'profiles': (model.get('profiles') or []), 'virtuals': (model.get('virtuals') or []), 'policies': policies, 'objects': _collected, 'preferred_policy': first}
def _all_graphs(model: dict) -> dict:
    policies = [_public_policy(pol) for pol in (model.get('policies') or []) if pol.get('nodes') is not None]
    return {'policies': policies, 'objects': _used_objects(policies, (model.get('objects') or {}))}
def _find_policy(model: dict, name: str) -> (dict | None):
    policies = model.get('policies') or []
    for pol in policies:
        if pol.get('name') == name:
            return pol
    last = str(name or '').rsplit('/', 1)[-1]
    if not last:
        return None
    for pol in policies:
        current = str(pol.get('name') or '')
        if current.endswith('/' + last) or current == last:
            return pol
    return None
def _policy_bundle(model: dict, name: str) -> (dict | None):
    target = _find_policy(model, name)
    if not target:
        return None
    by_name = {pol['name']: pol for pol in (model.get('policies') or []) if pol.get('name')}
    wanted = []
    seen = set()
    def add(policy_name):
        if not policy_name or policy_name in seen:
            return
        pol = by_name.get(policy_name)
        if pol is None:
            return
        seen.add(policy_name)
        if pol.get('nodes') is None:
            from .parser import materialize_policy_graph
            materialize_policy_graph(model, policy_name)
        wanted.append(pol)
        for macro in (pol.get('macros') or []):
            add(macro)
        for node in (pol.get('nodes') or []):
            add(node.get('macro'))
    add(target['name'])
    objects = (model.get('objects') or {})
    used = {}
    for pol in wanted:
        for node in (pol.get('nodes') or []):
            for item in ((node.get('irules') or []) + (node.get('references') or [])):
                key = (item.get('name') if isinstance(item, dict) else None)
                if not (key):
                    continue
                if not (key in objects):
                    continue
                if not (key not in used):
                    continue
                used[key] = objects[key]
    return {'policies': wanted, 'objects': used}
@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')
@app.get('/api/model')
def api_model():
    if STATE['model'] is None:
        return (jsonify({'error': 'no config loaded'}), 404)
    return jsonify(_client_model(STATE['model']))
@app.get('/api/policy')
def api_policy():
    if STATE['model'] is None:
        return (jsonify({'error': 'no config loaded'}), 404)
    name = (request.args.get('name') or '')
    bundle = _policy_bundle(STATE['model'], name)
    if bundle is None:
        return (jsonify({'error': '정책을 찾을 수 없습니다: ' + name}), 404)
    return jsonify(bundle)
@app.get('/api/graphs')
def api_graphs():
    if STATE['model'] is None:
        return (jsonify({'error': 'no config loaded'}), 404)
    return jsonify(_all_graphs(STATE['model']))
@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_exc):
    return (jsonify({'error': '파일이 너무 큽니다. 16GB 이하 qkview/UCS를 올려 주세요.'}), 413)
@app.post('/api/upload')
def api_upload():
    uploaded = request.files.get('file')
    if uploaded is None or not uploaded.filename:
        return (jsonify({'error': 'qkview, ucs 또는 bigip.conf 파일을 선택하세요.'}), 400)
    suffix = Path(uploaded.filename).suffix or '.bin'
    handle, tmp_path = tempfile.mkstemp(prefix='apm-vpe-', suffix=suffix)
    os.close(handle)
    try:
        uploaded.save(tmp_path)
        if os.path.getsize(tmp_path) == 0:
            return (jsonify({'error': '빈 파일입니다.'}), 400)
        try:
            model = build_model_from_path(tmp_path, uploaded.filename)
        except ValueError as exc:
            return (jsonify({'error': str(exc)}), 400)
        except Exception as exc:
            return (jsonify({'error': '분석 실패: ' + str(exc)}), 400)
        _store(model)
        return jsonify({
            'source': model.get('source'),
            'files': model.get('extracted_files') or [],
            'summary': model['summary'],
        })
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
def load_path(path: str) -> dict:
    p = Path(path)
    return _store(build_model_from_path(p, p.name))
def create_app():
    return app
