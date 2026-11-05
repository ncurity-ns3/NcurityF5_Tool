# worklog

---

## 2026-05-26 — Multiple 장비 표 UI 완료 (마일스톤 백업)

### 완료

- Multiple 진입 시 **자동 행 선택 제거** (`_clear_selection`).
- 장비 블록 선택: 활성 `#0260EA`, rSeries 형제 행 `#5C9DF5`, 미선택 zebra `#FBFDFF`/`#F3F8FD`.
- Password: 선택 블록 내 흰 배경·파란 테두리; ↑↓ 장비 간 포커스 이동.
- Model picker: hover만 Ncurity blue; 스크롤바 per-widget polish.

### 백업

- `backups/multiple_table_ui_20260526-1828.zip`
- `scripts/create_milestone_backup.py`
- 핸드오프: `docs/handoff_next_chat.md`

### 다음 (신규 채팅)

- `docs/os_upgrade_check_crd.md` 기준 **M2** GUI (Pre/Post Run) — CRD §7.

---

## 2026-05-22 — 업그레이드: 장비 개요 (1번 버튼)

- Test Connection 완료 후 작업 버튼 4개 (1번만 구현).
- `collect_device_overview` — Platform/Hostname/Serial/버전/HA/VLAN/Self·Floating·Gateway (iSeries는 F5OS 항목 공란).
- VLAN: TMOS `list net vlan` + rSeries F5OS REST/CLI.
- Self IP: REST `/tm/net/self` 이름·VLAN 휴리스틱 (ex/in).
- HTML: `output/os_upgrade/overview/device_overview_*.html` + Report 창.

## 2026-05-22 — GUI: 장비 연결 공유 + 메뉴

