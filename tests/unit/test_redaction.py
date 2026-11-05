from app.core.redaction import redact_data


def test_redact_data_masks_password() -> None:
    cleaned = redact_data({"username": "admin", "password": "secret"})
    assert cleaned["password"] == "[REDACTED]"
