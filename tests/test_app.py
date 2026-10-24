"""測試。Java 對照：JUnit + MockMvc。

pytest 會自動找 test_*.py 內以 test_ 開頭的函式，不需要註解標記。
"""
import base64
import hashlib
import hmac
import os

# 必須在 import app 之前設定，因為 app.main 載入時就會讀取設定
os.environ["LINE_CHANNEL_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.handlers import handle_text  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def sign(body: str) -> str:
    """依 LINE 規則計算簽章：HMAC-SHA256(channel secret, body) 再 Base64。"""
    digest = hmac.new(b"test-secret", body.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_callback_rejects_invalid_signature():
    response = client.post(
        "/callback", content='{"events": []}', headers={"X-Line-Signature": "bad"}
    )
    assert response.status_code == 400


def test_callback_accepts_valid_signature():
    body = '{"destination": "U0", "events": []}'
    response = client.post(
        "/callback", content=body, headers={"X-Line-Signature": sign(body)}
    )
    assert response.status_code == 200


def test_handle_text():
    assert handle_text("/名單") is not None
    assert handle_text("大家好") is None
    assert handle_text("/不存在的指令") is None
