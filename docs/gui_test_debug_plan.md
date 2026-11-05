# Health Check GUI — 테스트·디버깅 계획

현장 테스트를 빠르게 반복하기 위한 **자동 테스트 + 수동 체크리스트 + 디버깅 절차**.

---

## 1. 자동 테스트 (매 수정 후)

### 1.1 실행

```powershell
cd "C:\Users\ejes3\Ejes_OneDrive\OneDrive - Ncurity\바탕 화면\WorksFiles\F5 Project\Config & Rules & Apps\AI First"
.\.venv\Scripts\activate
python -m pytest tests/ -q --tb=short
```

### 1.2 GUI 세션 관련 (필수)

| 파일 | 검증 내용 |
|------|-----------|
| `tests/test_device_list_store.py` | 목록 Save/Load/Delete |
| `tests/test_health_check_session_load.py` | 한글 목록 ID; profile_store와 list_store 분리 |
| `tests/test_f5os_client.py` | F5OS API 경로 |
| `tests/test_platform_router.py` | rSeries 라우팅 |

### 1.3 추가 권장 (다음 PR)

- `pytest-qt`로 `HealthCheckView._load_saved_session` 분기 스모크
- Multiple `snapshot()` → `save` → `rebuild` roundtrip 위젯 테스트

---

## 2. 수동 GUI 체크리스트 (현장 장비)

GUI 실행: `scripts\run_gui.cmd`

### 2.1 Single

| # | 단계 | 기대 결과 |
|---|------|-----------|
| S1 | iSeries IP/User/Pass 입력 → Test Connection | 성공 (녹색 상태) |
| S2 | Save → 드롭다운에 프로필 표시 | 비밀번호 파일에 없음 |
| S3 | 폼 비우기 → 프로필 선택 | 자동 채움 |
| S4 | Load 버튼 | 동일 |

### 2.2 Multiple — 목록

| # | 단계 | 기대 결과 |
|---|------|-----------|
| M1 | 장비 2대 이상 입력 → Save → 이름 `3TeamVE+NSA테스트` | «목록 저장됨: … (N대)» |
| M2 | 표 비우거나 변경 → 목록 선택 → **Load** | 표 전체 복원, **«프로필을 찾을 수 없습니다» 없음** |
| M3 | Delete | 드롭다운에서 제거 |

저장 파일 확인 (선택):

```powershell
dir "$env:LOCALAPPDATA\f5tool\lists"
type "$env:LOCALAPPDATA\f5tool\lists\3TeamVE+NSA테스트.json"
```

### 2.3 Multiple — 장비별 계정

| # | 단계 | 기대 결과 |
|---|------|-----------|
| M4 | 장비별 계정 선택 | User/Password 열 표시 |
| M5 | Password 칸 Tab 반복 | **RecursionError 없음**, 해당 장비 블록 하이라이트 |
| M6 | Test Connection (전체) | «N대 (전체 성공)» 또는 실패 장비별 메시지 |

### 2.4 Multiple — 프로필에서 추가

