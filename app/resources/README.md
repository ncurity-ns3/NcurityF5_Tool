# Application resources

| File | Description |
|------|-------------|
| `f5_logo_source.png` | Optional F5 logo source |
| `f5_app_icon.png` / `.ico` | (선택) `--f5-only` 로만 생성 |
| `ncurity_home_source.png` | (선택) Home용 원본 PNG |
| `ncurity_logo_source.png` | (선택) 통합 로고 원본 |
| `ncurity_icon_source.png` | (선택) 사용자 지정 심볼 클립 — 있으면 **최우선** |
| `ncurity_symbol_only_source.png` | **심볼 전용 원본** (BIG_Logo_OnlyBlue, 글 없음). `ncurity_icon_source` 없을 때 사용 |
| `ncurity_home_logo.png` | **Home 화면** 배너 — 파란 로고, 흰 배경 (높이 118px) |
| `ncurity_home_logo_white.png` | **파란 헤더**용 흰 로고 (투명 배경) |
| `ncurity_app_icon.png` / `.ico` | 작업 표시줄·타이틀바 — **투명 배경**, 심볼 전체 + 안쪽 여백 |
| `checkbox_unchecked.png` | 체크박스 해제 (흰 박스 + 진한 테두리) |
| `checkbox_checked.png` | 체크박스 선택 (파란 박스 + 흰 체크) |

Generate all icons:

```cmd
.venv\Scripts\python.exe scripts\prepare_branding_assets.py
```

F5 only:

```cmd
.venv\Scripts\python.exe scripts\prepare_branding_assets.py --f5-only
```
