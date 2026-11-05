# 신규 채팅 핸드오프 (2026-05-26)

## 마일스톤 백업

| 항목 | 내용 |
|------|------|
| ZIP | `backups/multiple_table_ui_20260526-1828.zip` |
| 생성 | `scripts\create_milestone_backup.py` 또는 `.\.venv\Scripts\python.exe scripts\create_milestone_backup.py` |
| 포함 | `app/`, `config/`, `scripts/`, `tests/`, `docs/`, `templates/`, requirements, pyproject |
| 제외 | `.venv/`, `output/`, `backups/` |

---

## 이번 채팅에서 완료한 것 (Multiple 장비 표 UI)

**상태: 사용자 확인 완료 (“잘 됐다”)**

| 항목 | 내용 |
|------|------|
| 초기 진입 | Multiple 선택 시 **자동 선택 없음** (zebra만) |
| 선택 색 | 활성 행 `#0260EA` + 흰 글자 |
| rSeries 2행 | 클릭한 Stack 행 = `#0260EA`, 같은 장비 다른 행 = `#5C9DF5` + `#E8F2FF` |
| 미선택 zebra | `#FBFDFF` / `#F3F8FD` |
| 비밀번호 | 선택 블록 안에서도 **흰 배경 + 파란 테두리** |
| 스크롤바 | Ncurity `#0260EA` (`theme.polish_widget_scrollbars`) |
| Model 콤보 | hover만 `#0260EA` (현재 항목 기본 하이라이트 없음) |

**핵심 파일**

- `app/gui/widgets/multi_device_table.py` — 블록 선택·색·password 필터
- `app/gui/widgets/device_connection_panel.py` — Single/Multiple, 공통/장비별 계정
- `app/gui/widgets/choice_picker_popup.py` — Model 드롭다운
- `app/gui/theme.py` — 표·스크롤바 QSS
- `docs/prd.md` §3.3 — Multiple 표 요구 (선택 UX는 이번에 커스텀 색으로 구현, PRD “연한 파란” 문구와 다를 수 있음 → 필요 시 PRD 갱신)

**실행**

```bat
scripts\run_gui.cmd
```

**이전 대화 ID (참고):** `f9f7bf2d-591a-4844-b015-ab7d2221ba7d`

---

## 다음 챕터 (권장): OS 업그레이드 간 점검

**기준 문서:** `docs/os_upgrade_check_crd.md` (CRD)

| CRD 단계 | 상태 | 다음 작업 |
|----------|------|-----------|
| M0 메뉴·CRD | ✅ | — |
| M1 Pre/Post 스냅샷 collector | ✅ | — |
| **M2** GUI (Pre/Post Run, job 연결) | ⬜ | `OsUpgradeCheckView` 실화면 |
| M3 diff + HTML | ⬜ | |
| M4 rollback MD | ⬜ | |
| M5 rSeries 통합 테스트 | ⬜ | |

CRD 요약: **업그레이드 실행 없음** — Pre/Post 수집 → diff → rollback 체크리스트. Health Check와 동일 **DeviceConnectionPanel** / Single·Multiple 재사용.

---

## 신규 채팅 — 붙여넣기용 프롬프트

아래 블록을 **그대로** 새 채팅 첫 메시지에 붙이고, `@` 로 파일을 열어 주세요.

```
프로젝트: Ncurity F5 Big-IP Managing Tool (PyQt6, Windows, 오프라인).
워크스페이스: …\F5 Project\Config & Rules & Apps\AI First
실행: scripts\run_gui.cmd

## 완료된 마일스톤 (건드리지 말 것 — 회귀만 주의)
Multiple 모드 장비 목록 표 UI는 완료·백업됨.
- backups/multiple_table_ui_20260526-1828.zip
- docs/handoff_next_chat.md, docs/worklog.md (2026-05-26 항목)
- 핵심: app/gui/widgets/multi_device_table.py
  · Multiple 진입 시 자동 선택 없음
  · rSeries: 클릭 행 #0260EA, 형제 행 #5C9DF5
  · PRD §3.3 표 구조 (iSeries 1행 TMOS, rSeries F5OS+TMOS span)

## 이번 채팅 목표
docs/os_upgrade_check_crd.md (OS Upgrade Check CRD)를 **단일 기준**으로 다음을 진행해줘.

1. CRD §7 로드맵 확인 — M1은 완료, **M2부터** 구현.
2. M2: OsUpgradeCheckView — Pre-check / Post-check Run, job_id 연결, Health Check와 동일 장비 연결 패널 재사용.
3. 명시적 비목표(CRD §2 Out of scope): ISO/install/자동 재부팅/ config push 없음.
4. 산출물 레이아웃: CRD §6 — output/<job_id>/pre_snapshot, post_snapshot, 이후 M3 diff_report.html.
5. 구현 전 CRD와 docs/spec.md §3.5·§4.4, app/modules/os_upgrade/ 현재 코드를 읽고 계획을 짧게 제시한 뒤 코딩.

## 반드시 @ 로 열 파일
- docs/os_upgrade_check_crd.md
- docs/handoff_next_chat.md
- docs/prd.md (§3 장비 연결 — Multiple/Single 공유)
- docs/spec.md (os_upgrade 모듈 IO)
- app/gui/views/os_upgrade_check_view.py (또는 동일 역할 뷰)
- app/modules/os_upgrade/collector.py
- app/gui/views/health_check_view.py (Run/GUI 패턴 참고)
- app/gui/widgets/device_connection_panel.py

## 검증
- pytest: tests/test_os_upgrade_*.py
- GUI: 메뉴 「OS 업그레이드 간 점검」 → Pre Run → output 폴더 확인

한국어로 답하고, 변경은 최소 diff로. 커밋은 요청할 때만.
```

---

## @ 파일 체크리스트 (짧은 버전)

| 파일 | 이유 |
|------|------|
| `docs/os_upgrade_check_crd.md` | **본 CRD** — 범위·M2~M5·산출물 |
| `docs/handoff_next_chat.md` | 이번 핸드오프 |
| `docs/prd.md` | 장비 연결·Multiple 표 |
| `docs/spec.md` | 모듈 IO |
| `app/gui/views/health_check_view.py` | Run 워커·UI 패턴 |
| `app/gui/views/os_upgrade_check_view.py` | M2 대상 화면 |
| `app/modules/os_upgrade/collector.py` | M1 스냅샷 |
| `config/os_upgrade_pre.yaml`, `os_upgrade_post.yaml` | 체크 프로필 |

---

## PRD vs 구현 (Multiple 선택 UX)

PRD §3.3: “선택 표시 — 장비 블록 **연한 파란** 배경”.

현재 구현: Ncurity **`#0260EA` / `#5C9DF5`** 커스텀 하이라이트 (Qt 기본 selection 비사용). 사용자 승인됨. PRD 정합이 필요하면 §3.3 문구만 갱신하면 됨.
