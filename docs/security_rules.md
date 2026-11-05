# security rules

version: 0.1
applies to: f5 field automation platform — all phases
classification: mandatory for developers and operators

---

## 1. purpose

고객사 현장에서 오프라인으로 실행되는 도구이므로, **비밀정보 비저장**, **최소 권한**, **변경 통제**, **감사 가능성**을 최우선으로 한다. 본 문서는 구현·운영·배포 시 반드시 준수할 규칙이다.

---

## 2. data classification

| class | examples | storage | in repo/samples |
|-------|----------|---------|-----------------|
| public | product version, check profile names | anywhere | yes |
| internal | job metadata, sanitized stats | local sqlite/logs | synthetic only |
| confidential | mgmt ip, hostname, config excerpts | local job output (customer controlled) | **never real customer** |
| secret | password, token, api key, private key, session cookie | **memory or os keyring only** | **never** |

---

## 3. absolute prohibitions

다음은 **어떤 phase에서도 금지**:

1. password, token, private key, session cookie를 파일·sqlite·로그·리포트·git에 기록
2. 실제 고객사 ip, 계정명, 도메인, 설정 전문, qkview, ucs를 repository·기본 샘플·단위테스트 fixture에 포함
3. mcp 또는 외부 클라우드로 장비 정보·수집 결과 자동 전송 (기본값)
4. 사용자 승인 없이 운영 장비에 write/delete/reboot/failover 실행
5. telemetry, auto-update phone-home (phase 3에서도 기본 off)
6. ssl private key를 로컬 output에 export (메타데이터·만료일만 허용)

---

## 4. credential handling

### 4.1 input

- gui에서 password 입력 시 **password echo off**, clipboard copy 금지
- "remember password" 옵션 **제공하지 않음** (phase 1–3)
- optional: windows credential manager (`keyring`)에 **세션 단위** 저장 — 사용자 명시 동의 시만, 항목명 `f5tool/{job_id}`

### 4.2 runtime

- credentials는 `SecretStr` 타입으로 메모리에만 유지
- http/ssh 클라이언트에 전달 후 참조 최소화; job 종료 시 clear
- exception traceback에 credential 값 포함 금지 (custom exception handler)

### 4.3 output

- 리포트·json·html에 auth header, cookie, `X-F5-Auth-Token` 값 마스킹
- tmsh 출력 중 `password`, `secret`, `private-key` 블록은 `[REDACTED]` 치환

---

## 5. logging and audit

### 5.1 application log

- level: info default; debug는 개발 빌드만
- 구조화 필드: `timestamp`, `level`, `module`, `job_id`, `message`
- 금지: full rest response body (config 객체), authorization headers

### 5.2 audit log (immutable append)

기록 대상:

- job start/end, module, mode (`RO|GEN|PRE|WR|DEST`)
- operator (windows username)
- device profile id (not password)
- artifact paths generated
- approval events (who, when, diff hash)
- apply step results (success/fail, command **hash** not plaintext secret)

