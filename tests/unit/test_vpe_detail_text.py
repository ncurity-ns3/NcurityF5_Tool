"""AAA reference text and iRule code cards stay independent of the widgets."""

from app.modules.vpe_viewer.detail_text import (
    detail_document_html,
    object_section_html,
    reference_lines,
    section_card,
)


def test_http_ad_and_radius_settings_are_listed() -> None:
    http_text = "\n".join(
        reference_lines(
            {
                "key": "server",
                "name": "/Common/HTTP_FIDO_HKMC",
                "object": {
                    "name": "/Common/HTTP_FIDO_HKMC",
                    "object_kind": "aaa http",
                    "auth-type": "form-based",
                    "start-uri": "/fido/start",
                    "success-match-value": "OK",
                },
            }
        )
    )
    assert "HTTP_FIDO_HKMC  (aaa http)" in http_text
    assert "인증 방식: form-based" in http_text
    assert "시작 URI: /fido/start" in http_text
    assert "성공 값: OK" in http_text

    ad_text = "\n".join(
        reference_lines(
            {
                "key": "server",
                "name": "/Common/AD_CORP",
                "object": {
                    "object_kind": "aaa active-directory",
                    "domain": "corp.local",
                    "admin-name": "svc",
                },
            }
        )
    )
    assert "도메인: corp.local" in ad_text
    assert "관리자 이름: svc" in ad_text

    radius_text = "\n".join(
        reference_lines(
            {
                "key": "server",
                "name": "/Common/RAD",
                "object": {
                    "object_kind": "aaa radius",
                    "retries": 3,
                    "nas-ip-address": "10.1.1.1",
                },
            }
        )
    )
    assert "재시도: 3" in radius_text
    assert "NAS IP: 10.1.1.1" in radius_text


def test_http_fields_split_rows_and_inner_boxes() -> None:
    rendered = object_section_html(
        "HTTP_FIDO_HMG  (aaa http)",
        {
            "object_kind": "aaa http",
            "auth-type": "custom-post",
            "content-type": "none",
            "custom-body": '{\n  "site": "%{session.fido.site}"\n}',
            "form-action": "http://hmgfido.example/MPASS/PASS_hmg/PassFIDO_dec.jsp",
            "headers": {"header0": {"value": "application/json; charset=utf-8"}},
            "success-match-type": "string",
            "success-match-value": "1200",
        },
        skip_kind=True,
    )
    assert "인증 방식" in rendered
    assert "Content Type" in rendered
    assert "Custom Body" in rendered
    assert "폼 주소" in rendered
    assert "Headers" in rendered
    assert "header0" in rendered
    assert "application/json" in rendered
    assert "PassFIDO_dec.jsp" in rendered
    assert "Consolas" in rendered
    assert rendered.count("background-color:#FFFFFF") >= 3
    custom_at = rendered.index("Custom Body")
    form_at = rendered.index("폼 주소")
    header_at = rendered.index("Headers")
    assert custom_at < form_at < header_at


def test_reference_and_branch_cards_are_separate_boxes() -> None:
    rendered = detail_document_html(
        "HTTP Auth",
        [],
        [
            ("HTTP_FIDO_HMG  (aaa http)", ["인증 방식: custom-post", "성공 값: 1200"]),
            ("fallback", ["→ Deny", "expr { session.foo }"]),
        ],
    )
    assert rendered.count("background-color:#F4F7FB") == 2
    assert "HTTP_FIDO_HMG" in rendered
    assert "session.foo" in rendered
    assert "color:#0260EA" in section_card("분기", ["→ Allow"])


def test_irule_card_keeps_leading_spaces() -> None:
    source = "    set id [ACCESS::session data get]"
    rendered = detail_document_html("설명", [("Rule_Fido", source)])
    assert "Consolas" in rendered
    assert "&nbsp;&nbsp;&nbsp;&nbsp;set&nbsp;id" in rendered
