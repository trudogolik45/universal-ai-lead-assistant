"""Credentials Postgres для n8n повторяют смысл sslmode из DATABASE_URL."""

import pytest

from scripts.n8n_credentials import postgres_credential

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
