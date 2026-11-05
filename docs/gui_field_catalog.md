# gui field catalog

version: 0.2  
parent: [gui_design.md](gui_design.md)

모든 gui 입력 필드와 백엔드 매핑. 구현 시 이 표를 기준으로 한다.

---

## 1. shared — target mode

| ui label (en) | widget | model | note |
|---------------|--------|-------|------|
| Target Mode | QRadioButton | `target_mode: single \| multiple` | job scope |

## 2. shared — device connection

| ui label | lang | widget | model field | persisted | required |
|----------|------|--------|-------------|-----------|----------|
| Platform | en | QComboBox | `platform_type` | yes | yes (tmos only ph.1) |
| 장비 라벨 | ko | QLineEdit | `DeviceTarget.label` | yes | yes |
| mgmt ip | ko | QLineEdit | `DeviceTarget.host` | yes | yes* |
| Port | en | QSpinBox | `DeviceTarget.port` | yes | default 443 |
| tls 검증 | ko | QCheckBox | `DeviceTarget.verify_tls` | yes | — |
| Lab 지문 신뢰 | ko | QCheckBox | `tls_fingerprint` | yes | no |
| 사용자 ID | ko | QLineEdit | `ConnectionProfile.username` | **yes** (profile) | yes* |
| 비밀번호 | ko | QLineEdit password | `ConnectionProfile.password` | **never** | first login* |
| Fixture Mode | en | QCheckBox | `use_fixture` | no | no |
| Test Connection | en | QPushButton | — | triggers login | — |
| Disconnect | en | QPushButton | — | clears `SessionManager[host:port]` | — |

\* fixture 시 ip/id/pw 생략 가능. 세션 있으면 pw 없이 token 사용.

### 2.1 multiple mode — device table row

| column | model |
|--------|--------|
| label | `DeviceTarget.label` |
| mgmt ip | `DeviceTarget.host` |
| port | `DeviceTarget.port` |
| status | ui only (session ok / fail) |
| actions | remove row |

공통 id/pw → 각 host 로그인 시 동일 `ConnectionProfile` (username 동일, token per host).

## 2.2 session (memory only)

| key | value |
|-----|--------|
| `host:port` | `token`, `username`, `verified_at` |

disk: **never** — see `SessionManager` in gui_design §5.4.

---

## 3. health_check wizard

| step | ui label | model / config | output |
|------|----------|----------------|--------|
| 2 | 점검 프로필 | `HealthCheckProfile.categories` | — |
| 2 | 타임아웃 | `collector_timeout` | — |
| 3 | 사이트명 | `ReportContext.site_name` | report cover |
| 3 | 점검 기간 | `ReportContext.period` | report |
| 3 | 비고 | `ReportContext.engineer_notes` | report |
| 4 | — | `job_id`, `JobStatus` | `output/<job_id>/` |

---

## 4. initial_setup wizard

| ui label | model field | artifact |
|----------|-------------|----------|
| hostname | `NetworkProfile.hostname` | tmsh, design md |
| mgmt ip | `NetworkProfile.mgmt_ip` | design md |
| netmask | `NetworkProfile.mgmt_netmask` | design md |
| gateway | `NetworkProfile.gateway` | tmsh |
| dns servers | `NetworkProfile.dns_servers` | tmsh |
| ntp servers | `NetworkProfile.ntp_servers` | tmsh |
| vlan table | `NetworkProfile.vlans[]` | tmsh, yaml |

---

## 5. vpe_macro wizard

| ui label | model field | artifact |
|----------|-------------|----------|
| 인증 방식 | `VpeMacroRequest.auth_method` | design, commands |
| 리소스 모델 | `VpeMacroRequest.resource_model` | yaml |
| 그룹 매핑 테이블 | `VpeMacroRequest.group_mappings` | yaml, commands |
| mfa | `VpeMacroRequest.mfa_methods` | commands |
| irule 필요 | `VpeMacroRequest.irule_required` | irule_template.tcl |

---

## 6. os_upgrade wizard (phase 2)

| ui label | purpose |
|----------|---------|
| 목표 버전 | `upgrade_target_version` |
| maintenance window | report metadata |
| pre profile | extends health_check |
| post profile | extends health_check |

---

## 7. settings

| ui label | key | default |
|----------|-----|---------|
| Output Folder | `output_root` | `./output` |
| Clear sessions on exit | `clear_sessions_on_exit` | true |
| Open reports externally | `use_external_browser` | false |
| Change Mode | `change_mode_enabled` | false |

---

## 7. buttons — visibility by phase

| button | phase 1 | phase 2 | phase 3 |
|--------|---------|---------|---------|
| 연결 테스트 | yes | yes | yes |
| 점검 실행 | yes | yes | yes |
| 설계 산출 | yes | yes | yes |
| 미리보기 diff | no | yes | yes |
| 장비 적용 | no | no | opt-in |

---

*end of field catalog*
