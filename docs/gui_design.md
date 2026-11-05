# gui / ux design specification

version: 0.2  
status: design reviewed (awaiting implementation)  
parent: [spec.md](spec.md)  
companion: [ui_flows.md](ui_flows.md), [gui_field_catalog.md](gui_field_catalog.md)

---

## 1. design intent

현장 엔지니어가 **처음 보는 화면**에서 할 수 있어야 하는 것:

1. 대상 장비 **mgmt ip** (및 포트·플랫폼) 지정  
2. **id / password** 입력 (세션용, 파일·프로젝트에 저장하지 않음)  
3. 작업 유형 선택 (정기점검 / 초기설정 설계 / vpe macro 설계 / os upgrade 지원)  
4. 실행 → 진행 상태 확인 → **리포트·산출물** 열람  

지금까지 구현된 것은 위 UX의 **하위 엔진(cli + 모듈)** 검증 단계이다.  
**gui는 본 문서 승인 후** 구현한다.

---

## 2. user personas

| persona | goal | constraints |
|---------|------|-------------|
| field engineer | 고객사에서 빠르게 점검·산출 | 오프라인, usb 휴대, 운영 장비 실수 방지 |
| lead engineer | 산출물 검토·고객 제출 | 리포트 html/xlsx, 감사 로그 |
| lab engineer | 템플릿·fixture 검증 | 장비 없이 설계 모드 |

---

## 3. information architecture

```
main window
├── home (대시보드 / 최근 job)
├── devices (연결 프로필 — 비밀번호 제외 저장)
├── jobs
│   ├── health_check wizard
│   ├── initial_setup wizard
│   ├── vpe_macro wizard
│   └── os_upgrade wizard (phase 2)
├── reports (산출물 브라우저)
└── settings
    ├── output directory
    ├── default check profile
    ├── change mode (phase 3, 기본 off)
    └── about / offline help
```

**원칙:** 모든 모듈 job은 **동일한「장비 연결」스텝**을 공유하거나, 사전에 등록한 device profile을 선택한다.

---

## 4. application shell

### 4.1 main window layout

```
+------------------------------------------------------------------+
| [logo] f5 field tool          [offline]     사용자: DOMAIN\user  |
+----------+-------------------------------------------------------+
| nav      |  content area                                       |
|          |                                                       |
| home     |                                                       |
| devices  |                                                       |
| jobs  >  |                                                       |
| reports  |                                                       |
| settings |                                                       |
+----------+-------------------------------------------------------+
| status: ready | last job: ... | output: C:\...\output            |
+------------------------------------------------------------------+
```

| zone | widget | behavior |
|------|--------|----------|
| nav | QList / QTree | **메뉴 라벨 영문** (Home, Devices, Jobs, Reports, Settings) |
| content | QStackedWidget | 화면 전환 |
| status | QLabel | 연결 상태, job id, 경로 |

### 4.2 global modes (status bar badge)

| badge | meaning |
|-------|---------|
| offline | 인터넷 미사용 (항상) |
| design | 장비 연결 없이 산출만 |
| read-only | icontrol get만 (기본) |
| change | change mode on (phase 3, 경고색) |

---

## 5. device connection (core screen — phase 1 priority)

엔지니어가 기대하는 **첫 입력 화면**. 정기점검 wizard 1단계이자, `devices` 메뉴의 편집 화면과 동일한 필드셋.

### 5.0 target mode (single | multiple)

정기점검·수집 job 시작 시 **먼저** 선택한다.

| mode | ui (영문 라벨) | 설명 |
|------|----------------|------|
| **Single** | `Target Mode: Single` | 장비 1대 — 연결 폼 1세트 |
| **Multiple** | `Target Mode: Multiple` | 장비 N대 — **한 job에서 순차 점검** (테이블에 ip/라벨 추가) |

```
  Target Mode:  (•) Single   ( ) Multiple

  [ Single 일 때 ]
      → 아래 연결 폼 1개

  [ Multiple 일 때 ]
      | label      | mgmt ip      | port | [x] |
      | primary    | 10.0.0.1     | 443  | del |
      | secondary  | 10.0.0.2     | 443  | del |
      [ + Add Device ]

      [ 공통 인증 (모든 장비) ]  ← Single/Multiple 모두 **항상 표시** (v0.2.1)
        사용자 ID / 비밀번호 / TLS / Fixture
      [ ] per-device credentials (phase 2, 고급)
```

