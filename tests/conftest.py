import os
import shutil
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_TEST_DIR = Path.cwd() / "instance" / "pytest"
_TEST_DIR.mkdir(parents=True, exist_ok=True)
os.environ["FLASK_ENV"] = "development"
os.environ["SESSION_TYPE"] = "cachelib"
os.environ["DATABASE_PATH"] = str(_TEST_DIR / "test.db")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
os.environ["API_KEY_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("DATABASE_URL", None)
os.environ.pop("RENDER", None)

import app as app_module  # noqa: E402  (env harus diset sebelum import)

app_module.init_db()


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
    with app_module.app.app_context():
        app_module.db.session.query(app_module.UserApiKey).delete()
        app_module.db.session.query(app_module.User).delete()
        app_module.db.session.commit()
    yield
    # Bersihkan direktori per pengguna yang dibuat selama test.
    for base in (app_module.UPLOAD_DIR, app_module.OUTPUT_DIR):
        for child in base.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
    with app_module.app.app_context():
        app_module.db.session.remove()
        app_module.db.session.query(app_module.UserApiKey).delete()
        app_module.db.session.query(app_module.User).delete()
        app_module.db.session.commit()


def register_and_login(client, username="tester", password="rahasia-123"):
    client.post(
        "/register",
        data={"username": username, "password": password, "confirm_password": password},
    )
    client.post("/login", data={"username": username, "password": password})


def set_valid_api_key(client, monkeypatch, key="sk-test-kunci-palsu-123"):
    monkeypatch.setattr(app_module, "validate_api_key", lambda api_key: None)
    return client.post("/api-key", data={"api_key": key})
