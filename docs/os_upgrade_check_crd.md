# OS Upgrade Check — Chapter CRD (시작 문서)

| 항목 | 내용 |
|------|------|
| 모듈 ID (코드) | `os_upgrade` |
| 메뉴 표시명 | **OS 업그레이드 간 점검** |
| 영문 (내부) | OS Upgrade Readiness & Verification |
| 버전 | 0.1 (신규 챕터 킥오프) |
| 상태 | M1 ✅ 스냅샷 수집 · M2 GUI · M3 diff · M4 rollback |

---

## 1. 한 줄 정의

**장비에서 OS/TMOS 이미지 업그레이드를 대신 실행하지 않는다.**  
엔지니어가 수동 업그레이드 창 전·후에 해야 할 **체크리스트 수집·비교·리포트**를 자동화한다.

---

## 2. 범위

### In scope

| 구분 | 내용 |
|------|------|
| Pre-check | 업그레이드 **전** 스냅샷 수집 (버전, HA, 디스크, config 백업 확인, 필수 서비스 등) |
| Post-check | 업그레이드 **후** 동일 프로필 재수집 |
| Diff | Pre vs Post HTML/MD 리포트 (버전 변경, 실패 항목, 신규/소실) |
| Rollback guide | 롤백 시 확인할 항목 MD (실행은 수동) |
| 플랫폼 | iSeries/VE (TMOS), rSeries (F5OS + tenant TMOS) — Health Check와 동일 연결 모델 |
| 산출물 | `output/<job_id>/` — pre/, post/, diff_report.html, rollback_checklist.md |

### Out of scope (명시적 비목표)

- ISO/이미지 업로드, `install sys` / F5OS upgrade **실행**
- 자동 펌웨어/재부팅 스케줄링
- 변경 모드에서의 config push (Phase 1 원칙: read-first 유지)

---

## 3. 사용자 플로우 (목표 GUI)

```mermaid
flowchart LR
  A[장비·목표 버전 입력] --> B[Pre-check Run]
  B --> C[수동 업그레이드 안내\n앱은 대기/메모]
  C --> D[Post-check Run]
  D --> E[Diff 리포트]
  E --> F[Rollback 체크리스트]
```

1. **연결**: Health Check와 동일 — Single/Multiple, DeviceListStore, Test Connection.
2. **메타**: 사이트명, 유지보수 창, **Target Version** (문자열, 리포트용).
3. **Pre-check Run**: 체크 프로필 YAML 선택 → 수집 → `pre_snapshot/`.
4. **게이트**: UI에 “지금 장비에서 업그레이드를 수행하세요” (타이머/대기 강제 없음).
5. **Post-check Run**: 동일 장비·동일 프로필 → `post_snapshot/`.
6. **Diff**: 자동 생성 + Open Report Window.

---

## 4. Health Check와의 관계

| 항목 | Health Check | OS 업그레이드 간 점검 |
|------|----------------|----------------------|
| 목적 | 정기 운영 점검 | 업그레이드 전후 검증 |
| 시점 | 1회 Run | Pre 1회 + Post 1회 (같은 job) |
| 체크 목록 | `health_check_common.yaml` | `config/os_upgrade_pre.yaml`, `os_upgrade_post.yaml` (신규) |
| UCS | 점검 후 optional | Pre에서 **필수 권장**, Post에서 재확인 |
| 코드 재사용 | — | `collector`, `BigipClient`, `common_eval`, `evaluate_common`, 리포트 렌더러 |

**구현 전략:** `app/modules/os_upgrade/` 에 orchestrator 추가; 수집은 health_check collector **위임** 또는 공통 `collect_snapshot(profile)` 추출.

---

## 5. 체크 항목 (초안 — 구현 시 YAML화)

### Pre (사전)

- 현재 버전 (`/tm/sys/version`, F5OS version)
- HA 상태 (Active/Standby/In Sync, Force Offline = blocker)
- 디스크 여유 (`df`, `/var`, `/shared`)
- Config sync / UCS 최신 여부
- NTP 동기
- Pool/VS availability 요약 (다운 개수)
- APM/AWAF provision 여부 (해당 시)
- rSeries: F5OS + tenant 연결성

