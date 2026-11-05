# test plan

version: 0.1
product: f5 field automation platform
scope: phase 1 primary; phase 2–3 extensions noted

**Health Check GUI 수동·디버깅:** [gui_test_debug_plan.md](gui_test_debug_plan.md)  
**제품 요구사항 통합:** [prd.md](prd.md)

---

## 1. objectives

- **안전성:** secret 미저장, read-only 기본, change gate 동작 검증
- **정확성:** collector·template·report 출력이 스펙과 일치
- **신뢰성:** 오프라인·장시간 job·다중 device에서 안정 동작
- **회귀:** adapter 버전 차이에 대한 fixture 기반 회귀

---

## 2. test levels

```
                    ┌─────────────────────┐
                    │  field simulation   │  lab big-ip, air-gapped pc
                    └──────────┬──────────┘
                    ┌──────────▼──────────┐
                    │  e2e (gui + job)    │  pytest-qt + mock device
                    └──────────┬──────────┘
                    ┌──────────▼──────────┐
                    │  integration        │  adapter + http mock
                    └──────────┬──────────┘
                    ┌──────────▼──────────┐
                    │  unit               │  pure functions, validators
                    └─────────────────────┘
```

| level | tool | run frequency |
|-------|------|---------------|
| unit | pytest | every commit |
| integration | pytest + responses/httpx mock | every commit |
| gui smoke | pytest-qt | daily / pre-release |
| e2e | scripted job json + mock or lab | pre-release |
| field simulation | manual checklist | phase gate |
| security | custom scripts + optional bandit | pre-release |

---

## 3. test environment

### 3.1 synthetic fixtures (mandatory)

- all tests use `tests/fixtures/` only
- ip addresses: rfc 5737 documentation ranges
- no imports from customer exports

### 3.2 lab environment (recommended)

| component | spec |
|-----------|------|
| big-ip | tmos 15.x or 16.x ve, dual instance optional |
| mgmt | isolated vlan, no internet |
| accounts | dedicated lab admin; password rotated outside repo |
| rseries/f5os | phase 2+ optional lab |

### 3.3 windows matrix

| os | arch | note |
|----|------|------|
| windows 10 | x64 | primary |
| windows 11 | x64 | primary |
| windows server 2019+ | x64 | optional enterprise |

---

## 4. phase 1 test scope by module

### 4.1 core

| id | case | type | pass criteria |
|----|------|------|---------------|
| c01 | pydantic model validation rejects invalid cidr | unit | validation error |
| c02 | job store crud | unit | sqlite roundtrip |
| c03 | audit append only | unit | no truncate API |
| c04 | SecretStr never in model_dump json | unit | `***` or exclude |
| c05 | safety gate blocks write when change mode off | unit | exception raised |

### 4.2 adapters (tmos read)

| id | case | type | pass criteria |
|----|------|------|---------------|
| a01 | get system version parses fixture | integration | version string match |
| a02 | failover status enum mapping | unit | active/standby |
| a03 | http timeout retries (configurable) | integration | mock delay |
| a04 | 401 response surfaces auth error without password in message | integration | sanitized error |
| a05 | tls verify failure stops connect | integration | ssl error |
| a06 | write method blocked at adapter base | unit | ChangeModeDisabledError |

### 4.3 health_check

| id | case | type | pass criteria |
|----|------|------|---------------|
| h01 | full profile collect against mock | integration | raw_collection.json schema |
| h02 | partial profile skips categories | unit | absent keys |
| h03 | multi-device job continues on single failure | integration | exceptions.json entry |
| h04 | html report contains severity summary | unit | snapshot html structure |
| h05 | xlsx executive sheet row counts | unit | openpyxl parse |
| h06 | md report generates without html deps | unit | file exists |
| h07 | log file contains no auth token substring | security | scan pass |

### 4.4 initial_setup (design)

| id | case | type | pass criteria |
|----|------|------|---------------|
| i01 | network profile → tmsh contains vlan/self | unit | golden file compare |
| i02 | invalid gateway for vlan rejected | unit | validation error |
| i03 | design md includes validation checklist section | unit | heading present |
| i04 | no network call in design mode | integration | mock call count 0 |

### 4.5 vpe_macro (design)

| id | case | type | pass criteria |
|----|------|------|---------------|
| v01 | ad auth template structure | unit | yaml schema valid |
| v02 | radius + group resource assign | unit | apply_commands ordering |
| v03 | mfa list empty vs google_otp branch | unit | conditional sections |
| v04 | irule flag adds skeleton tcl | unit | file generated |
| v05 | idp metadata path not copied into repo sample | security | path reference only |

### 4.6 gui (smoke)

