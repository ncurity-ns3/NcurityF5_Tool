# f5 field automation

offline windows automation platform for f5 field engineers (phase 1 poc).

## version

현재 버전은 **1.3.1** 입니다. 출처는 `pyproject.toml`의 `version`이며, 창 제목과 설치 파일 이름에 같은 값이 들어갑니다.

번호는 `1.2.3` 형식입니다.

| 자리 | 언제 올리나 |
|------|-------------|
| 1 (Major) | UI 전체가 바뀌는 수준의 큰 변경 |
| 2 (Minor) | 기능 추가나 그에 준하는 변경 |
| 3 (Patch) | 버그 수정, 작은 개선, 로직 수정 |

| 버전 | 의미 | 설치 파일 |
|------|------|-----------|
| 1.0.0 | 정기 점검, OS 업그레이드 전 사전 점검. 당시 빌드 파일 버전은 0.1.0 | `dist\installer\NcurityF5Tool-Setup-1.0.0.exe` |
| 1.1.0 | APM Macro Save / Load | `dist\installer\NcurityF5Tool-Setup-1.1.0.exe` |
| 1.2.0 | VPE Viewer, 납품확인서 작성, 메뉴 정리 | GitHub Releases `NcurityF5Tool-1.2.0.msi` |
| 1.3.0 | WAF, OWASP Top 10 PoC (2021 목록) | GitHub Releases `NcurityF5Tool-1.3.0.msi` |
| 1.3.1 | OWASP 2017·2021 전체 목록, VPE 매크로 접기 | GitHub Releases `NcurityF5Tool-1.3.1.msi` |

자세한 변경 내용은 [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)에 있습니다.

## project root

```
C:\Users\ejes3\Ejes_OneDrive\OneDrive - Ncurity\바탕 화면\WorksFiles\F5 Project\Config & Rules & Apps\AI First
```

## gui preview — 화면 보기

```cmd
cd /d "C:\Users\ejes3\Ejes_OneDrive\OneDrive - Ncurity\바탕 화면\WorksFiles\F5 Project\Config & Rules & Apps\AI First"
scripts\setup_dev.cmd
.venv\Scripts\python.exe -m pip install PyQt6 PyQt6-WebEngine
scripts\run_gui.cmd
```

경로에 `&` 가 있으면 (Config & Rules …): `powershell -File scripts\run_gui.ps1`

1. 왼쪽 **Health Check** 클릭  
2. **Fixture Mode** 체크 → **Run Health Check**  
3. 아래 **Report Preview** 에 html 표시  

## quick start (cmd)

```cmd
scripts\setup_dev.cmd
scripts\run_tests.cmd
```

python 설치 문제: [docs/windows_setup.md](docs/windows_setup.md)

## customer build (windows)

Python 없이 실행: `dist\NcurityF5Tool\NcurityF5Tool.exe` 더블클릭.

```cmd
scripts\build_customer_release.cmd
```

- ZIP: `dist\release\NcurityF5Tool-<ver>-win64-portable.zip`
- 설치: `dist\installer\NcurityF5Tool-Setup-<ver>.exe` (Inno Setup 6)
- [docs/customer_delivery.md](docs/customer_delivery.md) — EDR·코드 서명·보안팀 SHA256
- [docs/windows_icons.md](docs/windows_icons.md) — Windows `.ico` 멀티 해상도·작업 표시줄 참고

## docs

- [docs/spec.md](docs/spec.md) — product spec
- [docs/gui_design.md](docs/gui_design.md) — **gui / ux (mgmt ip, id/pw부터)**
- [docs/ui_flows.md](docs/ui_flows.md) — screen flows
- [docs/gui_field_catalog.md](docs/gui_field_catalog.md) — field ↔ backend mapping
- [docs/roadmap.md](docs/roadmap.md)
- [docs/security_rules.md](docs/security_rules.md)
- [docs/test_plan.md](docs/test_plan.md)
- [docs/windows_setup.md](docs/windows_setup.md)
- [docs/worklog.md](docs/worklog.md)
