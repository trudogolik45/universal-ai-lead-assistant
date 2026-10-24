"""Credentials Postgres для n8n повторяют смысл sslmode из DATABASE_URL."""

import pytest

from scripts.n8n_credentials import SMTP_CREDENTIAL_ID, credentials, postgres_credential

URL = "postgresql://uala_app:secret@pooler.example.com:5432/postgres"


@pytest.mark.parametrize("sslmode", ["require", "prefer", "allow"])
def test_sslmode_without_verification_encrypts_but_trusts_any_certificate(sslmode):
    data = postgres_credential(f"{URL}?sslmode={sslmode}")["data"]

    assert data["allowUnauthorizedCerts"] is True


def test_url_without_sslmode_is_treated_as_require():
    data = postgres_credential(URL)["data"]

    assert data["ssl"] == "require"
    assert data["allowUnauthorizedCerts"] is True


@pytest.mark.parametrize("sslmode", ["verify-ca", "verify-full"])
def test_verifying_sslmode_checks_certificate(sslmode):
    data = postgres_credential(f"{URL}?sslmode={sslmode}")["data"]

    assert data["allowUnauthorizedCerts"] is False


def test_disabled_ssl_does_not_turn_on_tls_through_certificate_option():
    data = postgres_credential(f"{URL}?sslmode=disable")["data"]

    assert data["ssl"] == "disable"
    assert data["allowUnauthorizedCerts"] is False


def smtp_credential(env: dict) -> dict:
    return next(c for c in credentials({"DATABASE_URL": URL, **env}) if c["type"] == "smtp")


def test_smtp_credential_for_owner_reports_comes_from_env():
    smtp = smtp_credential({"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "465", "SMTP_SECURE": "true",
                            "SMTP_USER": "raporty@example.com", "SMTP_PASSWORD": "smtp-secret"})

    assert smtp["id"] == SMTP_CREDENTIAL_ID
    assert smtp["data"] == {"host": "smtp.example.com", "port": 465, "secure": True,
                            "user": "raporty@example.com", "password": "smtp-secret"}


def test_smtp_by_default_is_submission_port_with_starttls():
    smtp = smtp_credential({"SMTP_HOST": "smtp.example.com"})

    assert (smtp["data"]["port"], smtp["data"]["secure"]) == (587, False)