### Post (사후)

- Pre 항목 **전부** 재실행
- **Target version** 도달 여부
- HA 정상 복귀
- Self-IP / route / VLAN 인터페이스 (Pre 대비 diff)
- 서비스 재기동 흔적·에러 로그 샘플 (선택)

### Diff 규칙

| 변화 | 심각도 |
|------|--------|
| 버전 미변경 (post) | fail |
| HA worse (Active→Offline) | fail |
| down IF 증가 | fail |
| disk 사용률 +10%p | warn |
| 신규 error log 키워드 | warn |

---

## 6. 데이터·파일 레이아웃

```
output/<job_id>/
  job_meta.json          # site, target_version, window, devices
  pre_snapshot/
    raw_collection.json
    report.html          # optional pre-only
  post_snapshot/
    raw_collection.json
  diff_report.html
  rollback_checklist.md
  audit.log
```

Job DB: 기존 `JobStore` 에 `job_type: os_upgrade_check` 추가.

---

## 7. 구현 로드맵 (제안)

| 단계 | 산출 | 참고 |
|------|------|------|
| M0 | 메뉴명·placeholder·본 CRD | ✅ |
| M1 | `os_upgrade_pre.yaml` / `post.yaml` + 스냅샷 collector | ✅ `run_os_upgrade_snapshot` |
| M2 | `OsUpgradeCheckView` GUI (Pre/Post 버튼, job 연결) | `health_check_view.py` 패턴 |
| M3 | diff 엔진 + HTML 템플릿 | `templates/` |
| M4 | rollback_checklist.md 생성기 | findings 규칙 |
| M5 | rSeries F5OS 경로 통합 테스트 | `test_f5os_common.py` |

---

## 8. 신규 채팅에서 시작하는 방법

### 8.1 첫 메시지에 붙여넣기

```
다음 챕터: OS 업그레이드 간 점검 (os_upgrade 모듈).
docs/os_upgrade_check_crd.md 를 기준으로 M1부터 구현해줘.
업그레이드 실행은 하지 않고 Pre/Post 수집 + diff 리포트만.
Health Check GUI/연결 모델 재사용.
```

### 8.2 꼭 @ 로 열 파일

| 파일 | 이유 |
|------|------|
| `docs/os_upgrade_check_crd.md` | 본 CRD |
| `docs/spec.md` §3.5, §4.4 | 모듈 IO 스펙 |
| `app/gui/views/health_check_view.py` | GUI·Run 패턴 |
| `app/modules/health_check/collector.py` | job runner |
| `app/gui/main_window.py` | nav 슬롯 index 4 |
| `config/health_check_common.yaml` | 체크리스트 YAML 형식 참고 |

### 8.3 로컬 실행

```bat
scripts\setup_dev.cmd
scripts\run_gui.cmd
```

메뉴 **「OS 업그레이드 간 점검」** 선택 → placeholder 확인 (M2 이후 실화면).

### 8.4 백업 기준

정기점검 완료 스냅샷: `backups/정기점검완료_*.zip` (2026-05-22)

---

## 9. 열린 질문 (새 채팅에서 결정)

1. Pre/Post를 **한 job**에 묶을지, Pre job / Post job 분리할지 (권장: 한 job + `phase` 필드).
2. Target version을 수동 입력만 할지, F5 릴리즈 매트릭스 JSON 연동할지.
3. Post-check 전 “동일 연결 프로필” 검증 (IP/hostname hash).
4. PDF export 필요 여부 (spec에는 phase 2 optional).

---

## 10. 명명 규칙 (코드)

| 용도 | 이름 |
|------|------|
| 패키지 | `app/modules/os_upgrade/` |
| GUI 뷰 | `OsUpgradeCheckView` (예정) |
| Worker | `OsUpgradeCheckWorker` |
| Job type | `os_upgrade_check` |
| 메뉴 | `OS 업그레이드 간 점검` |

**사용하지 않을 표현:** “OS Upgrade 실행”, “Upgrade Now”, “Install image”.

---

*정기점검(Health Check) 챕터 완료 후 분기. 상세 일정은 `docs/roadmap.md` Phase 2 참고.*
