import io
import json

import httpx
import openai
import pytest
from docx import Document
from flask import session

import app as app_module
from conftest import register_and_login, set_valid_api_key

FAKE_KEY = "sk-test-kunci-palsu-123"


def make_docx_bytes():
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph("Judul Artikel Uji Coba Media Pembelajaran")
    document.add_paragraph("Abstract")
    document.add_paragraph("Ini adalah abstrak penelitian uji coba.")
    document.add_paragraph("Introduction")
    document.add_paragraph("Ini pendahuluan.")
    document.save(buffer)
    buffer.seek(0)
    return buffer


def make_openai_error(cls, status, body):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status, request=request, json=body)
    return cls("boom", response=response, body=body.get("error"))


# 1. Belum login tidak dapat membuka halaman analisis.
def test_index_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_analyze_requires_login(client):
    response = client.post("/analyze", data={})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# 2. Login tanpa API key diarahkan ke halaman API key.
def test_login_without_api_key_redirects_to_api_key_page(client):
    register_and_login(client)
    response = client.get("/")
    assert response.status_code == 302
    assert "/api-key" in response.headers["Location"]


# 3. API key invalid ditolak.
def test_invalid_api_key_rejected(client, monkeypatch):
    register_and_login(client)
    monkeypatch.setattr(
        app_module,
        "validate_api_key",
        lambda api_key: "API key OpenAI tidak valid atau sudah dicabut. Periksa kembali API key Anda.",
    )
    response = client.post("/api-key", data={"api_key": "sk-salah"})
    assert "tidak valid".encode() in response.data
    assert session.get(app_module.API_KEY_SESSION_FIELD) is None


# 4 & 5. API key valid hanya di server-side session, tidak muncul di HTML/cookie.
def test_valid_api_key_stored_server_side_only(client, monkeypatch):
    register_and_login(client)
    response = set_valid_api_key(client, monkeypatch, FAKE_KEY)
    assert response.status_code == 302
    assert session.get(app_module.API_KEY_SESSION_FIELD) == FAKE_KEY

    follow = client.get("/")
    assert FAKE_KEY.encode() not in follow.data
    for cookie in client._cookies.values():  # cookie hanya berisi session id
        assert FAKE_KEY not in cookie.value
    api_page = client.get("/api-key")
    assert FAKE_KEY.encode() not in api_page.data


# 6. Analisis memakai API key pengguna yang sedang aktif.
def test_analysis_uses_user_api_key(client, monkeypatch):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            class R:
                output_text = "Halo dari model"

            return R()

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    def fake_build_user_client(api_key):
        captured["api_key"] = api_key
        return FakeClient()

    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    monkeypatch.setattr(app_module, "build_user_client", fake_build_user_client)

    response = client.post("/test-ai", follow_redirects=True)
    assert response.status_code == 200
    assert captured["api_key"] == FAKE_KEY


