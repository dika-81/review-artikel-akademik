"""Lapisan runtime versi web: pengganti OpenAI SDK, httpx, dan thread.

Kode analysis yang diambil dari app.py memanggil `call_openai_chat`,
`httpx.get`, dan `ThreadPoolExecutor` seperti biasa. Di browser, permintaan
HTTP dijalankan oleh fungsi transport yang dipasang worker JavaScript
(XMLHttpRequest sinkron di dalam Web Worker). Di test CPython, transport
diganti tiruan.

Transport: fn(method, url, headers: dict, body: str | None, timeout: float)
-> (status: int, text: str). Status 0 berarti gagal jaringan; teks "timeout"
menandai batas waktu terlampaui.
"""

import json
import os
from urllib.parse import urlencode

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
DEFAULT_MODEL = "gpt-6-astra"

_transport = None
_settings = {
    "api_key": "",
    "model": DEFAULT_MODEL,
    "max_output_tokens": 16000,
    "timeout_seconds": 300,
}


def set_transport(fn):
    global _transport
    _transport = fn


def configure(api_key=None, model=None, max_output_tokens=None, timeout_seconds=None,
              scholarly_email=None):
    if api_key is not None:
        _settings["api_key"] = str(api_key).strip()
    if model:
        _settings["model"] = str(model).strip()
    if max_output_tokens:
        _settings["max_output_tokens"] = int(max_output_tokens)
    if timeout_seconds:
        _settings["timeout_seconds"] = int(timeout_seconds)
    if scholarly_email is not None:
        os.environ["SCHOLARLY_API_EMAIL"] = str(scholarly_email).strip()


def get_model_name():
    return _settings["model"]


def get_max_output_tokens():
    return _settings["max_output_tokens"]


def request(method, url, headers=None, body=None, timeout=30):
    if _transport is None:
        raise RuntimeError("Transport HTTP belum dipasang.")
    status, text = _transport(method, url, dict(headers or {}), body, float(timeout))
    return int(status), str(text or "")


# ---------------------------------------------------------------------------
# Pengganti httpx (hanya bagian yang dipakai app.py)
# ---------------------------------------------------------------------------

class HTTPStatusError(RuntimeError):
    pass


class _Response:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code == 0:
            raise HTTPStatusError(
                "batas waktu terlampaui" if self.text == "timeout" else "koneksi gagal"
            )
        if self.status_code >= 400:
            raise HTTPStatusError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


class _HttpxShim:
    @staticmethod
    def get(url, params=None, headers=None, timeout=30):
        if params:
            url = f"{url}?{urlencode(params)}"
        # Browser melarang header User-Agent kustom; identitas dikirim via mailto.
        headers = {k: v for k, v in (headers or {}).items() if k.lower() != "user-agent"}
        status, text = request("GET", url, headers=headers, timeout=timeout)
        return _Response(status, text)


httpx = _HttpxShim()


# ---------------------------------------------------------------------------
# Pengganti ThreadPoolExecutor: Pyodide tidak mendukung thread, jadi
# pekerjaan dijalankan berurutan dengan antarmuka yang sama.
# ---------------------------------------------------------------------------

class _Future:
    def __init__(self, fn, args, kwargs):
        self._result = None
        self._error = None
        try:
            self._result = fn(*args, **kwargs)
        except Exception as exc:  # disimpan, dilempar ulang saat result()
            self._error = exc

    def result(self):
        if self._error is not None:
            raise self._error
        return self._result