**ux 버그 수정 (2026-05-20):** 초기 preview 에서 Multiple 선택 시 Single 그룹 전체를 숨겨 ID/PW까지 사라짐 → **공통 인증 블록 분리**.

**Multiple 동작:** 한 번의「점검 실행」으로 리스트 순회 → 통합 리포트(장비별 섹션) + `exceptions.json`에 실패 장비만 기록.  
**한대씩 따로 job** 만드는 방식은 지원하지 않음 (전자가 운영상 편함 — 사용자 확인).

### 5.1 field layout (single 또는 multiple 공통 인증 블록)

```
[ Device Connection ]  ← 섹션 제목 한글

  Platform:     BIG-IP TMOS (VE)     ← phase 1: 이 항목만 제공 (아래 §5.5)

  장비 라벨:     [ lab-bigip-01_______________ ]

  MGMT IP:       [ 203.0.113.10___ ]   Port: [ 443 ]

  TLS:           [x] 인증서 검증   [ ] Lab 지문 신뢰 (1회)

  사용자 ID:     [ admin________________ ]

  비밀번호:      [ ************** ]  [👁]

  [ ] Fixture Mode (lab — 샘플 데이터)

  [ Test Connection ]   [ Disconnect ]   [ Next > ]

  세션: (비어 있음 | "10.0.0.1 — logged in as admin (expires on exit)")

  ※ 비밀번호·토큰은 파일에 저장하지 않습니다. 같은 IP 작업 중에는 세션을 유지합니다.
```

**버튼 라벨:** 기능명은 **영문** (Test Connection, Next, …), 설명·안내 문구는 **한글**.

### 5.2 validation rules

| field | rule |
|-------|------|
| mgmt ip | ipv4/ipv6, private range 허용, 빈 값 불가 (fixture 제외) |
| port | 1–65535 |
| username | non-empty (fixture 제외) |
| password | non-empty when not fixture; 메모리만 |
| label | non-empty, 파일명 안전 문자 |

### 5.3 connection test behavior

| step | action |
|------|--------|
| 1 | 입력 검증 |
| 2 | `BigipClient.authenticate` + `get_system_info` (read-only) |
| 3 | 성공: hostname/version을 녹색 메시지로 표시, wizard 다음 활성화 |
| 4 | 실패: 원인 분류 (tls / auth / timeout / network) — **password 값은 로그·ui에 노출 금지** |

### 5.4 session per mgmt ip (approved)

**요구사항:** 한 번 로그인하면, **같은 MGMT IP**에 대해 작업하는 동안 다시 비밀번호를 묻지 않는다.

| 항목 | 동작 |
|------|------|
| 첫 `Test Connection` | id/pw로 icontrol login → **메모리**에 `SessionEntry(host, token, username, expires_at=app_exit)` |
| 같은 IP 재작업 | 저장된 token으로 get 수행 (pw 필드 비워도 됨, 또는 pw 유지하되 token 우선) |
| IP 변경 / Disconnect | 해당 host 세션만 제거 |
| 앱 종료 | 모든 세션·토큰 폐기 |
| username | device profile json에 **저장** (ip·라벨과 함께) — 다음 방문 시 id 자동 채움 |
| password | **디스크 저장 never** |
| token | **디스크 never**, 메모리 only |

```
SessionManager (singleton)
  key: host:port
  value: { username, token, verified_at, platform }
```

**보안 UI:** `Disconnect` 버튼으로 현장 인계 전 세션 수동 삭제. 설정에 `Clear all sessions on exit` 기본 on.

### 5.5 persistence model (ui → disk)

| field | saved in device profile file? |
|-------|--------------------------------|
| label, host, port, platform, verify_tls, fingerprint | yes (`%LOCALAPPDATA%\f5tool\devices\*.json`) |
| username | **yes** (해당 ip 프로필에 연동) |
| password | **never** |
| session token | **never** (메모리만, §5.4) |

### 5.6 platform list (phase 1 — no “gray”)

phase 1 GUI **Platform** 드롭다운에는 **BIG-IP TMOS (VE) 만** 표시한다.

