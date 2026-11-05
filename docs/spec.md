# f5 field automation platform — product specification

version: 0.1 (design)
status: backend poc done; **gui design** in progress
target: windows offline gui tool for f5 engineers at customer sites

**gui / ux (선행 설계):** [gui_design.md](gui_design.md), [ui_flows.md](ui_flows.md), [gui_field_catalog.md](gui_field_catalog.md)

---

## 1. product vision

현장 f5 엔지니어가 반복 수행하는 **설치·초기 설정·apm vpe macro 설계·정기점검·os upgrade** 작업을 하나의 오프라인 플랫폼에서 지원한다. 단순 점검 스크립트가 아니라, **수집 → 분석 → 산출물 생성 → (선택) 승인 후 적용** 파이프라인을 갖춘 엔지니어링 워크벤치다.

### 1.1 design principles

| principle | description |
|-----------|-------------|
| offline-first | 인터넷 없이 실행; 모든 의존성·템플릿·문서를 패키지에 포함 |
| read-first | 1차 구현은 read-only 수집·리포트·설계 산출에 집중 |
| human-in-the-loop | 장비 변경은 preview → diff → rollback plan → explicit approval |
| no secrets on disk | password, token, private key는 메모리·os credential store만 사용 |
| no customer data in repo | 샘플은 합성(faker) 데이터만; 실제 ip/계정/로그/설정 전문 금지 |
| platform abstraction | big-ip ve / rseries / f5os / tmos 공통 인터페이스 + 제품별 adapter |

### 1.2 supported platforms (target matrix)

| platform | api / access | phase 1 | phase 2 | phase 3 |
|----------|--------------|---------|---------|---------|
| big-ip tmos (ve) | icontrol rest, tmsh, ssh | read + artifact gen | guided apply (approval) | full initial config |
| rseries | f5os rest / redfish (where applicable) | read + checklist | artifact gen | upgrade assist |
| f5os | platform-specific api | checklist templates | read collectors | upgrade assist |

---

## 2. overall architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     presentation (windows gui)                          │
│  pyqt6 / pyside6  —  wizards, dashboards, diff viewer, report viewer   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                     application layer (use cases)                       │
│  initial_setup │ vpe_macro │ health_check │ os_upgrade │ job_orchestrator│
└─────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  core domain  │         │  safety gate    │         │  output engine  │
│  models,      │         │  preview, diff, │         │  html, xlsx,    │
│  validators   │         │  rollback, audit  │         │  md, json, ucs  │
└───────────────┘         └─────────────────┘         └─────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                     infrastructure layer                                │
│  device adapters │ collectors │ template engine │ credential mgr       │
│  file store (local) │ job queue │ logging (sanitized) │ plugin registry  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                     external (runtime only, not in repo)                │
│  customer big-ip / rseries / f5os — https/ssh — session credentials    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.1 execution modes

| mode | code | description | default |
|------|------|-------------|---------|
| offline design | `design` | 장비 연결 없이 입력·템플릿만으로 산출물 생성 | yes (phase 1) |
| read-only collect | `collect` | 장비에서 상태·설정 읽기만 | yes (phase 1) |
| generate artifacts | `generate` | tmsh/rest payload, macro script, checklist 파일 생성 | yes (phase 1) |
| preview change | `preview` | 적용 전 diff·영향 분석 (파일 또는 dry-run) | phase 2 |
| apply change | `apply` | 사용자 승인 후 명령 전송 | phase 3, opt-in |

### 2.2 job lifecycle

```
create job → validate inputs → [connect] → collect/design → analyze
    → generate outputs → [preview diff] → [user approval] → [apply]
    → post-verify → archive report → close job
```

모든 job은 `job_id`, `timestamp`, `operator` (로컬 windows 사용자), `module`, `mode`, `device_profile`(민감정보 제외) 메타데이터를 로컬 audit log에 기록한다.

---

## 3. module structure

### 3.1 module map

```
src/f5tool/
├── app/                 # gui entry, main window, navigation
├── core/                # shared models, validators, safety gate
├── adapters/            # tmos, rseries, f5os device connectors
├── modules/
│   ├── initial_setup/
│   ├── vpe_macro/
│   ├── health_check/
│   └── os_upgrade/
├── output/              # report renderers (html, xlsx, md)
├── templates/           # jinja2 / yaml skeletons (no secrets)
└── plugins/             # optional customer-specific extensions
```

### 3.2 initial setup module (`initial_setup`)

**purpose:** greenfield / rebuild 시 필요한 초기 네트워크·시스템·라이선스·provisioning 설계 및 적용 후보 산출.

**subcomponents:**

