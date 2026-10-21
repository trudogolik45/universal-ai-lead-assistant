"""Service account Google для тестов: ключ стенда, проверка JWT, токен и чтение реальной таблицы."""

import base64
import json
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TOKEN_PATH = "/token"
JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


@dataclass
class ServiceAccount:
    email: str
    private_key_pem: str

    @classmethod
    def generate(cls, email: str = "stand@uala-test.iam.gserviceaccount.com") -> "ServiceAccount":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        return cls(email, pem)

    def env(self) -> dict[str, str]:
        """Переменные n8n. Ключ с `\\n` вместо переводов строк, как в .env."""
        return {
            "GOOGLE_SERVICE_ACCOUNT_EMAIL": self.email,
            "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY": self.private_key_pem.replace("\n", "\\n"),
        }

    def _private_key(self):
        return serialization.load_pem_private_key(self.private_key_pem.encode(), password=None)

    def sign(self, claims: dict) -> str:
        unsigned = f"{_b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}))}.{_b64(json.dumps(claims))}"
        signature = self._private_key().sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{unsigned}.{_b64(signature)}"

    def verify(self, jwt: str) -> dict:
        """Claims подписанного этим ключом JWT. Чужая подпись — исключение."""
        header, payload, signature = jwt.split(".")
        self._private_key().public_key().verify(
            _unb64(signature), f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        return json.loads(_unb64(payload))

    def access_token(self, token_url: str) -> str:
        now = int(time.time())
        claims = {"iss": self.email, "scope": SCOPE, "aud": token_url, "iat": now, "exp": now + 3600}
        response = httpx.post(token_url, data={"grant_type": JWT_GRANT, "assertion": self.sign(claims)})
        response.raise_for_status()
        return response.json()["access_token"]


def read_values(base_url: str, token: str, spreadsheet_id: str, sheet: str) -> list[list[str]]:
    sheet_range = quote(f"'{sheet}'!A:J", safe="")
    response = httpx.get(
        f"{base_url}/v4/spreadsheets/{spreadsheet_id}/values/{sheet_range}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json().get("values", [])


def _b64(data: str | bytes) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