- rSeries / F5OS 는 **아예 목록에 넣지 않음** (비활성 gray 항목 없음 → 혼동 방지)
- phase 2에서 드롭다운 항목 추가 + adapter 연결

이전 설계의 “gray 처리”는 **“아직 지원 안 하는 항목을 흐리게 보이게 한다”** 는 뜻이었으나, **선택지 자체를 숨기는 방식**으로 변경한다.

---

## 6. module wizards overview

| module | wizard steps (phase 1) | needs live device? |
|--------|------------------------|-------------------|
| health_check | 연결 → 점검 항목 → 메타(현장명/기간) → 실행 → 리포트 | yes (or fixture) |
| initial_setup | 설계 모드 선택 → 네트워크 폼 → 검토 → 산출 | no (design) |
| vpe_macro | 인증 방식 → 리소스 모델 → mfa → 검토 → 산출 | no (design) |
| os_upgrade | pre → (수동 upgrade 안내) → post → diff | phase 2 |

상세 단계·필드: [gui_field_catalog.md](gui_field_catalog.md)  
흐름도: [ui_flows.md](ui_flows.md)

---

## 7. health_check wizard (phase 1 mvp gui)

### step 1 — 장비 연결

섹션 5와 동일.

### step 2 — 점검 프로필

```
[ 정기점검 항목 ]

  프로필: [ 기본 ▼ ]  [ 고급 편집... ]

  [x] system    [x] network    [x] ltm_summary
  [ ] failover  [ ] apm        [ ] cert_expiry (phase 2)

  타임아웃(초): [ 120 ]
```

### step 3 — 현장 정보 (최소 입력)

```
  고객사/사이트명: [ _____________ ]  (리포트 표지)
  점검 기간:       [ 2026-05 ______ ]
  비고:            [ ___________________________ ]
```

### step 4 — 실행 및 결과

```
  [ Progress bar ]
  로그(요약):  device lab-01: system ok, network ok ...  (한글)

  +--------------------------------------------------+
  |  Report Preview (embedded — QWebEngineView)       |
  |  html 리포트 인앱 표시                              |
  +--------------------------------------------------+

  [ Open Folder ]  [ Export XLSX ]  [ Export MD ]

  Job ID: xxxxxxxx   Status: completed
```

**리포트:** **앱 내 embedded viewer** 기본 (외부 브라우저는 Settings 에서 optional fallback).

**버튼 정책:** 운영 장비에 **쓰기/적용** 버튼 없음.

---

## 8. initial_setup wizard (design-only gui)

### step 1 — 모드

```
  ( ) 설계만 (장비 미연결)  ← 기본
  ( ) 연결 후 현재 상태 참고 (read-only, phase 2)
```

### step 2 — 네트워크·시스템

```
  hostname:     [ _____________ ]
  mgmt ip:      [ _____________ ]  netmask: [ _____________ ]
  gateway:      [ _____________ ]
  dns:          [ + 추가 ]
  ntp:          [ + 추가 ]
  vlan 목록:    [ 테이블: name | tag | ... ]
```

### step 3 — 산출물 선택

```
  [x] setup_design.md   [x] tmsh_initial.tcl
  [x] validation_checklist.md   [ ] rest_payloads/
```

### step 4 — 생성

미리보기(tabs) + `로컬 폴더에 저장` — **장비 적용 버튼 없음**.

---

## 9. vpe_macro wizard (design-only gui)

| step | content |
|------|---------|
| 1 | auth: ad / radius / oauth / saml |
| 2 | resource: by_group / by_account + mapping table |
| 3 | mfa: google_otp, f5_otp, fido (checkbox) |
| 4 | irule 필요 여부 |
| 5 | mermaid 미리보기 + 산출물 생성 |

---

## 10. reports browser

```
  Filter: [ Module ▼ ] [ Period ▼ ] [ Search_____ ]

  | job id | module | date | site | status | [ Open ] |

  더블클릭 / Open → **동일 embedded html viewer** (메인 영역 또는 탭)
```

---

## 11. settings

| setting | default | note |
|---------|---------|------|
| output root | `%LOCALAPPDATA%\f5tool\output` or project `./output` |
| remember device profiles | on | without password |
| remember username | off | opt-in per device |
| change_mode_enabled | false | phase 3 |
| language | **mixed** | **nav·버튼·메뉴: 영문** / **라벨·안내·로그: 한글** |