- `DeviceConnectionPanel` — Single/Multiple, 저장 목록·프로필, Test Connection (정기 점검·업그레이드 전·후 점검 공유).
- 저장 경로: `%LOCALAPPDATA%\f5tool\devices\` (Single), `%LOCALAPPDATA%\f5tool\lists\` (Multiple).
- 메뉴: Home → Initial Setup → **정기 점검** → 업그레이드 전·후 점검 → VPE Macro.
- `OsUpgradeCheckView` — 장비 연결만 (Pre/Post Run은 M2).

## 2026-05-22 — os_upgrade M1 (Pre/Post 스냅샷 수집)

- `config/os_upgrade_pre.yaml`, `os_upgrade_post.yaml` — 체크 항목·수집 카테고리(common+ltm).
- `app/modules/os_upgrade/checklist.py` — phase별 YAML 로드.
- `app/modules/os_upgrade/collector.py` — `run_os_upgrade_snapshot(phase=pre|post)` → `output/<job_id>/pre_snapshot|post_snapshot/`, `job_meta.json`, manifest.
- Job: `module=os_upgrade_check`, 한 job에 Pre→Post (`job_id` 재사용).
- 테스트: `tests/test_os_upgrade_checklist.py`, `tests/test_os_upgrade_collector.py`.

## 2026-05-22 — 다음 챕터: 업그레이드 전·후 점검

- 메뉴 **OS Upgrade** → **업그레이드 전·후 점검** (실제 업그레이드 미실행, Pre/Post·diff·리포트).
- 킥오프 문서: `docs/os_upgrade_check_crd.md`

---

## 2026-05-22 — 정기점검 완료 (마일스톤 백업)

### 정기점검 기능 요약 (이번 단계)

- Common: SSL(만료/만료예정), HA, 인터페이스 Up/Down 분리 표시, UCS 정책 백업(리포트 하단).
- UCS: 점검 후 tmsh save (REST 생략), staggered 시작 1초, `tmsh delete sys ucs` cleanup.
- 모듈: LTM/APM/AWAF — APM CCU = `total connectivity sessions` (예: 3.0K).
- GUI: iSeries or VE, Multiple+rSeries F5OS 계정, QThread UCS worker.

### 백업

- `backups/정기점검완료_YYYYMMDD-HHmm.zip` (소스·설정·tests·docs, `.venv`/`output` 제외).

---

## 2026-05-21 — HA 상태 + 리포트 순서

### 변경

- **HA 상태** (common): `tmsh show sys failover` + `show cm failover-status` → Standalone / Active / Standby / Force Offline (Force Offline = fail).
- **리포트 순서 (장비별):** Common(SSL 포함) → HA → LTM/APM/AWAF → 정책 백업(UCS) 맨 아래.

---

## 2026-05-21 — UCS 삭제 범위·순차 save

### 변경

- save 전 cleanup: **당일·해당 호스트 파일 1개만** `rm` (기존 `find *.ucs -delete`는 다른 백업까지 삭제됨).
- deferred UCS: 장비별 **순차** 1스레드 큐 (동시 save/bash 경합 방지), 동일 TMOS IP 중복 행 skip.
- save 후 `/var/local/ucs` **파일 존재 probe** — 없으면 로그 FAIL.

## 2026-05-21 — UCS 점검 후 일괄 백그라운드

### 변경

- **UCS:** common 수집 중 save **미실행** (util/bash 경합 제거). **전 장비 점검·리포트 완료 후** `spawn_deferred_ucs_backups`로 장비별 daemon 스레드 일괄 시작. Run/GUI는 UCS 완료를 기다리지 않음. 리포트 = `점검 후 백그라운드 예정`.

## 2026-05-21 — UCS 백그라운드 + 항목 LTM/APM/AWAF

### 변경

- **UCS (구):** common 수집 직후 스레드 시작 → bash와 경합·장비 순차 지연. 아래 일괄 방식으로 대체.
- **항목 GUI:** `system`/`network`/`ltm_summary` 제거 → **LTM**, **APM**, **AWAF** (체크한 카테고리만 REST 수집).
- **카테고리:** `ltm`(pool/virtual/node), `apm`(access/session/license), `awaf`(asm policies/signature-update).

---

## 2026-05-21 — F5OS SSH su admin + SSL grep 수정

### 수정

- **rSeries F5OS:** SSH(22) `root` 또는 `admin` 로그인 → `su admin` → `show vlan`, `show interfaces interface summary`, `show system health summary` (`app/core/f5os_ssh_cli.py`, paramiko)
- REST CLI exec는 SSH 실패 시 폴백
- **SSL:** bash `grep -e expire | grep -v ca-bundle`; 파서 `expired on` / `will expire on`만 집계 (만료 1건이 만료예정으로 잡히던 문제)

### lab

- F5OS MGMT IP에 **SSH 22** 개방, GUI F5OS 비밀번호 = root SSH 및 `su admin` 비밀번호로 동일하게 시도
- `pip install paramiko` (setup_dev 재실행 또는 `pip install -r requirements.txt`)

---

## 2026-05-21 — SSL·F5OS admin CLI (사용자 피드백)

### 수정

- **SSL:** 값 `만료 N | 만료예정 M`만; 비고(detail)에 **만료예정** CN 목록만
- **F5OS CLI:** `first_admin_show` — `show vlan`/`show vlans`, `show interfaces interface summary`, RPC `context: admin` 등 다중 시도
- **PSU:** `show system health summary` 테이블에서 `\bpsu-\d+\b` + `ok` 파싱 (psu-1만 있어도 pass)

### lab 재확인

- F5OS MGMT 계정 **admin** 권장 (root만 있으면 REST CLI exec가 admin CLI와 다를 수 있음)
- Run 후 rSeries 전원·인터페이스 skip → pass 여부

---

## 2026-05-21 — Health Check Common (lab 검증 준비)

### 완료 (코드·단위테스트)

- rSeries F5OS: 온도 avg, `show vlans` + interfaces summary, PSU health summary
- iSeries: PSU 테이블, Inlet Temp, uptime TMOS만
- System Time: `date` + `clock` (tmsh show sys clock 제거)
- SSL: `grep -i expire`, 값에 `hostname@IP`
- 인터페이스: mgmt 별도 표시
- **F5OS VLAN:** CLI 실패 시 REST 폴백 (`rest-interfaces`, `rest-vlans`); 둘 다 없으면 `vlan_unavailable` → interface **skip**

### 다음 (lab)

1. `scripts\run_gui.cmd` → common 체크 → Run → Open Report
2. rSeries interface: CLI 지원 시 pass, 미지원 시 skip 문구 확인
3. iSeries `192.168.42.5` / rSeries F5OS·TMOS — `docs/gui_test_debug_plan.md` §4

### 테스트

```cmd
.\.venv\Scripts\python.exe -m pytest tests/test_f5os_common.py tests/test_common_eval.py tests/test_tmos_bash_parse.py -q
```

---

## 2026-05-20 — gui / ux 설계 문서 작성

### 작업 내용

- 사용자 피드백: mgmt ip, id/pw 입력 gui부터 기대 — **구현 전 설계 우선**
- 신규 문서:
  - `docs/gui_design.md` — 화면 구조, 장비 연결 폼, 모듈 wizard, 보안 ux, 구현 순서
  - `docs/ui_flows.md` — mermaid 흐름, connection 화면 ascii wireframe
  - `docs/gui_field_catalog.md` — ui 필드 ↔ pydantic/backend 매핑表
- `docs/spec.md`, `readme.md` 에 gui 문서 링크 추가

### 현재 코드와의 관계

- cli + 모듈 = 엔진 검증 완료 (11 pytest pass, health-check fixture 성공)
- gui = **설계만 완료**, 코딩 대기 (설계 §16 open questions 확인 후)

### 설계 피드백 반영 (2026-05-20)

| 항목 | 결정 |
|------|------|
| 계정 | mgmt ip별 **세션 유지**(토큰 메모리), **username 프로필 저장** |
| 장비 | **Single / Multiple** — Multiple = 1 job N대 순차 |
| 리포트 | **QWebEngineView 인앱** |
| 언어 | **메뉴·버튼 EN** / **라벨·안내 KO** |
| 플랫폼 | phase 1 **TMOS만 표시** (gray 항목 없음) |

문서: `gui_design.md` v0.2, `ui_flows.md`, `gui_field_catalog.md` v0.2

### 다음 작업

1. live icontrol Test Connection (preview는 세션만 등록)
2. initial_setup / vpe_macro gui wizard
3. devices profile 저장 (username)

---

## 2026-05-20 — multiple 모드 공통 인증 ui (사용자 피드백)

### 피드백
- Multiple 선택 시 계정(ID/PW) 입력란이 보이지 않음

### 수정 (다음 실행부터)
- `health_check_view.py`: **공통 인증 (모든 장비)** 그룹 분리 — Single/Multiple 모두 표시
- Multiple 시 장비 테이블 + 공통 ID/PW/TLS/Fixture

---

## 2026-05-20 — gui preview 검증 완료 (사용자)

- `scripts\run_gui.cmd`: 경로 `&` 수정 후 정상, **Report Preview 팝업 없음**
- WebEngine import 순서 수정 적용됨
- 다음: Health Check 실제 화면 사용·live icontrol 연동, initial_setup/vpe gui

---

## 2026-05-20 — webengine import order fix

### 증상
`QtWebEngineWidgets must be imported ... before QCoreApplication is created`

### 수정
- `bootstrap_webengine_before_qapplication()` — WebEngine import + AA_ShareOpenGLContexts **후** `QApplication()`
- `app/gui/main.py` import 순서 정리

---

## 2026-05-20 — webengine dll path (windows)

### 작업
- `app/gui/qt_utils.py`: `os.add_dll_directory(Qt6/bin)` for WebEngine on Windows
- `scripts/check_webengine.py` / `check_webengine.cmd` 진단용
- startup popup에 실패 상세 메시지 포함

### 사용자 확인
```cmd
scripts\check_webengine.cmd
```

---

## 2026-05-20 — cmd `&` 경로 버그 수정

### 증상

- `Config & Rules & Apps` 경로에서 `echo project: %CD%` 시 `Rules` 가 별도 명령으로 실행됨
- PyQt6-WebEngine 설치 후에도 Report Preview 안내 팝업

### 수정

- `run_gui.cmd` / `setup_dev.cmd` / `run_tests.cmd`: `pushd "%~dp0.."`, `echo "%CD%"`, python 경로 따옴표
- `scripts/run_gui.ps1` 추가 (& 경로 안전)
- `report_viewer.py`: QApplication 후 lazy WebEngine 로드

---

## 2026-05-20 — gui preview (대략적인 화면)

### 작업 내용

- `app/gui/` — PyQt6 main window, nav(영문), Health Check 화면(한글 라벨)
- Single / Multiple, device table, Fixture Mode, Run → embedded report
- `SessionManager` 메모리 세션 (Test Connection 미리보기)
- `scripts/run_gui.cmd`, `python -m app.gui.main`, `f5tool-gui` entry

### 실행

```cmd
scripts\run_gui.cmd
```

### 한계 (preview)

- Test Connection: 실제 BIG-IP 미연동, 세션 등록만
- Initial Setup / VPE Macro / Reports: placeholder

---

## 2026-05-20 — run_tests: py -3.12 오류 수정

### 증상

- `setup_dev.cmd` 성공 (`.venv` + pip 설치 완료, python 3.14)
- `run_tests.cmd` 실패: `py.exe : [ERROR] No runtime installed that matches 3.12`

### 원인

- `find_python.ps1` 이 `.venv` 검증 전에 `py -3.12` 호출
- `$ErrorActionPreference = Stop` 환경에서 py 런처 stderr가 terminating error 로 처리됨

### 수정

- `run_tests.ps1`: `.venv\Scripts\python.exe` 있으면 **즉시 사용** (find_python 생략)
- `find_python.ps1`: venv 우선, py 프로브는 `SilentlyContinue` + `-3.14` 등 포함
- `setup_dev.ps1`: venv 생성 시 `py -3` / `py -3.14` 폴백, pip exit code 검사

### 테스트 결과 (2026-05-20 사용자 실행)

- `scripts\run_tests.cmd` **성공**
- python: `.venv\Scripts\python.exe` — **Python 3.14.5**
- naming convention: ok
- pytest: **11 passed in 1.66s**
  - integration: `test_health_check_job`
  - naming: 5 tests
  - unit: safety_gate, redaction, initial_setup, vpe_macro, bigip_client write block

### 다음 작업

1. ` .venv\Scripts\python.exe -m app.main health-check --use-fixture --output output`
2. phase 1 gui (pyqt6)
3. pyinstaller 오프라인 번들

---

## 2026-05-20 — milestone backup + multiple test/run fixes

### 작업 내용

- Multiple Test Connection / Run: **목록 전체** 처리, `[label]` 표시, connection **순서(index)** 매칭
- Add Device: Port 기본 **443**, 라벨 `device-N` 자동
- 백업: `backups/f5field_tool_2026-05-20.zip`, `docs/milestone_backup_20260520.md`

### 다음

- 정기점검 리스트 (점검 항목·체크리스트)

---

## 2026-05-20 — iSeries / rSeries platform in health check gui

### 작업 내용

- **장비 모델:** `iSeries (TMOS)` / `rSeries (F5OS+TMOS)` — Single·Multiple 테이블 Model 열
- **rSeries 전용:** F5OS MGMT IP/Port + F5OS 인증 (공통·장비별), TMOS tenant MGMT는 선택
- **수집:** `platform_router` → `TmosCollector` / `RseriesCollector` + `F5osClient`
- **저장 프로필:** platform, f5os_host/port/username 포함 (비밀번호 미저장)
- **Test Connection:** TMOS·F5OS 각각 성공/실패 표시

---

## 2026-05-20 — health check gui ux round 2 (sessions, summary, no flicker)

### 작업 내용

- **저장된 연결:** `%LOCALAPPDATA%\f5tool\devices\*.json` — label/host/port/username (비밀번호 미저장), Load/Save/Delete, Multiple 시 Add from Saved
- **TLS 검증 / Fixture Mode:** GUI에서 제거, MGMT는 `verify_tls=False` 고정
- **Run 후 깜빡임:** Run 시 WebEngine 미리보기 제거 — 요약 패널만 갱신, HTML은 Open Report Window에서만
- **요약:** Healthy / Unhealthy + `Unhealthy 사유: N건` (`app/modules/health_check/findings.py`)
- **실제 수집:** Run 시 `ConnectionProfile` 전달 (Test Connection과 동일 계정)

---

## 2026-05-20 — health check gui ux (multiple auth, test connection, report window)

### 작업 내용

- **Multiple 인증:** `공통 계정` / `장비별 계정` 라디오 — 장비별 선택 시 테이블에 User ID·Password 열 추가, 공통 ID/PW 필드 숨김
- **Test Connection:** Fixture 제외 시 실제 `BigipClient.authenticate()` + system info — 성공/실패 제목·메시지·연결 상태 라벨(녹색/빨강) 구분
- **Report:** `Open Report Window` — 별도 대화상자(`ReportWindow`)에서 전체 HTML; 미리보기 영역은 요약용
- **HTML 리포트 템플릿:** 스타일·categories·status 컬럼 보강 (`templates/health_check_report.html.j2`)
- **Initial Setup:** 메뉴 placeholder 유지 — 다음 구현 예정

### 테스트

- pytest 11 passed (새 경로 venv)

---

## 2026-05-20 — project root relocated

### 작업 내용

- 프로젝트 루트를 사용자 지정 경로로 이동:
  - `C:\Users\ejes3\Ejes_OneDrive\OneDrive - Ncurity\바탕 화면\WorksFiles\F5 Project\Config & Rules & Apps\AI First`
- cursor agent workspace를 위 경로로 전환 (`move_agent_to_root`)
- `C:\Users\ejes3` 에 있던 poc 코드·테스트·스크립트를 새 경로에 재구성
- `docs/windows_setup.md`, `readme.md` 경로 안내 갱신
- 이전 위치(`C:\Users\ejes3`)는 legacy — **새 작업은 ai first 폴더만 사용**

### 테스트 결과

- (사용자 pc) `scripts\setup_dev.cmd` → `scripts\run_tests.cmd` 실행 필요

### 다음 작업

1. 새 경로에서 venv 생성 및 pytest
2. phase 1 gui / pyinstaller

---

## 2026-05-20 — windows python/pip 미설치 대응

(이전 루트 `C:\Users\ejes3` 에서 수행 — 내용 동일, 스크립트는 새 경로에 포함됨)

---

## 2026-05-20 — naming + phase 1 poc bootstrap

설계 문서: `docs/spec.md`, `docs/roadmap.md`, `docs/security_rules.md`, `docs/test_plan.md`

---

## 2026-05-20 — PRD + Multiple Load fix

- **Bug:** Multiple Load always called `profile_store.get` → «프로필을 찾을 수 없습니다» for list sessions.
- **Fix:** Branch on mode; lists use `list_store` only. List file stem keeps Korean/`+` in filename.
- **Docs:** `docs/prd.md`, `docs/gui_test_debug_plan.md`, `tests/test_health_check_session_load.py`.
