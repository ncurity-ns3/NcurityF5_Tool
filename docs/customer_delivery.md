# 고객 배포 — 패키징·보안·용량

Ncurity F5 Big-IP Managing Tool을 현장 PC에 전달할 때의 선택지와 트레이드오프입니다.

## 작업 표시줄 / Dock 아이콘 (Ncurity)

| OS | 동작 |
|----|------|
| **Windows** | `ncurity_app_icon.ico` + AppUserModelID (python.exe와 분리) |
| **macOS** | `ncurity_app_icon.png` + Qt 아이콘. Dock이 **Python**으로 보이면 한 번 설치: `pip install pyobjc-framework-Cocoa` 후 GUI 재실행 |
| **배포 exe/app** | PyInstaller 번들은 Ncurity 아이콘 포함 |

타이틀바·작업 표시줄 모두 **F5가 아닌 Ncurity 심볼**을 사용합니다 (Home 배너는 세로 전체 로고).

## 빌드 (내부)

### 한 번에 (ZIP + 설치 프로그램)

```cmd
scripts\build_customer_release.cmd
```

또는 PowerShell:

```powershell
cd "<프로젝트 루트>"
scripts\build_windows.ps1 -Installer
```

| 산출물 | 경로 |
|--------|------|
| **더블클릭 실행** (Python 불필요) | `dist\NcurityF5Tool\NcurityF5Tool.exe` |
| **포터블 ZIP** (고객 1순위) | `dist\release\NcurityF5Tool-<버전>-win64-portable.zip` |
| **설치 프로그램** (Inno Setup 6 필요) | `dist\installer\NcurityF5Tool-Setup-<버전>.exe` |
| **보안팀 제출용** | `dist\release\*-release-manifest.txt` (SHA256) |

설치 경로(관리자 권한 없음): `%LOCALAPPDATA%\Programs\Ncurity\F5 Big-IP Managing Tool\`  
리포트·설정 데이터: `%LOCALAPPDATA%\f5tool\` (exe와 분리)

### Setup exe만 (PyInstaller 빌드 후)

```cmd
scripts\build_installer_only.cmd
```

### exe만

```powershell
scripts\build_windows.ps1
```

결과: `dist\NcurityF5Tool\` — `NcurityF5Tool.exe` + `_internal\` (PyQt6·WebEngine 포함 시 **수백 MB**).

### macOS app (.app + ZIP + DMG)

macOS 장비에서 실행:

```bash
./scripts/build_macos.sh
```

산출물:

| 산출물 | 경로 |
|--------|------|
| **macOS app** | `dist/NcurityF5Tool.app` |
| **포터블 ZIP** | `dist/release/NcurityF5Tool-<버전>-macos-app.zip` |
| **설치 이미지** | `dist/release/NcurityF5Tool-<버전>-macos.dmg` |
| **보안팀 제출용** | `dist/release/NcurityF5Tool-<버전>-macos-release-manifest.txt` |

옵션:

```bash
# 서명 건너뜀
./scripts/build_macos.sh --skip-sign

# 서명 + 노타라이즈
export NCURITY_MAC_CODESIGN_IDENTITY="Developer ID Application: Ncurity Platform Inc. (TEAMID)"
export NCURITY_MAC_NOTARY_PROFILE="ncurity-notary"
./scripts/build_macos.sh --notarize
```

아이콘/타이틀 리소스:

```cmd
.venv\Scripts\python.exe scripts\prepare_branding_assets.py [로고.png]
```

## 왜 exe가 막히는가

| 원인 | 설명 |
|------|------|
| **미서명 바이너리** | PyInstaller one-file/one-folder exe는 AV·EDR이 휴리스틱으로 차단하는 경우가 많음 |
| **압축/자기추출** | one-file은 런타임에 임시 폴더에 풀림 → “의심스러운 동작” |
| **PyQt/WebEngine** | DLL·Chromium 규모가 커서 스캔 시간·오탐 증가 |

**완전 회피는 불가**하지만, 아래 조합으로 통과율을 올릴 수 있습니다.

## 권장 배포 형태 (우선순위)

### 1) One-folder + ZIP (현재 스크립트 기본) — **1순위**

- `dist\NcurityF5Tool` 전체를 ZIP으로 전달.
- 고객: 압축 해제 후 `NcurityF5Tool.exe` 실행 (설치 불필요).
- **one-file보다 EDR 오탐이 적은 편**.
- 용량: WebEngine 포함 시 **~250–450MB** (압축 ZIP은 보통 100–200MB대).

### 2) 코드 서명 (SignTool / EV 인증서) — **현장 통과에 가장 효과적**

- 회사명(Ncurity)으로 `NcurityF5Tool.exe`, `_internal\` 내 DLL, 설치 exe 서명.
- 빌드 시 자동 시도 (`scripts\sign_windows_release.ps1`):

```powershell
$env:NCURITY_SIGN_PFX_PATH = "C:\certs\ncurity_codesign.pfx"
$env:NCURITY_SIGN_PFX_PASSWORD = "..."   # 또는 안전한 비밀 저장소
# 또는 Windows 인증서 저장소: $env:NCURITY_SIGN_CERT_SHA1 = "<thumbprint>"