---

## 12. security & compliance (gui-specific)

| rule | ui enforcement |
|------|----------------|
| no password on disk | no QSettings key; session object only |
| no clipboard for password | disable copy on password field |
| clear on exit | optional prompt "세션 비밀번호 폐기" |
| audit | job start/end without credential fields |
| production guard | profile tag `production` → hide apply (phase 3) |

---

## 13. technology choices (gui layer)

| item | choice | note |
|------|--------|------|
| framework | **PyQt6** (primary) | offline, windows native |
| pattern | mvvm-like | `app/gui/views`, `app/gui/viewmodels`, `app/gui/services` |
| threading | QThread worker | icontrol 호출은 ui 스레드 차단 금지 |
| html report | **QWebEngineView** embedded | phase 1 기본; optional external browser in settings |

---

## 14. proposed package layout (after design approval)

```
app/gui/
├── main_window.py
├── views/
│   ├── home_view.py
│   ├── device_connection_view.py
│   ├── health_check_wizard.py
│   ├── initial_setup_wizard.py
│   ├── vpe_macro_wizard.py
│   └── reports_view.py
├── viewmodels/
│   └── connection_viewmodel.py
├── services/
│   ├── job_runner.py
│   ├── device_profile_store.py
│   └── session_manager.py
└── resources/
    └── styles.qss
```

---

## 15. implementation order (post-design)

| order | deliverable | maps to backend |
|-------|-------------|-----------------|
| 1 | main shell + navigation | — |
| 2 | **device_connection_view** + connection test | `BigipClient`, `DeviceTarget` |
| 3 | health_check wizard end-to-end | `run_health_check_job` |
| 4 | reports browser | output dir |
| 5 | initial_setup wizard | `generate_initial_setup_artifacts` |
| 6 | vpe_macro wizard | `generate_vpe_macro_artifacts` |
| 7 | pyinstaller entry `f5tool.exe` | `app.gui.main` |

**cli는 유지:** gui와 동일 viewmodel을 공유해 자동화·디버그용.

---

## 16. design decisions (approved 2026-05-20)

| # | topic | decision |
|---|--------|----------|
| 1 | 계정 유지 | **mgmt ip 단위 세션**: 로그인 후 토큰·username 세션 유지(앱 종료까지). username은 프로필에 저장. password·token은 파일 저장 안 함 |
| 2 | 장비 수 | **Single + Multiple** 모드. Multiple = 한 job에서 N대 순차 점검·통합 리포트 |
| 3 | 리포트 | **앱 내 embedded html viewer** (QWebEngineView) |
| 4 | 언어 | **메뉴·버튼·nav: 영문** / **필드 라벨·안내·진행 로그: 한글** |
| 5 | 플랫폼 | phase 1 **TMOS만 목록에 표시**. rSeries/F5OS는 항목 자체 미표시 (gray 없음) |

---

## 17. i18n convention (en + ko)

| ui element | language | examples |
|------------|----------|----------|
| left nav | english | Home, Devices, Jobs, Health Check, Reports, Settings |
| wizard buttons | english | Test Connection, Next, Back, Cancel, Run, Disconnect |
| section titles | korean | 장비 연결, 점검 항목, 현장 정보 |
| field labels | korean | MGMT IP, 사용자 ID, 비밀번호 (technical terms may stay EN) |
| hints / errors | korean | 로그인에 실패했습니다. ID/PW를 확인하세요. |
| status bar | mixed | `Ready` / `Collecting…` + 한글 부가 설명 optional |

구현: `app/gui/i18n/strings.py` 에 `nav_*` (en), `label_*` (ko) 분리 — 하드코딩 테이블 phase 1, qt linguist phase 2 optional.

---

## 18. relation to current codebase

| already exists | gui will use |
|----------------|--------------|
| `app/core/models.py` | DeviceTarget, ConnectionProfile, HealthCheckProfile |
| `app/core/bigip_client.py` | connection test |
| `app/modules/health_check/collector.py` | run job |
| `app/output/*` | report paths |
| `app/main.py` cli | parallel entry, same services |

---

*section 16 approved — gui implementation may start*