| id | case | type | pass criteria |
|----|------|------|---------------|
| g01 | application launches | gui | window visible < 5s |
| g02 | create health_check job wizard | gui | job_id assigned |
| g03 | open generated html report | gui | viewer loads |
| g04 | settings persist output path | gui | restart retains |

### 4.7 packaging

| id | case | type | pass criteria |
|----|------|------|---------------|
| p01 | pyinstaller binary starts offline | manual | no pip/network |
| p02 | templates bundled | manual | dir exists beside exe |
| p03 | clean machine (no python) run | manual | health_check mock job |

---

## 5. phase 2 additional tests

| area | cases |
|------|-------|
| os_upgrade | pre/post snapshot checksum; diff engine detects version change |
| drift | baseline compare flags added/removed pools |
| vpe_macro | oauth/saml template validation; otp branch ordering |
| preview | tmsh diff ui lines added/removed count |
| plugins | sample plugin registers check id |
| pdf | pdf file size > 0; no raw secrets |

---

## 6. phase 3 additional tests

| area | cases |
|------|-------|
| safety gate | apply without rollback artifact blocked |
| approval | wrong confirmation token blocks apply |
| guided apply | mock device receives ordered posts; stop on 4xx |
| ucs backup | pre-apply step records ucs path in audit |
| kill switch | change mode off mid-session blocks new writes |

---

## 7. security test suite

| id | test | method |
|----|------|--------|
| s01 | repo secret scan | script greps patterns |
| s02 | log redaction | run job with fake token in mock response |
| s03 | report redaction | assert `[REDACTED]` in html output |
| s04 | credential not in sqlite | query all tables |
| s05 | change mode default | config load test |
| s06 | dependency audit | `pip audit` in dev only (documented) |

---

## 8. performance benchmarks

| scenario | target | measurement |
|----------|--------|-------------|
| app cold start | < 5 s | manual stopwatch / log timestamp |
| 1 device health_check | < 3 min phase 1 | job duration in audit |
| report gen 1 device | < 30 s | audit |
| 10 device sequential | < 25 min phase 1 | lab run |

실패 시 프로파일링은 개발 환경에서만 수행; 고객 pc 성능 이슈는 operator guide에 hw 권장사항 기재.

---

## 9. regression strategy

- **golden files:** tmsh/rest artifacts hash-compared in `tests/golden/` (synthetic input only)
- **fixture versioning:** `fixtures/tmos_15_1/`, `fixtures/tmos_16_1/`
- **ci script:** `scripts/run_tests.ps1` — unit + integration mandatory; gui optional flag
- **breaking adapter change:** bump fixture version dir, never overwrite old without review

---

## 10. defect severity

| severity | definition | release block |
|----------|------------|---------------|
| critical | secret leak, unintended write, data loss | yes |
| high | wrong report data, crash on core flow | yes for ga |
| medium | partial collector failure undetected | phase gate review |
| low | ui cosmetic | no |

---

## 11. test deliverables

| artifact | location |
|----------|----------|
| unit/integration tests | `tests/` |
| fixtures | `tests/fixtures/` |
| golden outputs | `tests/golden/` |
| field simulation checklist | `docs/field_simulation_checklist.md` (phase 1 gate) |
| test run log | ci artifact or local `test-results.xml` (pytest `--junitxml`) |
| naming convention | `tools/check_naming.py` + `tests/test_naming_convention.py` |

---

## 12. phase gate entry / exit

### phase 1 exit (go / no-go)

- [ ] all c01–c05, a01–a06, h01–h07, i01–i04, v01–v05 pass
- [ ] g01–g04 pass on windows 10/11
- [ ] s01–s05 pass
- [ ] p01–p03 field simulation signed by engineer
- [ ] zero critical/high open defects

### phase 2 exit

- phase 1 exit still valid
- os_upgrade and drift tests pass
- extended vpe tests pass

### phase 3 exit (1.0.0)

- apply pipeline tests pass on lab only
- security review checklist complete
- signed installer verified on clean vm

---

## 13. responsibilities

| role | duty |
|------|------|
| developer | write/maintain unit + integration tests with pr |
| qa / lead engineer | field simulation, phase gate sign-off |
| security reviewer | s01–s06 before external beta |

---

## 14. automation commands (reference)

```powershell
# development
python -m pytest tests/unit tests/integration -q
python -m pytest tests/gui -q --optional-gui

# with coverage (dev machine)
python -m pytest tests/unit tests/integration --cov=src/f5tool --cov-report=term-missing

# security scan (dev)
python tools/check_naming.py .
```

---

*implements verification for `docs/spec.md` and `docs/security_rules.md`*
