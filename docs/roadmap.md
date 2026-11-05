# development roadmap

version: 0.1
horizon: 12 months (3 phases)
product: f5 field automation platform (windows offline)

---

## overview

| phase | name | duration (est.) | theme | risk level |
|-------|------|-----------------|-------|------------|
| 1 | safe poc | 8–10 weeks | platform shell + health_check + design-only modules | low |
| 2 | depth & upgrade assist | 10–12 weeks | expanded collectors, os upgrade diff, preview | medium |
| 3 | controlled change | 12+ weeks | opt-in apply pipeline with safety gate | high |

모든 phase는 **운영 장비 자동 변경 없음**을 기본으로 하며, phase 3에서만 명시적 opt-in 후 제한적 apply를 제공한다.

---

## phase 1 — safe poc (weeks 1–10)

### objectives

- 전체 아키텍처 골격 구현 (gui, core, adapters, output, job/audit)
- **가장 안전한 기능**부터 end-to-end: `health_check` (read-only) + 리포트
- 설계 전용: `initial_setup`, `vpe_macro` (subset)
- windows 오프라인 설치 패키지 1차

### milestones

| week | milestone | exit criteria |
|------|-----------|---------------|
| 1–2 | project bootstrap | pyproject, ci local script, directory per spec, synthetic fixtures |
| 2–3 | core + safety stubs | pydantic models, job store sqlite, audit log, credential mgr (keyring) |
| 3–4 | tmos read adapter | icontrol rest get subset: system, failover, vlan, self, route, pool summary |
| 4–5 | health_check module | check profiles yaml, collector orchestration, exception severity |
| 5–6 | output engine | html + xlsx + md from single `report_context` model |
| 6–7 | gui shell | main window, job wizard, device profile form, report viewer |
| 7–8 | initial_setup (design) | network profile → tmsh + design md + validation checklist |
| 8–9 | vpe_macro (design) | ad, radius, group resource assign → design md + apply_commands.txt |
| 9–10 | package + field test | pyinstaller build, lab big-ip smoke, security scan pass |

### phase 1 feature checklist

- [ ] offline application start (no network to internet)
- [ ] connect to lab big-ip with session credential (memory/keyring)
- [ ] run health_check against 1..n devices
- [ ] generate html/xlsx/md report under user output dir
- [ ] generate initial_setup artifacts without device connection
- [ ] generate vpe_macro design for ad/radius/group assign
- [ ] audit log for all jobs (no passwords)
- [ ] settings: output path, timeout, check profile selection

### phase 1 exclusions

- oauth, saml, fido macro templates
- os upgrade module (beyond placeholder menu)
- live config apply
- rseries/f5os live collectors (documentation stubs only)
- pdf export

---

## phase 2 — depth & upgrade assist (weeks 11–22)

### objectives

- 정기점검 범위 확대 (apm, cert expiry, config drift)
- vpe macro 전 인증/mfa 패턴 템플릿화
- os upgrade pre/post/diff/rollback **문서·리포트** (upgrade 실행은 수동)
- tmsh/rest **preview diff** (file vs live or snapshot vs snapshot)
- plugin hook for customer-specific checks

### milestones

| week | milestone | exit criteria |
|------|-----------|---------------|
| 11–12 | expanded tmos collector | apm sessions, cert list (metadata), disk detail |
| 12–14 | baseline drift | import prior `raw_collection.json`, highlight changes |
| 14–16 | vpe_macro expansion | oauth, saml, account resource, google/f5 otp templates |
| 16–18 | os_upgrade module | pre snapshot, post snapshot, diff_report.html, rollback md |
| 18–19 | preview engine | side-by-side diff ui for tmsh blocks |
| 19–20 | rseries/f5os | checklist templates + read adapter poc (lab only) |
| 20–22 | hardening | performance tuning, gui polish, installer signing prep |

### phase 2 feature checklist

- [ ] health_check apm/ltm extended profile
- [ ] drift comparison vs uploaded baseline
- [ ] os_upgrade job type with manual upgrade gate in ui
- [ ] vpe_macro all auth methods (design-only)
- [ ] irule skeleton generator with attachment checklist
- [ ] plugin sample: custom check registered via entry point
- [ ] optional pdf report export

---

## phase 3 — controlled change (weeks 23+)

### objectives

- safety gate 완성: preview → diff → rollback artifact → approval → apply batch
- initial_setup **guided apply** (lab/default off in production profile)
- vpe macro lab apply helper (export bundle for import, not direct prod default)
- signed offline update package
- security review remediation

### milestones

| milestone | exit criteria |
|-----------|---------------|
| change mode framework | global kill switch + per-module enable + local unlock |
| ucs/snapshot before apply | automatic local backup request before any `WR` op |
| batch apply executor | tmsh/rest with per-step success/fail + auto-stop on error |
| rollback workflow | restore procedure linked to pre-change ucs path |
| rseries/f5os adapters | parity with tmos where api documented |
| release 1.0 | signed installer, release notes, operator guide |

### phase 3 exclusions (permanent)

- unattended production change
- automatic os image install / reboot
- storing ssl private keys or customer passwords in project files
- mcp or cloud control plane

---

## cross-phase deliverables

| deliverable | phase 1 | phase 2 | phase 3 |
|-------------|---------|---------|---------|
| operator guide (ko) | draft | complete | maintained |
| lab setup guide | draft | complete | maintained |
| synthetic fixtures | yes | expand | expand |
| windows installer | zip | zip + optional msi | signed |
| version schema | semver 0.1.x | 0.2.x | 1.0.0 |

---

## dependency graph (simplified)

```
core + safety_gate
    ├── adapters/tmos (read)
    │       ├── health_check
    │       └── os_upgrade (phase 2)
    ├── output engine
    │       └── all modules
    ├── initial_setup (GEN)
    ├── vpe_macro (GEN)
    └── preview/apply (phase 2–3, depends on safety_gate)
```

---

## risk register

| risk | impact | mitigation | phase |
|------|--------|------------|-------|
| icontrol rest variance by tmos version | collector failures | version matrix + feature flags in adapter | 1+ |
| gui complexity | delayed delivery | narrow phase 1 screens; wizard pattern | 1 |
| secret leakage in logs | compliance | redaction middleware + security tests | 1 |
| engineer expectation of auto-apply | misuse | ui defaults + training docs | 1+ |
| pyinstaller false positives (av) | deployment blocked | code signing, vendor whitelist guide | 2–3 |
| offline dependency updates | stale libs | quarterly maintenance release process | 2+ |

---

## success metrics

| metric | phase 1 | phase 2 | phase 3 |
|--------|---------|---------|---------|
| health_check time (1 device) | < 3 min | < 2 min | < 2 min |
| report generation | < 30 s | < 20 s | < 20 s |
| critical secret in output files | 0 | 0 | 0 |
| lab apply success (guided) | n/a | n/a | > 95% in lab |
| engineer manual steps reduced | 30% vs manual | 50% | 60% |

---

## release naming

- `0.1.0` — phase 1 poc internal
- `0.2.0` — phase 2 beta (selected customers)
- `1.0.0` — phase 3 ga (change mode opt-in documented)

---

*aligns with `docs/spec.md` section 7*