| # | 단계 | 기대 결과 |
|---|------|-----------|
| M7 | Single에서 장비 1개 Save (프로필) | `devices\`에 json |
| M8 | Multiple → **+ 저장된 장비에서 추가…** | 대화상자, 다중 선택 → 행만 추가 (Load 아님) |

### 2.5 Run Health Check

| # | 단계 | 기대 결과 |
|---|------|-----------|
| M9 | 사이트명 입력 → Run | Progress 후 Healthy/Unhealthy |
| M10 | Open Report Window | HTML 정상 |

---

## 3. 디버깅 가이드

### 3.1 Load 실패 («프로필/목록을 찾을 수 없습니다»)

1. **모드 확인:** Multiple인데 `devices\` id를 고르고 있지 않은지 (드롭다운은 `lists\`만 표시해야 함).
2. **파일 존재:**

   ```powershell
   $id = "3TeamVE+NSA테스트"   # 드롭다운에 보이는 이름과 동일한지
   Test-Path "$env:LOCALAPPDATA\f5tool\lists\$id.json"
   ```

3. **코드 경로:** `health_check_view.py` → `_load_saved_session` — Multiple 분기가 **`list_store.get`만** 호출하는지 확인.
4. **구버전 slug:** 예전에 저장한 목록이 `3teamve.json` 등 짧은 이름이면 드롭다운 텍스트와 stem 불일치 가능 → 목록 **다시 Save**.

### 3.2 RecursionError (Password)

- `multi_device_table.py` `_FocusSelectRowFilter` — `setCurrentCell` 호출 여부.
- 수정 후: FocusIn 시 **`_highlight_block`만**.

### 3.3 rSeries TMOS 401

- F5OS `admin` ≠ TMOS tenant 계정 — tenant User/Password 재입력.
- Test Connection 메시지에서 `[label]` 구분 확인.

### 3.4 로그·산출물

| 경로 | 내용 |
|------|------|
| `output\<job-id>\` | raw_collection.json, report.html |
| GUI 상태 라벨 | 연결 테스트 결과 (Rich text) |

### 3.5 GUI 디버그 실행

```powershell
.\.venv\Scripts\python.exe -m app.gui.main
```

브레이크포인트 후보:

- `_load_saved_session` (item_id, multiple 분기)
- `_apply_saved_device_list`
- `MultiDeviceTablePanel.snapshot()`

---

## 4. 테스트 데이터 (권장 lab)

| 장비 | 용도 | 비고 |
|------|------|------|
| iSeries `192.168.42.5` | TMOS only | admin / tenant 계정 |
| rSeries F5OS `192.168.45.245` | 플랫폼 | admin |
| rSeries TMOS `192.168.42.141` | tenant | `ncurity` 등 별도 계정 |

**저장소에 실비밀번호 넣지 말 것** — 매 Load 후 수동 입력.

---

## 5. 회귀 방지 (다음 작업 시)

1. Multiple Load 수정 시 `tests/test_health_check_session_load.py` 유지.
2. PRD [prd.md](prd.md) §5 이슈 표에 새 버그 한 줄 추가.
3. `docs/worklog.md`에 날짜·증상·수정 한 줄.

---

## 6. 현장 검증된 회귀 시나리오 (2026-05-20)

사용자 수동 테스트 — **전 단계 통과**

| # | 단계 | 검증 내용 |
|---|------|-----------|
| 1 | **Single** — iSeries IP/ID/PW 수동 입력 → Test Connection | TMOS 단일 장비 연결 |
| 2 | **Single** — rSeries 프로필 Load → ID/PW 입력 → F5OS/TMOS Test | 프로필 Load + rSeries 2스택 인증 |
| 3 | **Multiple** — 장비별 계정 → iSeries·rSeries 각 Test | 표 + per-device auth + 전체 테스트 |
| 4 | **Multiple** — Session **Save** | `lists/` 목록 전체 저장 |
| 5 | 표에서 **Remove Selected** → **Load** | 목록 복원 (Load 버그 회귀 없음) |

이후 권장 추가 테스트:

- **Run Health Check** — `common (정기점검)` 체크만 켠 상태 (기본값)
- Open Report → **「정기점검 Common 체크리스트」** 표 (pass/warn/fail/skip)
- **+ 저장된 장비에서 추가…** (Single에서 저장한 프로필을 Multiple에 병합)
- `pytest tests/test_common_eval.py -q`

---

## 7. 빠른 스모크 (약 15분, 신규 빌드 시)

1. `pytest tests/ -q`
2. GUI 재시작 → §6 표 1~5 재실행
3. 시간 있으면 Run Health Check (§2.5 M9–M10)

§6 통과 후 정기점검 체크리스트(PRD §6 P0) 구현으로 진행.
