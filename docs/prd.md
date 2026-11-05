# F5 Field Tool — Product Requirements Document (PRD)

| 항목 | 내용 |
|------|------|
| 버전 | 0.2 (Health Check GUI 중심) |
| 상태 | 백엔드 PoC + **Health Check GUI 프리뷰** 진행 중 |
| 대상 사용자 | 고객사 현장 F5 엔지니어 (Windows, 오프라인) |
| 관련 문서 | [spec.md](spec.md), [gui_design.md](gui_design.md), [test_plan.md](test_plan.md), [gui_test_debug_plan.md](gui_test_debug_plan.md) |

---

## 1. 제품 비전

반복적인 **정기점검·초기 설정·VPE Macro·OS Upgrade**를 하나의 오프라인 워크벤치에서 수행한다. 1차 목표는 **읽기 전용 수집 → 분석 → HTML/MD 리포트**이며, 장비 변경은 승인 후 적용(후속 단계).

### 1.1 핵심 원칙

| 원칙 | 설명 |
|------|------|
| Offline-first | 인터넷 없이 실행; PyInstaller 번들 예정 |
| Read-first | Phase 1: 수집·리포트만 |
| No secrets on disk | 비밀번호·토큰은 메모리만; 세션 JSON에 비밀번호 금지 |
| Platform abstraction | iSeries(TMOS), rSeries(F5OS + TMOS tenant) |
| Human-in-the-loop | 적용/변경은 Preview → 승인(Phase 2+) |

### 1.2 지원 플랫폼 (Health Check)

| 모델 | 스택 | MGMT | Phase 1 |
|------|------|------|---------|
| iSeries | TMOS 1행 | TMOS IP:443 | Test Connection, Run Health Check |
| rSeries | F5OS → TMOS 2행 | F5OS + Tenant TMOS | F5OS 먼저 인증, TMOS 별도 계정 |

---

## 2. 아키텍처 요약

```
PyQt6 GUI (main_window)
  └─ HealthCheckView
       ├─ DeviceProfileStore   → %LOCALAPPDATA%\f5tool\devices\*.json   (장비 1대)
       ├─ DeviceListStore      → %LOCALAPPDATA%\f5tool\lists\*.json      (Multiple 목록)
       ├─ MultiDeviceTablePanel (2행/장비 표)
       └─ HealthCheckWorker → collector → report HTML
```

**실행:** `scripts\run_gui.cmd` (경로에 `&` 포함 → pushd 사용)