| subcomponent | responsibility |
|--------------|----------------|
| profile builder | mgmt ip, vlan, self ip, route, dns, ntp, hostname 입력·검증 |
| license planner | license pool 참조(오프라인 파일 경로만), activation command 생성 |
| provisioning planner | ltm, apm, afm 등 모듈 활성화 계획 |
| artifact generator | tmsh script, rest json, ansible-style task list (apply 금지 기본) |
| platform router | ve vs rseries vs f5os 분기 |

### 3.3 vpe macro module (`vpe_macro`)

**purpose:** apm vpe macro 설계서, 설정 템플릿, 적용 후보 명령, 검증 절차 생성. **운영 장비 직접 반영 없음 (phase 1–2).**

**macro families:**

| family | outputs |
|--------|---------|
| ad authentication | ldap/ad server profile, aaa server, vpe branch |
| radius authentication | radius server, aaa, vpe branch |
| oauth / saml | idp connector sketch, access policy branch, attribute mapping table |
| resource assign (group) | ad group → resource group → webtop/portal mapping matrix |
| resource assign (account) | username variable → dynamic assignment table |
| mfa (google otp, f5 otp, fido) | mfa action sequence, session variable map |
| irule linkage | irule skeleton, vs/policy attachment checklist (no live push) |

### 3.4 health check module (`health_check`)

**purpose:** 정기점검 데이터 자동 수집, 사용자 최소 입력, 리포트 생성.

**check categories:**

| category | examples |
|----------|----------|
| system | version, uptime, disk, memory, cpu, failover state |
| network | vlan, self ip, route, dns resolve test result |
| ltm | pool/node/vip summary, availability |
| apm | session count, license usage, aaa status |
| security | cert expiry, cipher profile names (not private keys) |
| config drift | hash/compare vs baseline file (user-provided) |

### 3.5 os upgrade module (`os_upgrade`)

**purpose:** upgrade 전후 pre/post check, diff, rollback checklist, 작업 리포트.

**workflow:**

```
pre-check collect → baseline snapshot → [manual upgrade window]
→ post-check collect → diff engine → rollback checklist → signed report
```

---

## 4. inputs and outputs per module

### 4.1 initial setup

| direction | name | type | required | notes |
|-----------|------|------|----------|-------|
| in | `platform_type` | enum | yes | `tmos_ve`, `rseries`, `f5os` |
| in | `deployment_profile` | yaml/json | yes | network, dns, ntp, hostname |
| in | `license_reference` | path | no | 오프라인 license 파일 경로만 |
| in | `provisioning_plan` | object | no | 모듈별 on/off |
| in | `connection_profile` | object | phase 2+ | host, port; creds via credential mgr |
| out | `setup_design.md` | markdown | yes | human-readable design |
| out | `tmsh_initial.tcl` | script | yes | apply 후보 (not auto-run) |
| out | `rest_payloads/*.json` | json | optional | icontrol rest bodies |
| out | `validation_checklist.md` | markdown | yes | post-apply verification steps |
| out | `risk_assessment.json` | json | yes | change risk score |

### 4.2 vpe macro

| direction | name | type | required | notes |
|-----------|------|------|----------|-------|
| in | `auth_method` | enum | yes | ad, radius, oauth, saml |
| in | `idp_metadata` | file/path | conditional | saml/oauth; no secrets in saved project |
| in | `resource_model` | enum | yes | `by_group`, `by_account` |
| in | `group_mapping_table` | csv/yaml | conditional | ad group → resource |
| in | `mfa_methods` | list | no | google_otp, f5_otp, fido |
| in | `irule_required` | bool | no | generates irule template |
| out | `vpe_design.md` | markdown | yes | macro flow diagram (mermaid) |
| out | `macro_config_template.yaml` | yaml | yes | logical policy structure |
| out | `apply_commands.txt` | text | yes | ordered tmsh/api steps |
| out | `verification_procedure.md` | markdown | yes | test users, expected results |
| out | `irule_template.tcl` | tcl | optional | skeleton only |

### 4.3 health check

| direction | name | type | required | notes |
|-----------|------|------|----------|-------|
| in | `device_targets` | list | yes | mgmt ip, label; no stored password |
| in | `check_profile` | yaml | yes | which categories to run |
| in | `customer_context` | form fields | no | site name, period, engineer notes |
| in | `baseline_archive` | zip/path | no | prior run for drift |
| out | `raw_collection.json` | json | yes | sanitized (no secrets) |
| out | `report.html` | html | yes | primary deliverable |
| out | `report.xlsx` | xlsx | yes | executive summary sheet |
| out | `report.md` | markdown | optional | git-friendly |
| out | `exceptions.json` | json | yes | failed checks, severity |