scripts\build_windows.ps1 -Installer
```

- 서명 변수가 없으면 빌드는 계속되며 manifest에 **미서명** 상태로 SHA256만 기록됨.
- 고객 보안팀에 **해시·서명자·버전·프로세스명**을 화이트리스트 요청 (`dist\release\*-release-manifest.txt`).
- 비용·갱신 절차는 있으나, “막힌다” 이슈의 정석 대응.

### 3) 고객 보안팀 사전 등록

- 배포 ZIP SHA256, exe 경로, 프로세스명 `NcurityF5Tool.exe` 고정.
- “관리 도구 / F5 점검용 / 아웃바운드 HTTPS(443)만” 등 용도 문서 1페이지 첨부.

### 4) WebEngine 제외 빌드 (용량·오탐 절감, 기능 제한)

- 리포트 HTML은 **외부 브라우저** 또는 **텍스트 미리보기**만 사용.
- `PyQt6-WebEngine` 미포함 spec → **용량·DLL 수 대폭 감소**, 인앱 HTML 미리보기 불가.
- 현장에서 “리포트만 보면 된다”면 현실적인 절충.

### 5) Python 포터블 + 소스 (exe 대신) — 보안이 매우 빡센 사이트

- 회사 제공 **검증된 Python 3.12 embed** + `pip install` 오프라인 wheel 번들.
- 실행: `python -m app.gui.main` — exe 없음 → 일부 EDR은 완화.
- 대신 고객 PC에 Python 배치·경로 관리 필요.

### 6) 사내 VD / 점프 서버에서만 실행

- 고객망이 아닌 **Ncurity 관리 VM**에서만 도구 실행 → 고객 EDR 영향 최소.

## 용량을 줄이는 실무 팁

- **one-file 사용 금지** (느리고 오탐↑).
- spec `excludes`에 numpy/pandas/matplotlib 등 미사용 대형 패키지 유지.
- WebEngine이 필수가 아니면 optional 빌드 분리.
- `templates/`, `config/`만 datas로 포함 — 테스트·docs 제외.
- 전달은 **ZIP**; USB는 exFAT/FAT32(4GB 제한) 주의.

## 전달 체크리스트

- [ ] `NcurityF5Tool.exe` 서명 (가능 시)
- [ ] ZIP SHA256 명시 (릴리스 노트)
- [ ] 버전·빌드일·연락처 (Ncurity)
- [ ] 데이터 경로: `%LOCALAPPDATA%\f5tool\` (고객 데이터 잔류 안내)
- [ ] 방화벽: 장비 MGMT HTTPS(443), SSH 22 미사용 (게이트웨이 정책 문서화)

## 관련 파일

| 파일 | 용도 |
|------|------|
| `packaging/ncurity_f5tool.spec` | PyInstaller one-folder (UPX off, asInvoker manifest) |
| `packaging/NcurityF5Tool.iss` | Inno Setup 설치 프로그램 |
| `scripts/build_customer_release.cmd` | ZIP + installer 일괄 빌드 |
| `scripts/build_windows.ps1` | PyInstaller + ZIP + 선택 `-Installer` |
| `scripts/build_macos.sh` | macOS `.app` + ZIP + 선택 notarize |
| `scripts/sign_windows_release.ps1` | Authenticode 서명 |
| `packaging/macos_entitlements.plist` | macOS codesign entitlements |
| `scripts/generate_version_info.py` | exe FileVersion 리소스 |
| `app/runtime/paths.py` | 배포 exe 시 `%LOCALAPPDATA%\f5tool` 출력 경로 |
| `scripts/prepare_branding_assets.py` | 로고 → `.ico` / `.png` |
| `app/gui/branding.py` | 창 제목·아이콘 |