**데이터 디렉터리:** `%LOCALAPPDATA%\f5tool\`

---

## 3. Health Check GUI — 기능 요구사항

### 3.1 Target Mode

| 모드 | 설명 |
|------|------|
| Single | 장비 1대 폼 (모델, F5OS/TMOS, 공통 인증) |
| Multiple | 장비 표 + 공통/장비별 계정 |

### 3.2 저장된 연결 (Session)

#### Single 모드

| 동작 | 동작 상세 |
|------|-----------|
| 드롭다운 | `devices/*.json` 개별 **프로필** 목록 |
| 프로필 선택 | 폼에 **자동 반영** (Load와 동일) |
| Save | 현재 폼 → 프로필 1개 저장 (비밀번호 제외) |
| Load | 선택 프로필 → 폼 |
| Delete | 선택 프로필 삭제 |

#### Multiple 모드

| 동작 | 동작 상세 |
|------|-----------|
| 드롭다운 라벨 | **「목록」** — `lists/*.json` (**표 전체** 스냅샷) |
| Save | 이름 입력 → **현재 표 전체** + 공통/장비별 계정 플래그 저장 |
| Load | 선택 목록 → 표 **전체 교체** (인증 모드 포함) |
| Delete | 선택 목록 삭제 |
| + 저장된 장비에서 추가… | **대화상자**에서 `devices/*.json` 다중 선택 → 표 **끝에 행 추가** (드롭다운과 무관) |

**비밀번호:** 모든 Save에 비밀번호 미저장. Load 후 사용자가 다시 입력.

**목록 파일 ID:** 표시 이름과 동일한 파일명 stem (한글·`+` 허용, Windows 금지 문자만 `_` 치환).

### 3.3 장비 목록 표 (Multiple)

| 요구 | 구현 |
|------|------|
| iSeries | TMOS 1행 (Stack=TMOS) |
| rSeries | F5OS 행 + TMOS 행; Model/Label **row span** |
| 공통 계정 | User/Password 열 숨김; 하단 **인증 (공통)** 사용 |
| 장비별 계정 | User/Password 열 표시; Password는 `QLineEdit` Password echo |
| 선택 표시 | 장비 블록 연한 파란 배경; Tab 시 포커스 **유지** (재귀 방지) |
| Test Connection | **표의 모든 장비** 순차 테스트; `[label]` 접두 메시지 |
| Run Health Check | 모든 장비; `connections`는 **인덱스 정렬** (라벨 중복 허용) |

### 3.4 연결·API

| 항목 | 요구 |
|------|------|
| TLS | 검증 off (현장 자체서명) |
| 포트 기본값 | 443 |
| F5OS API | `GET /api`, `Content-Type: application/yang-data+json`, `X-Auth-Token` |
| TMOS | icontrol REST; 401 시 basic auth fallback (read-only 경로) |
| rSeries TMOS | F5OS admin ≠ tenant TMOS 계정 (실패 시 힌트만) |

### 3.5 리포트 UX

| 요구 | 구현 |
|------|------|
| Run 시 WebEngine 미사용 | 요약 패널만 갱신 (깜빡임 방지) |
| 요약 | Healthy / Unhealthy + 장비 수·사유 건수 |
| 상세 | **Open Report Window** → HTML |

### 3.6 사이트 메타

사이트명, 점검 기간, 비고 → 리포트 템플릿에 반영.

### 3.7 정기점검 Common 체크리스트 (2026-05-20)

| 구분 | iSeries | rSeries |
|------|---------|---------|
| 수집 | TMOS bash only | **F5OS** REST: uptime·PSU·온도·Disk / **TMOS** bash: 논리·성능·SSL·UCS |
| GUI | `common (정기점검)` 체크 (기본 ON) | 동일 |
| 정의 | `config/health_check_common.yaml` | |
| 판정 | `app/modules/health_check/common_eval.py` | |
| 리포트 | HTML 「정기점검 Common 체크리스트」 표 | |

**Common 항목:** Uptime, 전원, 온도, 인터페이스, NTP, System Time, Disk, 데몬(tmm/bigd/mcpd), CPU/Mem/Connection/Throughput, SSL 만료, UCS 백업.

**후속:** SSL VPN(접속자/License), WAF(Event/Policy 수) 등은 별도 모듈.

---

## 4. 백엔드 (Health Check 모듈)

| 구성요소 | 역할 |
|----------|------|
| `BigipClient` | TMOS 로그인·수집 |
| `F5osClient` | rSeries 플랫폼 수집·`format_f5os_summary()` |
| `platform_router` / `RseriesCollector` | F5OS → TMOS 순서 |
| `collector.py` | targets + connections (index-aligned) |
| `findings.py` | Pass/Fail 규칙·요약 |
| `templates/health_check_report.html.j2` | HTML 리포트 |

---

## 5. 알려진 이슈 & 수정 이력 (대화 누적)

| # | 증상 | 원인 | 상태 |
|---|------|------|------|
| 1 | Multiple Save 시 Load처럼 행 추가 | combo `currentIndexChanged` + Save 후 reload가 자동 Load | **수정** — Single만 자동 반영, `blockSignals` |
| 2 | Add from Saved = Load UX | 상단 드롭다운 의존 | **수정** — 프로필 선택 대화상자 |
| 3 | Save가 선택 행만 저장 | Multiple Save가 `selected_device_index` 사용 | **수정** — 표 전체 → `lists/` |
| 4 | Password Focus RecursionError | FocusIn → setCurrentCell → Combo FocusIn 루프 | **수정** — 하이라이트만, 포커스 이동 안 함 |
| 5 | Multiple Load «프로필을 찾을 수 없습니다» | Load가 항상 `profile_store.get` 먼저 호출 | **수정** — Multiple은 `list_store`만 |
| 6 | 한글 목록명 slug 깨짐 | `[^a-z0-9]`만 허용 | **수정** — 유니코드 파일명 stem |

---

## 6. 미완 / 로드맵

| 우선순위 | 항목 |
|----------|------|
| P0 | 정기점검 체크리스트 — **Common 1차 구현** (`common` category, `config/health_check_common.yaml`) |
| P1 | SSL VPN / WAF 등 솔루션별 체크 모듈 |
| P1 | Initial Setup 탭 (placeholder) |
| P1 | Test Connection 토큰 재사용 (성능) |
| P2 | PyInstaller 고객 배포 번들 |
| P2 | OS Upgrade / VPE Macro 모듈 |

---

## 7. 비기능 요구사항

| 항목 | 기준 |
|------|------|
| OS | Windows 10/11 x64 |
| Python | 3.11+ (venv) |
| 성능 | Multiple 10대 이하 Test Connection 2분 이내 (현장 목표) |
| 보안 | repo에 실 IP/비밀번호 금지; `%LOCALAPPDATA%`만 실데이터 |
| 테스트 | `pytest` unit + [gui_test_debug_plan.md](gui_test_debug_plan.md) 수동 체크 |

---

## 8. 수용 기준 (Health Check GUI — 현재 스프린트)

- [x] Single: iSeries 수동 Test Connection
- [x] Single: rSeries 프로필 Load + F5OS/TMOS Test Connection
- [x] Multiple: 장비별 계정 + iSeries/rSeries Test
- [x] Multiple: 목록 Save(전체) → Remove Selected → Load
- [ ] Single: 프로필 Save/Delete/자동반영 (Load는 검증됨)
- [ ] Multiple: + 저장된 장비에서 추가 (다중 선택)
- [ ] 장비별 계정 Password 필드 Tab 시 크래시 없음 (수동 재확인 권장)
- [ ] Run Health Check → Healthy/Unhealthy + Open Report
- [ ] 한글 목록명 Save 후 Load 동일 장비 수 (동일 시나리오로 검증됨)

---

## 9. 용어

| 용어 | 의미 |
|------|------|
| 프로필 | 장비 1대 연결 정보 (`devices/`) |
| 목록 | Multiple 표 스냅샷 (`lists/`) |
| F5OS | rSeries 플랫폼 MGMT |
| TMOS | Tenant/iSeries 데이터 플레인 MGMT |

---

*최종 갱신: 2026-05-20 — Health Check GUI 세션/표/Load 버그 반영*
