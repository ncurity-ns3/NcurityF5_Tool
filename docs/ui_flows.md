# ui flows and wireframes

version: 0.1  
parent: [gui_design.md](gui_design.md)

---

## 1. app entry

```mermaid
flowchart TD
  start([앱 시작]) --> main[메인 창]
  main --> home[home]
  main --> dev[devices]
  main --> jobs[jobs 메뉴]
  main --> rep[reports]
  main --> set[settings]
```

---

## 2. health_check — primary field flow

엔지니어 **기대 경로**: target mode → mgmt ip + id/pw → (세션 유지) → 점검 → **인앱** 리포트.

```mermaid
flowchart LR
  s0[0. Target Mode\nSingle or Multiple] --> s1[1. Device Connection]
  s1 --> s2[2. Check Items]
  s2 --> s3[3. Site Info]
  s3 --> s4[4. Run]
  s4 --> s5[5. Embedded Report]
```

### 2.0 multiple mode

```mermaid
flowchart TD
  m0[Multiple selected]
  m0 --> table[Device table\nlabel + ip + port]
  table --> cred[Shared ID/PW]
  cred --> test[Test Connection per row\nor Test All]
  test --> sess[Session per host:port]
  sess --> run[Run: sequential collect]
  run --> rep[Single job report\nsections per device]
```

### 2.1 fixture 분기

```mermaid
flowchart TD
  s1[장비 연결 화면]
  s1 -->|fixture 체크| mock[fixture json 로드]
  s1 -->|미체크| live[icontrol login + get]
  mock --> s2[점검 항목]
  live --> test{연결 테스트}
  test -->|ok| s2
  test -->|fail| s1
```

---

## 3. session + profile (per mgmt ip)

```mermaid
flowchart TD
  form[연결 폼 + Test Connection]
  form --> login[icontrol login]
  login --> mem[SessionManager\nhost:port → token in RAM]
  mem --> reuse[같은 IP 재작업\n토큰 재사용]
  form --> prof[device profile json]
  prof --> saveuser[username + host + label saved]
  prof --> nopw[password never saved]
  reuse --> job[health_check job]
```

---

## 4. initial_setup — design-only

```mermaid
flowchart TD
  a[모드: 설계만] --> b[네트워크 폼]
  b --> c[검토 화면]
  c --> d[산출물 생성]
  d --> e[폴더 열기]
  note[장비 apply 없음]
```

---

## 5. vpe_macro — design-only

```mermaid
flowchart TD
  a1[인증 방식] --> a2[리소스 모델]
  a2 --> a3[mfa 선택]
  a3 --> a4[검토 + mermaid]
  a4 --> a5[산출물 생성]
```

---

## 6. os upgrade (phase 2)

```mermaid
flowchart TD
  pre[pre-check 수집] --> manual[엔지니어 수동 upgrade\n앱은 대기 안내]
  manual --> post[post-check 수집]
  post --> diff[diff 리포트]
  diff --> rb[rollback checklist]
```

---

## 7. ascii wireframe — connection screen (primary)

```
+----------------------------------------------------------+
|  Health Check  >  Step 1/4  |  장비 연결                  |
+----------------------------------------------------------+
|  Target Mode:  (•) Single   ( ) Multiple                  |
|                                                          |
|  Platform:    [ BIG-IP TMOS (VE)  ▼ ]   ← TMOS only ph.1 |
|                                                          |
|  --- Single ---                                          |
|  라벨         [____________________________]             |
|  MGMT IP      [________________]  Port [443]             |
|  사용자 ID    [____________________________]             |
|  비밀번호     [****************************]  [👁]         |
|                                                          |
|  --- Multiple: device table + shared ID/PW above ---     |
|                                                          |
|  [ ] Fixture Mode                                        |
|  세션: 203.0.113.10 — logged in as admin (until exit)    |
|                                                          |
|     [ Test Connection ] [ Disconnect ]  [ Next > ] [Cancel]|
|  같은 IP 작업 중에는 로그인 상태를 유지합니다.             |
+----------------------------------------------------------+
```

---

## 8. job state (gui ↔ backend)

| ui state | backend |
|----------|---------|
| idle | — |
| validating | pydantic validators |
| connecting | `BigipClient.authenticate` |
| collecting | `TmosCollector.collect` |
| rendering | `render_*_report` |
| completed | `JobStatus.completed` |
| failed | `JobStatus.failed` + exceptions.json |

---

## 9. error ux matrix

| error | user message | recovery |
|-------|--------------|----------|
| ssl verify fail | 인증서 검증 실패. lab이면 지문 신뢰 선택 | tls 옵션 |
| 401 | 로그인 실패. id/pw 확인 | 재입력 |
| timeout | 장비 응답 없음. ip/망 확인 | retry |
| change blocked | 변경 모드 꺼짐 (정상) | info only |

---

*end of ui flows*
