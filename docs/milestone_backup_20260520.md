# milestone backup — 2026-05-20

health check gui (multiple devices, iSeries/rSeries) 완료 시점 스냅샷.

## 완료 기능

- Single / Multiple target mode
- iSeries (TMOS) / rSeries (F5OS → TMOS) — 2-row table, Model/Label span
- 공통 / 장비별 계정 (장비별 시 인증 공통 패널 숨김·초기화)
- 저장된 연결 (Session) — `%LOCALAPPDATA%\f5tool\devices\`
- Test Connection — Multiple 목록 **전체**, 메시지에 `[label]` + hostname
- Run Health Check — 목록 전체 수집, 인덱스 매칭 connections
- 요약: Healthy / Unhealthy + 건수, Open Report Window
- TLS verify off (사설 인증서), Fixture UI 제거
- Port 기본 **443** (Add Device 포함)

## 백업 아카이브

- 파일: `backups/f5field_tool_2026-05-20.zip` (소스·문서·스크립트; `.venv` / `output` 제외)

## 다음 작업

- **정기점검 리스트** — 점검 항목·체크리스트 정의 및 GUI/리포트 연동

## 복원

```powershell
Expand-Archive -Path backups\f5field_tool_2026-05-20.zip -DestinationPath .
```

(기존 파일과 충돌 시 별도 폴더에 풀기)
