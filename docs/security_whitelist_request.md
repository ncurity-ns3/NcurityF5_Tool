# 보안팀 화이트리스트 요청 (Ncurity F5 Tool)

고객 EDR/백신에 등록 요청 시 아래를 첨부하세요. 빌드 후 `dist\release\*-release-manifest.txt` 의 SHA256을 최신 값으로 교체합니다.

## 제품 정보

| 항목 | 값 |
|------|-----|
| 제품명 | Ncurity F5 Big-IP Managing Tool |
| 용도 | F5 BIG-IP 현장 점검·OS 업그레이드 전후 Check List |
| 프로세스 | `NcurityF5Tool.exe` |
| 발행사 (서명 시) | Ncurity |

## 배포 파일

1. **포터블**: `NcurityF5Tool-<버전>-win64-portable.zip` — 압축 해제 후 `NcurityF5Tool.exe` 실행  
2. **설치형**: `NcurityF5Tool-Setup-<버전>.exe` — 사용자 설치 (`%LOCALAPPDATA%\Programs\Ncurity\...`)

## 네트워크

- 아웃바운드: F5 장비 MGMT **HTTPS 443** (REST API, 리포트 수집)
- **TCP 22 (SSH) 미사용** — 고객 게이트웨이 정책과 동일

## 로컬 데이터

- `%LOCALAPPDATA%\f5tool\` — 장비 목록, 리포트 출력 (고객 데이터 잔류 가능)

## 오탐 완화 (권장)

- [ ] Ncurity **코드 서명** (exe + 설치 프로그램)  
- [ ] manifest SHA256 화이트리스트  
- [ ] one-file exe **사용 안 함** (본 제품은 one-folder만 제공)

## 서명 없이 배포 시

미서명 PyInstaller 바이너리는 휴리스틱 차단 가능성이 있습니다. 통과율을 높이려면 반드시 **회사 Authenticode 서명** 후 재빌드하세요 (`docs/customer_delivery.md`).