보존: 사용자 로컬 `%LOCALAPPDATA%\f5tool\audit\`; 고객 정책에 따라 수동 삭제

---

## 6. change control (safety gate)

모든 `WR` / `DEST` 작업은 다음을 **모두** 만족해야 실행 가능:

| step | requirement |
|------|-------------|
| 1 preview | 적용 대상 명령/payload 목록 표시 |
| 2 diff | 현재 상태 vs 제안 상태 (또는 파일 vs live) |
| 3 rollback | ucs 경로 또는 역순 tmsh 스크립트 artifact 존재 |
| 4 approval | ui에서 명시적 checkbox + "APPLY" 입력 (phase 3) |
| 5 scope | 대상 device list 재확인 |

**kill switch:** settings `change_mode_enabled=false` (default)이면 adapter의 write 메서드는 `ChangeModeDisabledError` 발생.

---

## 7. read-only vs write enforcement

| operation class | network call | default |
|-----------------|--------------|---------|
| `RO` | GET only | allowed |
| `GEN` | none (local files) | allowed |
| `PRE` | GET + local simulate | phase 2+ |
| `WR` | POST/PATCH/DELETE | blocked unless change mode |
| `DEST` | destructive | blocked + double confirm |

adapter 구현은 base class에서 `write_*` 메서드가 safety gate 데코레이터를 통과하도록 강제한다.

---

## 8. high-risk feature policy

`docs/spec.md` section 6 목록(h01–h12)에 해당하는 기능:

- gui에 ⚠ 표시 및 별도 확인 dialog
- production profile: 메뉴 숨김 또는 disabled
- lab profile: change mode + approval 후만
- h08 (reboot/upgrade execute): **도구가 자동 실행하지 않음** — 체크리스트·리포트만

---

## 9. local data storage

| path | content | encryption |
|------|---------|------------|
| `%LOCALAPPDATA%\f5tool\jobs\` | job json, sanitized collections | optional dpapi (phase 2) |
| `%LOCALAPPDATA%\f5tool\reports\` | html/xlsx/md | customer responsibility |
| `%LOCALAPPDATA%\f5tool\logs\` | redacted logs | rotate 30 days default |
| `%LOCALAPPDATA%\f5tool\audit\` | audit events | append-only file |

usb portable 실행 시: 동일 구조를 usb 하위에 두되, 분실 시 노출 위험을 operator guide에 명시.

---

## 10. repository naming convention

- all file and folder names: **lowercase** only
- word separation: **underscore** (`_`); no spaces, no uppercase, no hyphen
- enforced in ci/local via `python tools/check_naming.py .` and `tests/test_naming_convention.py`
- examples: `docs/spec.md`, `app/core/bigip_client.py`, `tests/test_naming_convention.py`

---

## 11. repository and build security

### 10.1 source repo

- `.gitignore`: `*.ucs`, `*.qkview`, `*.pem`, `*.key`, `.env`, `output/`, `jobs/`
- pre-commit hook (recommended): secret pattern scan (gitleaks or custom)
- pr review: no real customer data in fixtures

### 10.2 synthetic data only

- ip: `203.0.113.0/24`, `198.51.100.0/24`
- hostnames: `*.example.invalid`
- ad groups: `lab-group-01` etc.

### 10.3 build pipeline

- reproducible `requirements.txt` hashes (pip-tools)
- pyinstaller spec에 불필요 모듈 제외
- optional: code signing certificate for `f5tool.exe` (phase 3)

---

## 12. transport security

- icontrol rest: **https only**; certificate verify default **on**
- self-signed lab devices: per-device "trust fingerprint once" — fingerprint를 로컬 device profile에 저장 (pem 전체 저장 금지, fingerprint만)
- tls 1.2+ only; weak cipher disable via httpx/ssl context
- ssh: host key verification; no `AutoAddPolicy` in production code path

---

## 13. gui security

- no embedded browser remote content (offline)
- export path user-selectable; default not system32
- open report in browser uses `file://` local only
- disable external link auto-fetch

---

## 14. incident response (operator)

수집물·리포트에 민감정보가 포함되었을 suspected 시:

1. 해당 job output 디렉터리 삭제
2. audit log 해당 `job_id` 기록 확인
3. credential manager 항목 삭제
4. 필요 시 고객 csirt 절차에 따라 장비 비밀번호 로테이션 (도구 외부)

---

## 15. compliance checklist (release gate)

release 전 필수 확인:

- [ ] `grep`/scanner: repo에 password, `BEGIN PRIVATE KEY`, bearer token 없음
- [ ] unit test: log redaction, report redaction 통과
- [ ] change mode default off verified
- [ ] audit log writes on all job types
- [ ] operator guide에 "no secrets on disk" 명시
- [ ] offline install 문서에 usb 분실 위험 명시

---

## 16. role-based expectations

| role | responsibility |
|------|----------------|
| developer | enforce rules in code review; no real data in tests |
| field engineer | use lab profile on non-prod; never save password to project |
| customer admin | control output directory permissions; usb policy |

---

*violations of section 3 are release blockers*