### 4.4 os upgrade

| direction | name | type | required | notes |
|-----------|------|------|----------|-------|
| in | `upgrade_target_version` | string | yes | target image/version |
| in | `device_targets` | list | yes | same as health check |
| in | `pre_check_profile` | yaml | yes | extends health check |
| in | `post_check_profile` | yaml | yes | typically superset of pre |
| in | `maintenance_window` | datetime range | no | report metadata |
| out | `pre_snapshot/` | directory | yes | json + checksum manifest |
| out | `post_snapshot/` | directory | yes | after manual upgrade |
| out | `diff_report.html` | html | yes | before/after comparison |
| out | `rollback_checklist.md` | markdown | yes | ordered recovery steps |
| out | `upgrade_result_report.pdf` | pdf | phase 2 | optional export |

---

## 5. read-only vs write/change separation

### 5.1 classification

| class | tag | allowed operations | gui default |
|-------|-----|------------------|-------------|
| read-only | `RO` | get, list, show, stats, download (config sans secrets) | enabled |
| generate-only | `GEN` | template render, file write to **local output dir only** | enabled |
| preview | `PRE` | dry-run parse, diff vs live or snapshot, simulate tmsh | enabled phase 2 |
| write | `WR` | post/patch/delete on device, config merge, license activate | disabled; explicit unlock |
| destructive | `DEST` | delete partition, overwrite, failover force, reboot | disabled; double confirm |

### 5.2 enforcement layers

1. **module declaration:** each operation tagged `RO|GEN|PRE|WR|DEST` in registry.
2. **safety gate:** `apply` requests must pass preview + diff + rollback artifact present.
3. **gui policy:** write 클래스 메뉴는 settings에서 "enable change mode" + admin password (local) 필요.
4. **audit:** all `WR`/`DEST` logged with operator, timestamp, command hash (not password).

### 5.3 phase 1 boundary

phase 1 implements **only `RO` + `GEN`**. no network write calls.

---

## 6. high-risk features (production equipment)

다음 기능은 **high-risk**로 분류하며, 기본 비활성·이중 승인·rollback 필수:

| id | feature | risk | phase |
|----|---------|------|-------|
| h01 | live config merge / load sys config | service outage | 3 |
| h02 | license activation / reprovision | lockout | 3 |
| h03 | vlan/self ip/route change | mgmt loss | 3 |
| h04 | apm policy publish to production | auth outage | 3 |
| h05 | certificate install/replace | tls failure | 3 |
| h06 | pool member force disable | traffic drop | 3 |
| h07 | failover trigger / force standby | ha event | 3 |
| h08 | reboot / install image / upgrade execute | hard downtime | never auto; checklist only phase 1–2 |
| h09 | user/account delete on device | lockout | 3 |
| h10 | irule attach without lab test | app break | 2+ preview only |
| h11 | wide ip / gtm change | dns impact | 3 |
| h12 | secret file write (ssl key, cert key) | credential leak | never store; runtime only |

**phase 1–2:** h08 upgrade **실행**은 도구가 수행하지 않음. pre/post 수집·리포트·rollback 문서만.

---

## 7. development phases (1st / 2nd / 3rd)

### 7.1 phase 1 — safe poc (target: 8–10 weeks)

**goal:** 플랫폼 골격 + 가장 안전한 모듈 end-to-end (offline + read-only collect + report).

| deliverable | scope |
|-------------|-------|
| shell gui | navigation, job wizard, settings |
| core | models, validators, job store, audit log |
| adapter tmos | read-only icontrol rest collector (subset) |
| health_check | full collect + html/xlsx/md report |
| vpe_macro | design-only: ad + radius + group resource assign |
| initial_setup | design-only: network profile → tmsh artifact |
| security | credential mgr, sanitized logging |
| packaging | windows offline installer (pyinstaller) |

**out of scope phase 1:** live apply, os upgrade execution, oauth/saml/fido.

### 7.2 phase 2 — expand collectors & design depth

| deliverable | scope |
|-------------|-------|
| health_check | apm/ltm expanded checks, baseline drift |
| vpe_macro | oauth, saml, account resource, google/f5 otp templates |
| os_upgrade | pre/post snapshot, diff report, rollback checklist |
| initial_setup | rseries/f5os checklist templates |
| preview mode | tmsh diff viewer (file vs live) |
| plugins | customer extension hook |

### 7.3 phase 3 — controlled change (opt-in)

