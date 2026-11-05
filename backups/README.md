# 프로젝트 백업

정기점검 등 마일스톤마다 ZIP으로 보관합니다.

| 항목 | 내용 |
|------|------|
| 포함 | `app/`, `config/`, `scripts/`, `tests/`, `docs/`, `templates/`, `requirements*.txt`, `pyproject.toml` |
| 제외 | `.venv/`, `output/`, `.pytest_cache/`, `backups/` |

| 백업 파일 | 설명 |
|-----------|------|
| `정기점검완료_YYYYMMDD-HHmm.zip` | 정기점검 마일스톤 |
| `multiple_table_ui_20260526-1828.zip` | Multiple 장비 표 UI 완료 |

생성:

```bat
.\.venv\Scripts\python.exe scripts\create_milestone_backup.py
```

복원: ZIP을 원하는 경로에 풀고 `scripts\setup_dev.cmd` → `scripts\run_gui.cmd`
