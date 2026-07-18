import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="revisi-artikel-test-"))
os.environ["FLASK_ENV"] = "development"
os.environ["SESSION_TYPE"] = "filesystem"
os.environ["DATABASE_PATH"] = str(_TEST_DIR / "test.db")
os.environ["SECRET_KEY"] = "test-secret-key"

import app as app_module  # noqa: E402  (env harus diset sebelum import)


@pytest.fixture()
def flask_app():
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield app_module.app


@pytest.fixture()
def client(flask_app):
    with flask_app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state():
    yield
    # Bersihkan direktori per pengguna yang dibuat selama test.
    for base in (app_module.UPLOAD_DIR, app_module.OUTPUT_DIR):
        for child in base.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
    if Path(os.environ["DATABASE_PATH"]).exists():
        with app_module.get_db() as connection:
            connection.execute("DELETE FROM users")


def register_and_login(client, username="tester", password="rahasia-123"):
    client.post(
        "/register",
        data={"username": username, "password": password, "confirm_password": password},
    )
    client.post("/login", data={"username": username, "password": password})


def set_valid_api_key(client, monkeypatch, key="sk-test-kunci-palsu-123"):
    monkeypatch.setattr(app_module, "validate_api_key", lambda api_key: None)
    return client.post("/api-key", data={"api_key": key})