| deliverable | scope |
|-------------|-------|
| safety gate | full preview → approve → apply pipeline |
| initial_setup | guided apply batches (with rollback ucs) |
| vpe_macro | lab-only apply helper (never default) |
| adapters | rseries/f5os read write where api stable |
| hardening | pen-test fixes, signed updates |

---

## 8. recommended technology stack

| layer | choice | rationale |
|-------|--------|-----------|
| language | python 3.12+ | ecosystem, f5 community familiarity |
| gui | pyqt6 or pyside6 | native windows look, offline, rich widgets |
| http client | httpx | sync/async, timeout control |
| ssh/cli | paramiko + custom tmsh wrapper | fallback when rest unavailable |
| config/templates | pydantic v2 + jinja2 + pyyaml | validation + artifact gen |
| reports | jinja2 → html; openpyxl → xlsx; weasyprint or reportlab → pdf (phase 2) |
| diff | deepdiff, difflib | snapshot comparison |
| local db | sqlite (jobs, audit); no secrets column | offline metadata |
| credentials | keyring (windows credential manager) | no disk secrets |
| packaging | pyinstaller + optional briefcase | single-folder offline deploy |
| tests | pytest, pytest-qt, responses (http mock) | ci + offline |
| lint/format | ruff, mypy (strict core) | maintainability |

**explicitly excluded:** mcp, cloud sync default, telemetry phone-home, docker-as-runtime on customer pc (optional dev only).

---

## 9. test strategy (summary)

상세는 `docs/test_plan.md` 참조.

| level | focus |
|-------|-------|
| unit | validators, template render, sanitizers, diff engine |
| integration | mock icontrol rest (recorded fixtures), adapter contracts |
| gui | pytest-qt smoke flows |
| security | secret leak scan, log redaction, repo sample audit |
| field simulation | air-gapped vm: run full health_check against lab big-ip |

**fixtures policy:** all ips like `203.0.113.x` (rfc 5737), hostnames `lab-device-01.example.invalid`.

---

## 10. windows offline deployment

| aspect | approach |
|--------|----------|
| bundle | pyinstaller one-folder: `f5tool.exe` + `internal/` deps + `templates/` |
| size target | < 150 mb compressed zip (without customer data) |
| install | unzip to `C:\Tools\f5tool\` or portable usb; no admin required for user dir |
| updates | offline zip replace; optional signature verify (phase 3) |
| config | `%LOCALAPPDATA%\f5tool\` for jobs, reports, settings |
| logs | `%LOCALAPPDATA%\f5tool\logs\` with auto redaction |
| python runtime | embedded in bundle; customer machine needs no python install |

---

## 11. project directory structure

**naming rule:** all file and folder names are lowercase; word separation uses underscore (`_`); no spaces or uppercase. enforced by `tools/check_naming.py` and `tests/test_naming_convention.py`.

```
f5-field-automation/
├── docs/
│   ├── spec.md
│   ├── roadmap.md
│   ├── security_rules.md
│   ├── test_plan.md
│   └── worklog.md
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── bigip_client.py
│   │   ├── models.py
│   │   ├── safety_gate.py
│   │   ├── job_store.py
│   │   ├── audit.py
│   │   └── redaction.py
│   ├── adapters/
│   │   ├── base.py
│   │   └── tmos_collector.py
│   ├── modules/
│   │   ├── initial_setup/
│   │   ├── vpe_macro/
│   │   ├── health_check/
│   │   └── os_upgrade/
│   └── output/
├── templates/
├── tests/
│   ├── test_naming_convention.py
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── tools/
│   └── check_naming.py
├── scripts/
│   └── run_tests.ps1
├── pyproject.toml
├── requirements.txt
├── requirements_dev.txt
└── readme.md
```

---

## 12. non-functional requirements

| nfr | target |
|-----|--------|
| offline startup | < 5 s on typical laptop |
| collect timeout | configurable per device; default 120 s |
| report generation | < 30 s for 10 devices |
| accessibility | keyboard navigation for main flows |
| i18n | korean ui primary; english labels for tmsh/rest |
| logging | no full config blobs with secrets; truncate large fields |

---

## 13. glossary

| term | meaning |
|------|---------|
| vpe | visual policy editor (apm) |
| artifact | generated file intended for manual or approved apply |
| job | single end-to-end run of a module |
| safety gate | central policy enforcing preview/approval |
| adapter | platform-specific connector implementation |

---

## 14. open decisions (for review)

1. pyqt6 vs pyside6 license preference for commercial customer delivery
2. ucs/qkview import for baseline drift (phase 2)
3. whether pdf export is mandatory in phase 2 reports
4. local "change mode" unlock: windows hello vs static local passphrase

---

*end of specification*