# 7. Dua pengguna tidak berbagi session, key, maupun hasil.
def test_two_users_are_isolated(flask_app, monkeypatch):
    client_a = flask_app.test_client()
    client_b = flask_app.test_client()

    register_and_login(client_a, username="usera")
    register_and_login(client_b, username="userb")
    set_valid_api_key(client_a, monkeypatch, "sk-milik-a")
    set_valid_api_key(client_b, monkeypatch, "sk-milik-b")

    with client_a:
        client_a.get("/")
        assert session.get(app_module.API_KEY_SESSION_FIELD) == "sk-milik-a"
    with client_b:
        client_b.get("/")
        assert session.get(app_module.API_KEY_SESSION_FIELD) == "sk-milik-b"

    # User A mengunggah artikel; user B tidak dapat memakai hasilnya.
    upload = client_a.post(
        "/analyze",
        data={"article": (make_docx_bytes(), "artikel.docx")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    output_name = next(
        path.name
        for path in app_module.OUTPUT_DIR.glob("*/artikel-*.json")
    )
    response = client_b.post(
        "/analyze-title",
        data={"filename": "artikel.docx", "output_name": output_name},
        follow_redirects=True,
    )
    assert "tidak ditemukan".encode() in response.data


# 8 & 9. Logout menghapus API key; login kembali meminta API key lagi.
def test_logout_clears_api_key_and_relogin_requires_key(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)

    response = client.post("/logout")
    assert "/login" in response.headers["Location"]
    with client.session_transaction() as flask_session:
        assert app_module.API_KEY_SESSION_FIELD not in flask_session
        assert "_user_id" not in flask_session

    # Setelah logout, halaman analisis tidak dapat diakses lagi (tombol Back).
    assert "/login" in client.get("/").headers["Location"]

    client.post("/login", data={"username": "tester", "password": "rahasia-123"})
    response = client.get("/")
    assert "/api-key" in response.headers["Location"]


# 10. Session tanpa API key (misalnya kedaluwarsa) diminta mengisi ulang.
def test_missing_key_mid_session_redirects(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    with client.session_transaction() as flask_session:
        flask_session.pop(app_module.API_KEY_SESSION_FIELD)
    response = client.get("/")
    assert "/api-key" in response.headers["Location"]


# 11. Terjemahan error OpenAI.
def test_translate_insufficient_quota():
    exc = make_openai_error(
        openai.RateLimitError,
        429,
        {"error": {"message": "quota", "type": "insufficient_quota", "code": "insufficient_quota"}},
    )
    message = app_module.translate_openai_error(exc)
    assert "Kuota atau saldo OpenAI API Anda tidak mencukupi" in message


def test_translate_rate_limit_not_quota():
    exc = make_openai_error(
        openai.RateLimitError,
        429,
        {"error": {"message": "slow down", "type": "rate_limit_error", "code": "rate_limit_exceeded"}},
    )
    message = app_module.translate_openai_error(exc)
    assert "rate limit" in message.lower()
    assert "saldo" not in message.lower()


def test_translate_invalid_key():
    exc = make_openai_error(
        openai.AuthenticationError,
        401,
        {"error": {"message": "bad key", "type": "invalid_request_error", "code": "invalid_api_key"}},
    )
    assert "tidak valid" in app_module.translate_openai_error(exc)


def test_translate_model_not_found():
    exc = make_openai_error(
        openai.NotFoundError,
        404,
        {"error": {"message": "no model", "type": "invalid_request_error", "code": "model_not_found"}},
    )
    assert "tidak tersedia" in app_module.translate_openai_error(exc)


def test_translate_timeout_and_connection():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    timeout_exc = openai.APITimeoutError(request=request)
    assert "batas waktu" in app_module.translate_openai_error(timeout_exc)
    connection_exc = openai.APIConnectionError(message="down", request=request)
    assert "Koneksi ke OpenAI gagal" in app_module.translate_openai_error(connection_exc)


def test_safe_error_message_hides_internal_details():
    assert "internal" in app_module.safe_error_message(ValueError("secret traceback info"))
    assert "secret" not in app_module.safe_error_message(ValueError("secret traceback info"))


# 12. File sementara dihapus setelah hasil reviu dihapus.
def test_delete_review_removes_files(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    client.post(
        "/analyze",
        data={"article": (make_docx_bytes(), "artikel.docx")},
        content_type="multipart/form-data",
    )
    output_path = next(app_module.OUTPUT_DIR.glob("*/artikel-*.json"))
    upload_path = next(app_module.UPLOAD_DIR.glob("*/artikel.docx"))

    client.post(f"/delete-review/{output_path.name}")
    assert not output_path.exists()
    assert not upload_path.exists()


# 13. Fitur lama: upload artikel valid tetap bekerja dan format salah ditolak.
def test_upload_docx_still_works(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    response = client.post(
        "/analyze",
        data={"article": (make_docx_bytes(), "artikel.docx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "Artikel berhasil diunggah".encode() in response.data


def test_upload_wrong_extension_rejected(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    response = client.post(
        "/analyze",
        data={"article": (io.BytesIO(b"bukan docx"), "artikel.exe")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "Format file harus .docx".encode() in response.data


def test_upload_corrupt_docx_rejected(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    response = client.post(
        "/analyze",
        data={"article": (io.BytesIO(b"PK\x03\x04 rusak"), "artikel.docx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "tidak dapat dibaca".encode() in response.data


# CSRF aktif menolak POST tanpa token.
def test_csrf_protects_post(flask_app):
    flask_app.config.update(WTF_CSRF_ENABLED=True)
    try:
        raw_client = flask_app.test_client()
        response = raw_client.post(
            "/login", data={"username": "x", "password": "y"}
        )
        assert response.status_code == 400
    finally:
        flask_app.config.update(WTF_CSRF_ENABLED=False)


# Health check tidak membocorkan informasi.
def test_healthz_public_and_minimal(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "ok"}


# Halaman sensitif memakai no-store.
def test_no_store_headers(client):
    register_and_login(client)
    response = client.get("/api-key")
    assert "no-store" in response.headers.get("Cache-Control", "")
