# Windows 아이콘·작업 표시줄 (참고)

일반 Windows UI·쉘에서 쓰는 크기와, **작업 표시줄 전용** 문서가 항상 일치하진 않습니다. 아래는 실무에서 많이 쓰는 기준입니다.

- **가로형** 로고(심볼 왼쪽·텍스트 오른쪽)는 세로로만 잘라서는 글자가 섞입니다. 스크립트는 `w > 1.12×h`이면 **왼쪽 `NCURITY_SYMBOL_LEFT_FRAC`만** 사용합니다.
- **세로형**은 **위쪽 `NCURITY_SYMBOL_TOP_FRAC`만** 사용합니다.
- `app/resources/ncurity_symbol_only_source.png` — **BIG_Logo_OnlyBlue** 심볼 전용(글 없음). 있으면 가로/세로 비율 자르기 없이 전체 래스터로 `.ico` 생성.
- `BIG_Logo_OnlyBlue-….png` — Cursor 에셋 폴더에 있을 때 위 파일이 없으면 이 이름으로 대체 시도.

## `.ico` 멀티 해상도

하나의 `.ico` 안에 **여러 정사각 크기**를 넣어 두면, 쉘이 표시 크기에 가장 가까운 프레임을 고릅니다. 큰 원본(예: 256px)을 작은 박스에 **축소해서 쓰는 것**이, 저해상도 한 장만 넣는 것보다 선명한 경우가 많습니다.

이 프로젝트의 Ncurity 아이콘은 `512×512` 마스터에서 아래 크기별로 **각각 리샘플**해 `.ico` 레이어를 만듭니다.

`256, 128, 96, 64, 48, 40, 32, 24, 20, 16` (px)

## PyQt / 작업 표시줄

- **Windows**에서는 `QIcon`에 **단일 대형 PNG만** `addFile` 하는 것보다, **`ncurity_app_icon.ico`를 직접 로드**하는 편이 쉘·작업 표시줄에서 레이어 선택이 잘 됩니다. (`app/gui/branding.py`에서 ICO 우선)
- **24×32 계열**은 DPI·Windows 버전에 따라 다릅니다. 위처럼 **24·32·48**을 모두 넣어 두는 것이 안전합니다.

## 투명 배경

투명 PNG/ICO는 Windows 11에서 **밝은 타일** 위에 그려질 수 있습니다. 심볼이 작아 보이면 `scripts/prepare_branding_assets.py`의 `NCURITY_ICON_MARGIN_RATIO`를 줄이거나, 마스터 해상도 `NCURITY_ICON_CANVAS`를 올려 조정합니다.

## 관련 스크립트

```cmd
.venv\Scripts\python.exe scripts\prepare_branding_assets.py
```

출력: `app/resources/ncurity_app_icon.png`, `ncurity_app_icon.ico`