class ThreadPoolExecutor:
    def __init__(self, max_workers=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def submit(self, fn, *args, **kwargs):
        return _Future(fn, args, kwargs)


def as_completed(futures):
    return list(futures)


# ---------------------------------------------------------------------------
# OpenAI Responses API
# ---------------------------------------------------------------------------

def _error_body(text):
    try:
        return (json.loads(text) or {}).get("error") or {}
    except (ValueError, AttributeError):
        return {}


def translate_http_error(status, text):
    """Pesan aman berbahasa Indonesia; isi respons mentah tidak pernah ditampilkan."""
    error = _error_body(text)
    code = str(error.get("code") or "")
    if status == 0:
        if text == "timeout":
            return "Permintaan ke OpenAI melebihi batas waktu. Silakan coba kembali."
        return "Koneksi ke OpenAI gagal. Periksa koneksi internet Anda, lalu coba kembali."
    if status == 401:
        return "API key OpenAI tidak valid atau sudah dicabut. Periksa kembali API key Anda."
    if status == 429:
        if code == "insufficient_quota" or error.get("type") == "insufficient_quota":
            return (
                "Kuota atau saldo OpenAI API Anda tidak mencukupi. Silakan periksa halaman "
                "billing dan batas penggunaan akun OpenAI Anda, lalu coba kembali."
            )
        return "Batas laju (rate limit) OpenAI tercapai. Tunggu sebentar, lalu coba kembali."
    if status in (403, 404):
        return (
            f"Model '{get_model_name()}' tidak tersedia atau tidak diizinkan untuk API key Anda. "
            "Ganti model di halaman Pengaturan atau gunakan API key dengan akses model tersebut."
        )
    if status == 400:
        if code == "context_length_exceeded":
            return "Artikel terlalu panjang untuk dianalisis dalam satu permintaan."
        return "Permintaan ke OpenAI ditolak. Periksa kembali isi artikel Anda."
    return "Terjadi kesalahan pada layanan OpenAI. Silakan coba kembali."


def _auth_headers():
    return {"Authorization": f"Bearer {_settings['api_key']}"}


def _post_responses(payload):
    return request(
        "POST",
        OPENAI_RESPONSES_URL,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        body=json.dumps(payload, ensure_ascii=False),
        timeout=_settings["timeout_seconds"],
    )


def diagnose_failure():
    """Cari tahu penyebab permintaan yang gagal tanpa keterangan.

    Respons error dari /v1/responses tidak membawa header CORS, sehingga di
    browser hanya terlihat sebagai "koneksi gagal" (status 0). Endpoint
    /v1/models membawa header CORS dan tidak memakai token, jadi dipakai untuk
    memeriksa API key dan akses model.
    """
    status, text = request(
        "GET",
        f"{OPENAI_MODELS_URL}/{get_model_name()}",
        headers=_auth_headers(),
        timeout=20,
    )
    if status in (401, 403, 404, 429):
        return translate_http_error(status, text)
    if status == 200:
        return (
            "Permintaan ke OpenAI ditolak tanpa keterangan. API key dan model valid, jadi "
            "kemungkinan penyebabnya saldo/kuota habis, batas laju tercapai, atau artikel "
            "terlalu panjang. Periksa halaman billing OpenAI Anda, lalu coba kembali."
        )
    return translate_http_error(0, "network")


def _output_text(data):
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    return "".join(parts)


def call_openai_chat(system_prompt, user_prompt, force_json=False):
    if not _settings["api_key"]:
        raise RuntimeError(
            "OpenAI API key belum diisi. Silakan isi API key di halaman Pengaturan."
        )
    payload = {
        "model": get_model_name(),
        "instructions": system_prompt,
        "input": user_prompt,
        "max_output_tokens": get_max_output_tokens(),
    }
    if force_json:
        payload["text"] = {"format": {"type": "json_object"}}

    status, text = _post_responses(payload)
    # Di browser, error 400 tidak terbaca (status 0), jadi keduanya diperlakukan
    # sama: model/akun mungkin tidak mendukung format JSON, ulangi tanpa format.
    if force_json and (status == 400 or (status == 0 and text != "timeout")):
        payload.pop("text", None)
        status, text = _post_responses(payload)
    if status == 0 and text != "timeout":
        raise RuntimeError(diagnose_failure())
    if status != 200:
        raise RuntimeError(translate_http_error(status, text))

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RuntimeError("OpenAI API mengembalikan respons yang tidak dapat dibaca.") from exc

    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason", "")
        if reason == "max_output_tokens":
            raise RuntimeError(
                "Keluaran model terpotong karena melebihi batas token keluaran. "
                "Naikkan batas token keluaran di halaman Pengaturan atau analisis bagian "
                "yang lebih pendek. Hasil terpotong tidak ditampilkan agar tidak menyesatkan."
            )
        raise RuntimeError("Keluaran model tidak selesai (incomplete). Silakan ulangi analisis.")

    content = _output_text(data)
    if not content:
        raise RuntimeError("OpenAI API mengembalikan respons kosong. Silakan ulangi analisis.")
    return content


def test_openai_connection():
    return call_openai_chat("Jawab secara singkat dan jelas dalam bahasa Indonesia.", "Halo")


def safe_error_message(exc):
    if isinstance(exc, RuntimeError):
        return str(exc)
    return "Terjadi kesalahan internal aplikasi. Silakan coba kembali."
