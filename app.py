import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import re

import openai
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_user,
    logout_user,
)
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
import httpx
from openai import OpenAI
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from xml.sax.saxutils import escape
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from analysis_schema import (
    ANALYSIS_MODES,
    DEFAULT_ANALYSIS_MODE,
    ModelJSONError,
    apply_mode_limits,
    normalize_finding,
    normalize_section_result,
    parse_model_json,
    resolve_analysis_mode,
    sort_findings,
)
from article_profile import (
    APPROACH_SIGNALS,
    ARTICLE_TYPE_CHOICES,
    ARTICLE_TYPE_LABELS,
    article_type_label,
    detect_article_profile,
    effective_article_type,
    filter_false_positive_findings,
)
from article_structure import (
    extract_article_structure,
    format_section_for_prompt,
    format_section_tail_for_prompt,
    get_section,
    locate_quote,
    validate_findings_quotes,
)
from citations import run_citation_check
import prompts as prompt_builders
from prompts import SYSTEM_ANALYST


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
INSTANCE_DIR = BASE_DIR / "instance"
ALLOWED_EXTENSIONS = {".docx"}
API_KEY_SESSION_FIELD = "openai_api_key"

load_dotenv()

IS_PRODUCTION = os.getenv("FLASK_ENV", "production").lower() != "development"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or os.getenv(
    "FLASK_SECRET_KEY", "dev-secret-change-me"
)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# Session server-side: API key pengguna tidak pernah berada di cookie browser,
# cookie hanya berisi ID session yang ditandatangani.
app.config["SESSION_TYPE"] = os.getenv("SESSION_TYPE", "filesystem")
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    minutes=int(os.getenv("SESSION_LIFETIME_MINUTES", "120"))
)
app.config["SESSION_FILE_DIR"] = str(BASE_DIR / "flask_session")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SECURE"] = IS_PRODUCTION

if app.config["SESSION_TYPE"] == "redis":
    import redis

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("SESSION_TYPE=redis membutuhkan environment variable REDIS_URL.")
    app.config["SESSION_REDIS"] = redis.from_url(redis_url)

Session(app)
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Silakan login terlebih dahulu."

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
INSTANCE_DIR.mkdir(exist_ok=True)

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", INSTANCE_DIR / "app.db"))


# ---------------------------------------------------------------------------
# Akun pengguna
# ---------------------------------------------------------------------------

def get_db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


init_db()


class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = str(user_id)
        self.username = username


def find_user_row(username):
    with get_db() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


@login_manager.user_loader
def load_user(user_id):
    with get_db() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return None
    return User(row["id"], row["username"])


# ---------------------------------------------------------------------------
# Penyimpanan per pengguna
# ---------------------------------------------------------------------------

def user_upload_dir():
    path = UPLOAD_DIR / secure_filename(str(current_user.id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_output_dir():
    path = OUTPUT_DIR / secure_filename(str(current_user.id))
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# API key pengguna di server-side session
# ---------------------------------------------------------------------------

def get_session_api_key():
    return session.get(API_KEY_SESSION_FIELD)


def clear_session_api_key():
    session.pop(API_KEY_SESSION_FIELD, None)


def get_model_name():
    return os.getenv("OPENAI_MODEL", "gpt-5.6")


def get_max_output_tokens():
    return int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "16000"))


def build_user_client(api_key):
    return OpenAI(api_key=api_key, timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "300")))


def translate_openai_error(exc):
    """Terjemahkan exception OpenAI menjadi pesan aman berbahasa Indonesia.

    Tidak pernah menyertakan isi response mentah agar tidak membocorkan
    informasi sensitif (termasuk potongan API key).
    """
    if isinstance(exc, openai.AuthenticationError):
        return "API key OpenAI tidak valid atau sudah dicabut. Periksa kembali API key Anda."
    if isinstance(exc, openai.RateLimitError):
        code = getattr(exc, "code", "") or ""
        body = getattr(exc, "body", None) or {}
        if code == "insufficient_quota" or (
            isinstance(body, dict)
            and (body.get("error") or {}).get("type") == "insufficient_quota"
        ):
            return (
                "Kuota atau saldo OpenAI API Anda tidak mencukupi. Silakan periksa halaman "
                "billing dan batas penggunaan akun OpenAI Anda, lalu coba kembali."
            )
        return "Batas laju (rate limit) OpenAI tercapai. Tunggu sebentar, lalu coba kembali."
    if isinstance(exc, (openai.NotFoundError, openai.PermissionDeniedError)):
        return (
            f"Model '{get_model_name()}' tidak tersedia atau tidak diizinkan untuk API key Anda. "
            "Hubungi administrator atau gunakan API key dengan akses model tersebut."
        )
    if isinstance(exc, openai.APITimeoutError):
        return "Permintaan ke OpenAI melebihi batas waktu. Silakan coba kembali."
    if isinstance(exc, openai.APIConnectionError):
        return "Koneksi ke OpenAI gagal. Periksa koneksi internet server, lalu coba kembali."
    if isinstance(exc, openai.BadRequestError):
        code = getattr(exc, "code", "") or ""
        if code == "context_length_exceeded":
            return "Artikel terlalu panjang untuk dianalisis dalam satu permintaan."
        return "Permintaan ke OpenAI ditolak. Periksa kembali isi artikel Anda."
    if isinstance(exc, openai.OpenAIError):
        return "Terjadi kesalahan pada layanan OpenAI. Silakan coba kembali."
    return None


def safe_error_message(exc):
    translated = translate_openai_error(exc)
    if translated:
        return translated
    if isinstance(exc, RuntimeError):
        return str(exc)
    return "Terjadi kesalahan internal aplikasi. Silakan coba kembali."


def validate_api_key(api_key):
    """Validasi ringan: ambil metadata model via API. Tidak mengonsumsi token.

    Mengembalikan None bila valid, atau pesan error berbahasa Indonesia.
    """
    client = OpenAI(api_key=api_key, timeout=20)
    try:
        client.models.retrieve(get_model_name())
    except (openai.NotFoundError, openai.PermissionDeniedError):
        # Key valid tetapi model default tidak terlihat; pastikan key bisa
        # mengakses daftar model sebelum menerima key tersebut.
        try:
            client.models.list()
        except openai.OpenAIError as exc:
            return translate_openai_error(exc) or "API key tidak dapat divalidasi."
    except openai.OpenAIError as exc:
        return translate_openai_error(exc) or "API key tidak dapat divalidasi."
    return None


# ---------------------------------------------------------------------------
# Guard akses terpusat
# ---------------------------------------------------------------------------

PUBLIC_ENDPOINTS = {"login", "register", "healthz", "static"}
NO_API_KEY_REQUIRED_ENDPOINTS = PUBLIC_ENDPOINTS | {"api_key_page", "delete_api_key", "logout"}


@app.before_request
def enforce_access_rules():
    endpoint = request.endpoint
    if endpoint is None or endpoint in PUBLIC_ENDPOINTS:
        return None
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if endpoint in NO_API_KEY_REQUIRED_ENDPOINTS:
        return None
    if not get_session_api_key():
        flash("Masukkan OpenAI API key Anda terlebih dahulu untuk sesi ini.")
        return redirect(url_for("api_key_page"))
    return None


@app.after_request
def add_no_store_headers(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Alur analisis
# ---------------------------------------------------------------------------

WORKFLOW_STEPS = [
    {"number": 1, "key": "profil_artikel", "endpoint": "analyze_profile", "label": "Profil Artikel"},
    {"number": 2, "key": "judul", "endpoint": "analyze_title", "label": "Judul"},
    {"number": 3, "key": "abstrak", "endpoint": "analyze_abstract", "label": "Abstrak"},
    {"number": 4, "key": "pendahuluan", "endpoint": "analyze_introduction", "label": "Pendahuluan"},
    {"number": 5, "key": "metodologi", "endpoint": "analyze_methodology", "label": "Metodologi"},
    {
        "number": 6,
        "key": "hasil_pembahasan",
        "endpoint": "analyze_results_discussion",
        "label": "Hasil dan Pembahasan",
    },
    {"number": 7, "key": "kesimpulan", "endpoint": "analyze_conclusion", "label": "Kesimpulan"},
    {
        "number": 8,
        "key": "konsistensi",
        "endpoint": "analyze_cross_section",
        "label": "Konsistensi Lintas Bagian",
    },
    {
        "number": 9,
        "key": "sitasi_apa",
        "endpoint": "analyze_reference_citation",
        "label": "Sitasi dan APA 7",
    },
    {
        "number": 10,
        "key": "referensi_tambahan",
        "endpoint": "analyze_reference_recommendations",
        "label": "Rekomendasi Referensi Tambahan",
    },
]

LEGACY_WORKFLOW_KEYS = (
    "judul",
    "abstrak",
    "pendahuluan",
    "metodologi",
    "hasil_pembahasan",
    "kesimpulan",
    "sitasi_apa",
    "referensi_tambahan",
)

SECTION_STAGE_META = {
    "abstrak": ("ABS", "Abstrak"),
    "pendahuluan": ("INTRO", "Pendahuluan"),
    "metodologi": ("MET", "Metodologi"),
    "hasil_pembahasan": ("HP", "Hasil dan Pembahasan"),
    "kesimpulan": ("KES", "Kesimpulan"),
    "konsistensi": ("KON", "Konsistensi Lintas Bagian"),
    "judul": ("JDL", "Judul"),
}

SECTION_CHUNK_CHARS = int(os.getenv("SECTION_CHUNK_CHARS", "20000"))

ANALYSIS_MODE_LABELS = {
    "ringkas": "Analisis Ringkas",
    "mendalam": "Analisis Mendalam",
}
ANALYSIS_MODE_DESCRIPTIONS = {
    "ringkas": "Menampilkan komentar singkat hanya pada bagian yang paling perlu direvisi.",
    "mendalam": "Menampilkan alasan akademik, dampak, dan contoh revisi untuk masalah penting.",
}


def analysis_mode(result):
    """Mode analisis hasil ini; hasil lama tanpa field mode = mode mendalam lama."""
    return resolve_analysis_mode((result or {}).get("_mode_analisis"))


def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def extract_docx_text(path):
    """Kompatibilitas lama: teks polos artikel (dipakai untuk pemeriksaan cepat)."""
    return extract_article_structure(path)["full_text"]


def detect_title(structure):
    awal = structure["sections"].get("awal")
    candidates = [p["text"] for p in awal["paragraphs"]] if awal else []
    if not candidates and structure.get("fallback"):
        artikel = structure["sections"].get("artikel")
        if artikel and artikel["paragraphs"]:
            candidates = [artikel["paragraphs"][0]["text"]]
    if not candidates:
        return {"detected": False, "title": "", "note": "Judul tidak terdeteksi."}
    title = candidates[0]
    if len(title) < 12 and len(candidates) > 1:
        title = " ".join(candidates[:2])
    return {
        "detected": True,
        "title": title,
        "note": "Kandidat judul diambil dari baris awal artikel sebelum bagian Abstrak.",
    }


def build_short_article_context(structure):
    parts = [
        detect_title(structure).get("title", ""),
        (get_section(structure, "abstrak") or {}).get("text", ""),
        (get_section(structure, "pendahuluan") or {}).get("text", ""),
    ]
    return "\n\n".join(item for item in parts if item)[:5000]


# ---------------------------------------------------------------------------
# Pemanggilan model
# ---------------------------------------------------------------------------

def call_openai_chat(system_prompt, user_prompt, force_json=False):
    api_key = get_session_api_key()
    if not api_key:
        raise RuntimeError(
            "OpenAI API key belum dimasukkan untuk sesi ini. Silakan isi API key terlebih dahulu."
        )

    client = build_user_client(api_key)
    kwargs = {
        "model": get_model_name(),
        "instructions": system_prompt,
        "input": user_prompt,
        "max_output_tokens": get_max_output_tokens(),
    }
    if force_json:
        kwargs["text"] = {"format": {"type": "json_object"}}

    try:
        response = client.responses.create(**kwargs)
    except TypeError:
        # SDK lama tanpa dukungan parameter tertentu: coba tanpa opsi tambahan.
        kwargs.pop("text", None)
        kwargs.pop("max_output_tokens", None)
        try:
            response = client.responses.create(**kwargs)
        except openai.OpenAIError as exc:
            raise RuntimeError(translate_openai_error(exc)) from exc
    except openai.BadRequestError as exc:
        if force_json:
            # Model/akun tidak mendukung format JSON terstruktur: ulangi tanpa format.
            kwargs.pop("text", None)
            try:
                response = client.responses.create(**kwargs)
            except openai.OpenAIError as retry_exc:
                raise RuntimeError(translate_openai_error(retry_exc)) from retry_exc
        else:
            raise RuntimeError(translate_openai_error(exc)) from exc
    except openai.OpenAIError as exc:
        raise RuntimeError(translate_openai_error(exc)) from exc

    status = getattr(response, "status", None)
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", "") if details else ""
        if reason == "max_output_tokens":
            raise RuntimeError(
                "Keluaran model terpotong karena melebihi batas token keluaran. "
                "Naikkan OPENAI_MAX_OUTPUT_TOKENS atau analisis bagian yang lebih pendek. "
                "Hasil terpotong tidak ditampilkan agar tidak menyesatkan."
            )
        raise RuntimeError(
            "Keluaran model tidak selesai (incomplete). Silakan ulangi analisis."
        )

    content = response.output_text
    if not content:
        raise RuntimeError("OpenAI API mengembalikan respons kosong. Silakan ulangi analisis.")

    return content


JSON_REPAIR_SYSTEM = (
    "Anda memperbaiki teks menjadi JSON valid. Jangan menambah, menghapus, atau "
    "mengubah isi substantif; hanya perbaiki sintaks JSON. Kembalikan hanya JSON."
)


def openai_chat_json(system_prompt, user_prompt):
    content = call_openai_chat(system_prompt, user_prompt, force_json=True)
    try:
        return parse_model_json(content)
    except ModelJSONError:
        pass
    # Satu kali koreksi terkontrol: minta model memperbaiki sintaks JSON-nya sendiri.
    repaired = call_openai_chat(
        JSON_REPAIR_SYSTEM,
        "Perbaiki teks berikut menjadi satu objek JSON valid:\n\n" + content,
        force_json=True,
    )
    try:
        return parse_model_json(repaired)
    except ModelJSONError as exc:
        raise RuntimeError(
            "OpenAI API mengembalikan respons yang bukan JSON valid dan tidak dapat "
            "diperbaiki otomatis. Coba ulangi analisis."
        ) from exc


def test_openai_connection():
    return call_openai_chat(
        "Jawab secara singkat dan jelas dalam bahasa Indonesia.",
        "Halo",
    )


# ---------------------------------------------------------------------------
# Profil artikel dan finalisasi hasil analisis
# ---------------------------------------------------------------------------

def profile_summary_for_prompts(result):
    type_key, source = effective_article_type(result)
    klasifikasi = (result.get("profil_artikel") or {}).get("klasifikasi_artikel") or {}
    heuristik = result.get("_profil_heuristik") or {}
    base = klasifikasi if klasifikasi else heuristik
    return (
        {
            "jenis_artikel": article_type_label(type_key),
            "kunci_jenis": type_key,
            "pendekatan_penelitian": base.get("pendekatan_penelitian", ""),
            "desain_penelitian": base.get("desain_penelitian", ""),
            "tingkat_keyakinan": base.get("tingkat_keyakinan", "rendah"),
            "sumber_penentuan": source,
            "catatan": base.get("catatan", ""),
        },
        type_key,
    )


def finalize_section_result(data, structure, stage_key, type_key, mode="mendalam"):
    """Normalisasi + validasi bukti + filter kriteria tidak relevan + batas mode."""
    code, label = SECTION_STAGE_META.get(stage_key, ("SEC", stage_key.title()))
    data = normalize_section_result(data, code, label)
    findings, stats = validate_findings_quotes(
        data["masalah_teridentifikasi"], structure
    )
    kept, excluded = filter_false_positive_findings(findings, type_key)
    data["masalah_teridentifikasi"] = sort_findings(kept)
    if excluded:
        data["masalah_dikecualikan"] = excluded + list(data.get("masalah_dikecualikan") or [])
    data = apply_mode_limits(data, mode)
    data["validasi_bukti"] = stats
    return data


def split_section_batches(section, limit=SECTION_CHUNK_CHARS):
    """Pecah bagian panjang menjadi kelompok paragraf tanpa mengubah penomoran."""
    if not section or not section["paragraphs"]:
        return [section]
    batches = []
    current = []
    current_len = 0
    for paragraph in section["paragraphs"]:
        current.append(paragraph)
        current_len += len(paragraph["text"])
        if current_len >= limit:
            batches.append(current)
            current, current_len = [], 0
    if current:
        batches.append(current)
    if len(batches) <= 1:
        return [section]
    return [
        {**section, "paragraphs": batch, "tables": section.get("tables", []) if index == 0 else []}
        for index, batch in enumerate(batches)
    ]


def merge_partial_results(partials, list_keys=(), text_keys=()):
    """Gabungkan hasil batch tanpa kehilangan nomor lokasi paragraf."""
    if len(partials) == 1:
        return partials[0]
    merged = dict(partials[0])
    for key in ("masalah_teridentifikasi", "prioritas_revisi",
                "catatan_data_yang_harus_dilengkapi", *list_keys):
        combined = []
        for partial in partials:
            value = partial.get(key)
            if isinstance(value, list):
                combined.extend(value)
            elif value:
                combined.append(value)
        merged[key] = combined
    for key in ("versi_revisi", *text_keys):
        texts = [str(p.get(key) or "").strip() for p in partials]
        merged[key] = "\n\n".join(t for t in texts if t)
    summaries = [str(p.get("ringkasan") or "").strip() for p in partials]
    merged["ringkasan"] = " ".join(s for s in summaries if s)
    scores = []
    for partial in partials:
        try:
            scores.append(int(partial.get("skor")))
        except (TypeError, ValueError):
            continue
    merged["skor"] = round(sum(scores) / len(scores)) if scores else None
    return merged


def analyze_section_with_batches(section, prompt_fn, list_keys=(), text_keys=()):
    """Analisis satu bagian; bila terlalu panjang, pecah per kelompok paragraf."""
    batches = split_section_batches(section)
    partials = []
    for index, batch in enumerate(batches):
        note = ""
        if len(batches) > 1 and batch and batch.get("paragraphs"):
            first = batch["paragraphs"][0]["paragraph_number"]
            last = batch["paragraphs"][-1]["paragraph_number"]
            note = (
                f" (Batch {index + 1}/{len(batches)}: hanya paragraf {first}-{last}; "
                "gunakan nomor paragraf asli seperti pada penanda.)"
            )
        partials.append(openai_chat_json(SYSTEM_ANALYST, prompt_fn(batch, note)))
    return merge_partial_results(partials, list_keys=list_keys, text_keys=text_keys)


def validate_classification_evidence(klasifikasi, structure):
    validated = []
    for item in klasifikasi.get("bukti_teks") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("kutipan") or "")
        located = locate_quote(quote, structure)
        entry = {
            "lokasi": str(item.get("lokasi") or ""),
            "kutipan": quote,
        }
        if located["status"] == "eksak":
            entry["validasi"] = "terverifikasi"
        elif located["status"] == "dikoreksi":
            entry["kutipan"] = located["kutipan_terkoreksi"]
            entry["validasi"] = "dikoreksi_otomatis"
        else:
            entry["validasi"] = "tidak_ditemukan"
        if located.get("lokasi"):
            entry["lokasi_terverifikasi"] = located["lokasi"]
        validated.append(entry)
    klasifikasi["bukti_teks"] = validated
    return klasifikasi


# ---------------------------------------------------------------------------
# Fungsi analisis per tahap
# ---------------------------------------------------------------------------

def stage_profile(structure, result):
    heuristic = result.get("_profil_heuristik") or detect_article_profile(structure)
    result["_profil_heuristik"] = heuristic
    data = openai_chat_json(
        SYSTEM_ANALYST,
        prompt_builders.build_classification_prompt(structure, heuristic),
    )
    klasifikasi = data.get("klasifikasi_artikel") or {}
    jenis = str(klasifikasi.get("jenis_artikel") or "").strip()
    if jenis not in APPROACH_SIGNALS and jenis != "belum_teridentifikasi":
        klasifikasi["jenis_artikel"] = heuristic.get("jenis_artikel", "belum_teridentifikasi")
        klasifikasi["catatan"] = (
            (str(klasifikasi.get("catatan") or "") + " ").strip()
            + " Jenis dari model tidak dikenali; memakai hasil deteksi heuristik."
        ).strip()
    if str(klasifikasi.get("tingkat_keyakinan", "")).lower() not in ("tinggi", "sedang", "rendah"):
        klasifikasi["tingkat_keyakinan"] = "rendah"
    klasifikasi = validate_classification_evidence(klasifikasi, structure)
    klasifikasi["label"] = article_type_label(klasifikasi.get("jenis_artikel"))
    return {
        "klasifikasi_artikel": klasifikasi,
        "deteksi_heuristik": heuristic,
    }


def stage_title(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    title_info = detect_title(structure)
    data = openai_chat_json(
        SYSTEM_ANALYST,
        prompt_builders.build_title_prompt(
            title_info["title"],
            profile_summary,
            build_short_article_context(structure),
            mode=mode,
        ),
    )
    findings = [
        normalize_finding(raw, "JDL", index)
        for index, raw in enumerate(data.get("masalah_teridentifikasi") or [])
    ]
    findings, stats = validate_findings_quotes(findings, structure)
    data["masalah_teridentifikasi"] = sort_findings(findings)
    data = apply_mode_limits(data, mode)
    data["validasi_bukti"] = stats
    data["judul_awal"] = data.get("judul_awal") or title_info["title"]
    return data


def _abstract_context(structure):
    blocks = []
    for key, label in (
        ("metodologi", "Metodologi"),
        ("hasil_pembahasan", "Hasil utama"),
        ("kesimpulan", "Kesimpulan"),
    ):
        section = get_section(structure, key)
        text = format_section_for_prompt(section, max_chars=7000)
        blocks.append(
            f"{label}:\n\"\"\"{text}\"\"\""
        )
    title = detect_title(structure).get("title", "")
    return f"Judul:\n\"\"\"{title}\"\"\"\n\n" + "\n\n".join(blocks)


def stage_abstract(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    abstract_section = get_section(structure, "abstrak")
    data = openai_chat_json(
        SYSTEM_ANALYST,
        prompt_builders.build_abstract_prompt(
            profile_summary,
            type_key,
            abstract_section,
            _abstract_context(structure),
            mode=mode,
        ),
    )
    return finalize_section_result(data, structure, "abstrak", type_key, mode)


def stage_introduction(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    intro_section = get_section(structure, "pendahuluan")
    abstract_context = format_section_for_prompt(
        get_section(structure, "abstrak"), max_chars=3000
    )
    methodology_context = format_section_for_prompt(
        get_section(structure, "metodologi"), max_chars=3000
    )
    context = (
        f"Judul: {detect_title(structure).get('title', '')}\n\n"
        f"Abstrak:\n\"\"\"{abstract_context}\"\"\"\n\n"
        f"Metodologi (ringkas):\n\"\"\"{methodology_context}\"\"\""
    )
    data = analyze_section_with_batches(
        intro_section,
        lambda batch, note: prompt_builders.build_introduction_prompt(
            profile_summary,
            type_key,
            format_section_for_prompt(batch),
            context,
            batch_note=note,
            mode=mode,
        ),
        list_keys=("peta_fungsi_paragraf",),
        text_keys=("evaluasi_gap_penelitian", "evaluasi_tujuan_dan_rumusan_masalah"),
    )
    return finalize_section_result(data, structure, "pendahuluan", type_key, mode)


def stage_methodology(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    method_section = get_section(structure, "metodologi")
    abstract_context = format_section_for_prompt(
        get_section(structure, "abstrak"), max_chars=3000
    )
    introduction_context = format_section_tail_for_prompt(
        get_section(structure, "pendahuluan"), max_chars=3000
    )
    context = (
        f"Judul: {detect_title(structure).get('title', '')}\n\n"
        f"Abstrak:\n\"\"\"{abstract_context}\"\"\"\n\n"
        f"Pendahuluan (bagian akhir, biasanya memuat tujuan):\n"
        f"\"\"\"{introduction_context}\"\"\""
    )
    data = analyze_section_with_batches(
        method_section,
        lambda batch, note: prompt_builders.build_methodology_prompt(
            profile_summary,
            type_key,
            format_section_for_prompt(batch) + note,
            context,
            mode=mode,
        ),
        list_keys=("pemeriksaan_komponen",),
        text_keys=("kesesuaian_metode_dengan_tujuan",),
    )
    return finalize_section_result(data, structure, "metodologi", type_key, mode)


def stage_results_discussion(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    section = get_section(structure, "hasil_pembahasan")
    tables_text = "\n\n".join(
        f"[{table['id']}] Tabel {table['table_number']} (bagian {table['section_label']}):\n"
        + table["text"][:2500]
        for table in structure.get("tables", [])
    )
    methodology_context = format_section_for_prompt(
        get_section(structure, "metodologi"), max_chars=5000
    )
    context = (
        f"Judul: {detect_title(structure).get('title', '')}\n\n"
        f"Metodologi (ringkas):\n\"\"\"{methodology_context}\"\"\""
    )
    data = analyze_section_with_batches(
        section,
        lambda batch, note: prompt_builders.build_results_discussion_prompt(
            profile_summary,
            type_key,
            format_section_for_prompt(batch),
            tables_text,
            context,
            batch_note=note,
            mode=mode,
        ),
        list_keys=(
            "interpretasi_tabel",
            "analisis_tema",
            "analisis_pembahasan_per_paragraf",
        ),
        text_keys=("versi_revisi_hasil", "versi_revisi_pembahasan"),
    )
    return finalize_section_result(data, structure, "hasil_pembahasan", type_key, mode)


def stage_conclusion(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    conclusion_section = get_section(structure, "kesimpulan")
    results_text = format_section_for_prompt(
        get_section(structure, "hasil_pembahasan"), max_chars=9000
    )
    context = (
        f"Judul: {detect_title(structure).get('title', '')}\n\n"
        f"Hasil dan pembahasan (sumber klaim):\n\"\"\"{results_text}\"\"\""
    )
    data = openai_chat_json(
        SYSTEM_ANALYST,
        prompt_builders.build_conclusion_prompt(
            profile_summary,
            type_key,
            format_section_for_prompt(conclusion_section),
            context,
            mode=mode,
        ),
    )
    return finalize_section_result(data, structure, "kesimpulan", type_key, mode)


def stage_cross_section(structure, result):
    profile_summary, type_key = profile_summary_for_prompts(result)
    mode = analysis_mode(result)
    section_limit = 3500 if mode == "ringkas" else 7000
    section_texts = []
    section_texts.append(
        (
            "Judul/awal artikel",
            format_section_for_prompt(
                structure["sections"].get("awal"), max_chars=2000
            ),
        )
    )
    for key in ("abstrak", "pendahuluan", "metodologi", "hasil_pembahasan", "kesimpulan"):
        section = get_section(structure, key)
        section_texts.append(
            (
                (section or {}).get("label", key.title()),
                format_section_for_prompt(section, max_chars=section_limit),
            )
        )
    citation_summary = run_citation_check(structure)["pencocokan"]["statistik"]
    data = openai_chat_json(
        SYSTEM_ANALYST,
        prompt_builders.build_cross_section_prompt(
            profile_summary, type_key, section_texts, citation_summary, mode=mode
        ),
    )
    data = finalize_section_result(data, structure, "konsistensi", type_key, mode)
    data["statistik_sitasi"] = citation_summary
    return data


def stage_citations(structure, result):
    deterministic = run_citation_check(structure)
    reference_section = get_section(structure, "daftar_pustaka")
    reference_text = (reference_section or {}).get("text", "")
    try:
        ai_explanation = openai_chat_json(
            SYSTEM_ANALYST,
            prompt_builders.build_citation_explanation_prompt(
                deterministic, reference_text, mode=analysis_mode(result)
            ),
        )
    except RuntimeError as exc:
        ai_explanation = {
            "ringkasan_kualitas_referensi": (
                "Penjelasan AI tidak tersedia: " + safe_error_message(exc)
            )
        }
    return {**deterministic, "evaluasi_ai": ai_explanation}


STAGE_HANDLERS = {
    "profil_artikel": stage_profile,
    "judul": stage_title,
    "abstrak": stage_abstract,
    "pendahuluan": stage_introduction,
    "metodologi": stage_methodology,
    "hasil_pembahasan": stage_results_discussion,
    "kesimpulan": stage_conclusion,
    "konsistensi": stage_cross_section,
    "sitasi_apa": stage_citations,
}


# ---------------------------------------------------------------------------
# Rekomendasi referensi tambahan (OpenAlex/Crossref)
# ---------------------------------------------------------------------------

REVISION_SYSTEM_PROMPT = (
    "Anda adalah editor artikel ilmiah. Berikan revisi final yang ringkas dan siap dipakai. "
    "Jangan mengarang data, angka, lokasi, metode, hasil, sitasi, atau referensi baru. "
    "Jika informasi tidak tersedia, nyatakan bahwa bagian tersebut perlu dilengkapi penulis. "
    "Kembalikan hanya JSON valid sesuai format."
)

_LEGACY_REVISION_FIELDS = {
    "abstrak": "abstrak_revisi",
    "pendahuluan": "pendahuluan_revisi",
    "metodologi": "metodologi_revisi",
    "hasil_pembahasan": "hasil_pembahasan_revisi",
    "kesimpulan": "kesimpulan_revisi",
}


def stage_revision_text(result, key):
    stage = result.get(key) or {}
    return (
        stage.get("versi_revisi")
        or stage.get(_LEGACY_REVISION_FIELDS.get(key, ""), "")
        or ""
    )


def stage_context_text(result, structure, key, limit):
    """Teks bagian untuk konteks pencarian referensi.

    Mode ringkas tidak menghasilkan versi revisi, sehingga teks asli artikel
    dipakai sebagai fallback.
    """
    text = stage_revision_text(result, key)
    if not text.strip() and structure is not None:
        section = get_section(structure, key)
        text = (section or {}).get("text", "")
    return text[:limit]


def extract_reference_search_terms(result, structure=None):
    prompt = f"""
Ekstrak kata kunci pencarian artikel ilmiah dari teks berikut.
Berikan 5-8 kata kunci dan 3 query pencarian singkat. Jangan menambahkan topik yang tidak ada.

Judul:
{result.get("judul", {}).get("judul_rekomendasi", "")}

Abstrak:
{stage_context_text(result, structure, "abstrak", 4000)}

Pendahuluan:
{stage_context_text(result, structure, "pendahuluan", 4000)}

Metodologi:
{stage_context_text(result, structure, "metodologi", 4000)}

Format JSON:
{{"kata_kunci": ["..."], "query_pencarian": ["...", "...", "..."]}}
""".strip()
    data = openai_chat_json(REVISION_SYSTEM_PROMPT, prompt)
    keywords = [str(item).strip() for item in data.get("kata_kunci", []) if str(item).strip()]
    queries = [str(item).strip() for item in data.get("query_pencarian", []) if str(item).strip()]
    title = result.get("judul", {}).get("judul_rekomendasi", "").strip()
    if title:
        queries.insert(0, title)
    return {
        "kata_kunci": keywords[:8],
        "query_pencarian": list(dict.fromkeys(queries))[:4],
    }


def normalize_doi(value):
    if not value:
        return ""
    doi = str(value).strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    return doi.strip()


def format_authors_apa(authors):
    def format_name(name):
        value = str(name).strip()
        if not value:
            return ""
        if "," in value:
            family, given = [part.strip() for part in value.split(",", 1)]
        else:
            parts = value.split()
            if len(parts) == 1:
                return parts[0]
            family, given = parts[-1], " ".join(parts[:-1])
        initials = " ".join(
            f"{part[0].upper()}."
            for part in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", given)
            if part
        )
        return f"{family}, {initials}".strip().rstrip(",")

    names = [format_name(name) for name in authors if str(name).strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]}, & {names[1]}"
    return f"{', '.join(names[:-1])}, & {names[-1]}"


def format_reference_apa_7(reference):
    authors = format_authors_apa(reference.get("penulis_list", []))
    year = reference.get("tahun") or "n.d."
    title = reference.get("judul", "").rstrip(".")
    journal = reference.get("jurnal", "").rstrip(".")
    doi = normalize_doi(reference.get("doi"))
    prefix = f"{authors} ({year})." if authors else f"({year})."
    parts = [prefix, f"{title}."]
    if journal:
        parts.append(f"{journal}.")
    if doi:
        parts.append(f"https://doi.org/{doi}")
    return " ".join(parts)


def crossref_reference_from_item(item):
    title_values = item.get("title") or []
    container_values = item.get("container-title") or []
    authors = []
    for author in item.get("author") or []:
        family = str(author.get("family") or "").strip()
        given = str(author.get("given") or "").strip()
        name = ", ".join(part for part in (family, given) if part)
        if name:
            authors.append(name)
    date_parts = (
        item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or item.get("issued", {}).get("date-parts")
        or []
    )
    year = date_parts[0][0] if date_parts and date_parts[0] else ""
    reference = {
        "judul": str(title_values[0]).strip() if title_values else "",
        "penulis": "; ".join(authors),
        "penulis_list": authors,
        "tahun": str(year),
        "jurnal": str(container_values[0]).strip() if container_values else "",
        "quartile_atau_sinta": "Perlu verifikasi pada Scopus/WoS/SINTA",
        "doi": normalize_doi(item.get("DOI")),
        "sumber_metadata": "Crossref",
        "jumlah_sitasi": int(item.get("is-referenced-by-count") or 0),
    }
    reference["apa_7"] = format_reference_apa_7(reference)
    return reference


def openalex_reference_from_item(item):
    authors = [
        authorship.get("author", {}).get("display_name", "").strip()
        for authorship in item.get("authorships") or []
        if authorship.get("author", {}).get("display_name", "").strip()
    ]
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}
    reference = {
        "judul": str(item.get("display_name") or item.get("title") or "").strip(),
        "penulis": "; ".join(authors),
        "penulis_list": authors,
        "tahun": str(item.get("publication_year") or ""),
        "jurnal": str(source.get("display_name") or "").strip(),
        "quartile_atau_sinta": "Perlu verifikasi pada Scopus/WoS/SINTA",
        "doi": normalize_doi((item.get("ids") or {}).get("doi") or item.get("doi")),
        "sumber_metadata": "OpenAlex",
        "jumlah_sitasi": int(item.get("cited_by_count") or 0),
    }
    reference["apa_7"] = format_reference_apa_7(reference)
    return reference


def reference_is_complete(reference):
    return all(
        reference.get(key)
        for key in ("judul", "penulis", "tahun", "jurnal", "doi")
    )


def search_crossref(query, limit=15):
    params = {
        "query.bibliographic": query,
        "filter": "type:journal-article",
        "rows": limit,
    }
    email = os.getenv("SCHOLARLY_API_EMAIL", "").strip()
    if email:
        params["mailto"] = email
    response = httpx.get(
        "https://api.crossref.org/works",
        params=params,
        headers={"User-Agent": "RevisiArtikelAI/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    return [crossref_reference_from_item(item) for item in items]


def search_openalex(query, limit=15):
    params = {
        "search": query,
        "filter": "type:article,has_doi:true",
        "per-page": limit,
    }
    email = os.getenv("SCHOLARLY_API_EMAIL", "").strip()
    if email:
        params["mailto"] = email
    response = httpx.get(
        "https://api.openalex.org/works",
        params=params,
        headers={"User-Agent": "RevisiArtikelAI/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    return [
        openalex_reference_from_item(item)
        for item in response.json().get("results", [])
    ]


def rank_reference_candidates(candidates, result, search_terms, structure=None):
    immutable_candidates = [
        {
            "id": index,
            "judul": item["judul"],
            "tahun": item["tahun"],
            "jurnal": item["jurnal"],
        }
        for index, item in enumerate(candidates)
    ]
    prompt = f"""
Urutkan kandidat referensi nyata berikut berdasarkan relevansi dengan artikel.
Jangan mengubah metadata dan jangan menambahkan referensi. Gunakan hanya ID yang tersedia.

Konteks artikel:
Judul: {result.get("judul", {}).get("judul_rekomendasi", "")}
Abstrak: {stage_context_text(result, structure, "abstrak", 3000)}
Pendahuluan: {stage_context_text(result, structure, "pendahuluan", 3000)}
Metodologi: {stage_context_text(result, structure, "metodologi", 3000)}
Kata kunci: {", ".join(search_terms.get("kata_kunci", []))}

Kandidat:
{json.dumps(immutable_candidates, ensure_ascii=False)}

Kategori yang diizinkan:
1. Sangat relevan dengan topik
2. Sangat relevan dengan metodologi
3. Pendukung teori dan pembahasan

Format JSON:
{{
  "peringkat": [
    {{"id": 0, "kategori": "1", "alasan_relevan": "alasan singkat berbasis judul kandidat"}}
  ]
}}
""".strip()
    try:
        ranked = openai_chat_json(REVISION_SYSTEM_PROMPT, prompt).get("peringkat", [])
    except Exception:
        ranked = []

    ranking_map = {}
    for position, item in enumerate(ranked):
        try:
            candidate_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if 0 <= candidate_id < len(candidates) and candidate_id not in ranking_map:
            category = str(item.get("kategori") or "3").strip()
            category = category[0] if category and category[0] in {"1", "2", "3"} else "3"
            ranking_map[candidate_id] = {
                "position": position,
                "kategori": category,
                "alasan_relevan": str(item.get("alasan_relevan") or "").strip(),
            }

    ordered = []
    for index, reference in enumerate(candidates):
        annotation = ranking_map.get(index, {})
        item = dict(reference)
        item["kategori"] = annotation.get("kategori", "3")
        item["alasan_relevan"] = annotation.get(
            "alasan_relevan",
            "Relevan berdasarkan kemiripan metadata dengan kata kunci artikel.",
        )
        item["_rank"] = annotation.get("position", len(candidates) + index)
        ordered.append(item)
    ordered.sort(key=lambda item: (item["_rank"], -item.get("jumlah_sitasi", 0)))
    for item in ordered:
        item.pop("_rank", None)
    return ordered


def find_verified_reference_recommendations(result, structure=None):
    search_terms = extract_reference_search_terms(result, structure)
    candidates_by_doi = {}
    errors = []

    search_jobs = [
        (search_function, query)
        for query in search_terms["query_pencarian"]
        for search_function in (search_openalex, search_crossref)
    ]
    if not search_jobs:
        raise RuntimeError("Kata kunci pencarian referensi tidak berhasil diekstrak.")
    with ThreadPoolExecutor(max_workers=min(8, len(search_jobs))) as executor:
        futures = {
            executor.submit(search_function, query): (search_function, query)
            for search_function, query in search_jobs
        }
        for future in as_completed(futures):
            search_function, query = futures[future]
            try:
                references = future.result()
            except Exception as exc:
                errors.append(f"{search_function.__name__} ({query}): {exc}")
                continue
            for reference in references:
                doi = normalize_doi(reference.get("doi"))
                if doi and reference_is_complete(reference):
                    existing = candidates_by_doi.get(doi)
                    if not existing or reference.get("jumlah_sitasi", 0) > existing.get("jumlah_sitasi", 0):
                        candidates_by_doi[doi] = reference

    candidates = sorted(
        candidates_by_doi.values(),
        key=lambda item: item.get("jumlah_sitasi", 0),
        reverse=True,
    )[:30]
    ranked = rank_reference_candidates(candidates, result, search_terms, structure)[:15]
    if len(ranked) < 10:
        raise RuntimeError(
            "Sumber ilmiah hanya menghasilkan "
            f"{len(ranked)} referensi dengan metadata lengkap. "
            "Minimal 10 referensi aktual diperlukan; sistem tidak membuat referensi fiktif."
        )
    return {
        "kata_kunci": search_terms["kata_kunci"],
        "query_pencarian": search_terms["query_pencarian"],
        "rekomendasi": ranked,
        "referensi_dipilih": [],
        "catatan_pencarian": (
            f"Ditemukan {len(ranked)} referensi aktual dari OpenAlex/Crossref. "
            "Status quartile Scopus/WoS atau SINTA perlu diverifikasi pada portal indeks terkait."
        ),
        "error_sumber": errors,
    }


# ---------------------------------------------------------------------------
# Penyimpanan hasil dan konteks template
# ---------------------------------------------------------------------------

def article_type_context(result):
    type_key, source = effective_article_type(result)
    klasifikasi = (result.get("profil_artikel") or {}).get("klasifikasi_artikel") or {}
    heuristik = result.get("_profil_heuristik") or {}
    base = klasifikasi if klasifikasi else heuristik
    return {
        "key": type_key,
        "label": article_type_label(type_key),
        "sumber": source,
        "keyakinan": base.get("tingkat_keyakinan", "rendah"),
        "catatan": base.get("catatan", ""),
        "pilihan_pengguna": result.get("_jenis_artikel_pilihan", "otomatis"),
        "choices": ARTICLE_TYPE_CHOICES,
    }


def citation_groups_for_display(stage_data):
    """Samakan hasil sitasi skema baru dan hasil WIP lama untuk UI/PDF."""
    stage_data = stage_data if isinstance(stage_data, dict) else {}
    matching = stage_data.get("pencocokan")
    if isinstance(matching, dict):
        return {
            "statistik": matching.get("statistik", {}),
            "sitasi_tanpa_referensi": matching.get("sitasi_tanpa_referensi", []),
            "tahun_tidak_cocok": matching.get("tahun_tidak_cocok", []),
            "kemungkinan_cocok": matching.get("kemungkinan_cocok", []),
            "referensi_tidak_pernah_disitasi": matching.get(
                "referensi_tidak_pernah_disitasi", []
            ),
            "referensi_duplikat": matching.get("referensi_duplikat", []),
            "referensi_tidak_lengkap": matching.get("referensi_tidak_lengkap", []),
            "sitasi_sekunder": matching.get("sitasi_sekunder", []),
            "referensi_bermasalah": [],
            "catatan_akhir_sitasi": "",
        }
    return {
        "statistik": {},
        "sitasi_tanpa_referensi": stage_data.get("sitasi_tanpa_referensi", []),
        "tahun_tidak_cocok": [],
        "kemungkinan_cocok": [],
        "referensi_tidak_pernah_disitasi": stage_data.get(
            "referensi_tidak_disitasi", []
        ),
        "referensi_duplikat": [],
        "referensi_tidak_lengkap": [],
        "sitasi_sekunder": [],
        "referensi_bermasalah": stage_data.get("referensi_bermasalah", []),
        "catatan_akhir_sitasi": stage_data.get("catatan_akhir_sitasi", ""),
    }


def result_template_context(filename, output_name, result):
    mode = analysis_mode(result)
    return {
        "filename": filename,
        "output_name": output_name,
        "review_complete": is_review_complete(result),
        "workflow_steps": get_workflow_steps(result),
        "article_type": article_type_context(result),
        "citation_groups": citation_groups_for_display(result.get("sitasi_apa")),
        "analysis_mode": mode,
        "analysis_mode_label": ANALYSIS_MODE_LABELS[mode],
        "result": result,
    }


def get_workflow_steps(result=None):
    result = result or {}
    is_uploaded = bool(result.get("_uploaded"))
    unlocked_next = is_uploaded
    steps = []

    for step in WORKFLOW_STEPS:
        is_complete = bool(result.get(step["key"]))
        is_unlocked = is_complete or unlocked_next

        if not is_complete:
            unlocked_next = False
        else:
            unlocked_next = True

        if is_complete:
            status = "Selesai"
            icon = "✓"
        elif is_unlocked:
            status = "Aktif"
            icon = "▶"
        else:
            status = "Terkunci"
            icon = "🔒"

        steps.append(
            {
                **step,
                "complete": is_complete,
                "unlocked": is_unlocked,
                "status": status,
                "icon": icon,
            }
        )

    return steps


def module_is_unlocked(result, module_key):
    for step in get_workflow_steps(result):
        if step["key"] == module_key:
            return step["unlocked"]
    return False


def is_review_complete(result):
    if all(result.get(step["key"]) for step in WORKFLOW_STEPS):
        return True
    is_legacy_result = not result.get("_profil_heuristik")
    return is_legacy_result and all(result.get(key) for key in LEGACY_WORKFLOW_KEYS)


def guard_module_order(result, module_key):
    if module_is_unlocked(result, module_key):
        return True

    flash("Tombol ini masih terkunci. Jalankan analisis sebelumnya sesuai urutan terlebih dahulu.")
    return False


def save_result(filename, result):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_name = f"{Path(filename).stem}-{timestamp}.json"
    output_path = user_output_dir() / output_name
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_name


def load_result(output_name):
    output_path = user_output_dir() / secure_filename(output_name)
    if not output_path.exists():
        return None
    return json.loads(output_path.read_text(encoding="utf-8"))


def update_result(output_name, result):
    output_path = user_output_dir() / secure_filename(output_name)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def uploaded_file_is_used_elsewhere(filename, excluded_output_name):
    for output_path in user_output_dir().glob("*.json"):
        if output_path.name == excluded_output_name:
            continue
        try:
            other_result = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if secure_filename(other_result.get("_filename", "")) == filename:
            return True
    return False


# ---------------------------------------------------------------------------
# Ekspor PDF
# ---------------------------------------------------------------------------

def pdf_safe_text(value):
    text = str(value)
    return escape(text).replace("\n", "<br/>")


def add_pdf_value(story, value, styles, level=0):
    if isinstance(value, dict):
        for key, child in value.items():
            label = str(key).replace("_", " ").title()
            story.append(Paragraph(pdf_safe_text(label), styles["FieldLabel"]))
            add_pdf_value(story, child, styles, level + 1)
        return

    if isinstance(value, list):
        if not value:
            story.append(Paragraph("Tidak ada.", styles["BodyText"]))
            return
        for item in value:
            if isinstance(item, (dict, list)):
                add_pdf_value(story, item, styles, level + 1)
            else:
                story.append(
                    Paragraph(
                        pdf_safe_text(item),
                        styles["ReviewBullet"],
                        bulletText="-",
                    )
                )
        return

    story.append(
        Paragraph(
            pdf_safe_text(value if value is not None else "Tidak ada."),
            styles["BodyText"],
        )
    )


FINDING_PDF_FIELDS = [
    ("lokasi", "Lokasi"),
    ("kutipan_asli", "Kutipan asli"),
    ("jenis_masalah", "Jenis masalah"),
    ("kriteria_yang_digunakan", "Kriteria yang digunakan"),
    ("masalah", "Masalah"),
    ("alasan", "Alasan"),
    ("dampak", "Dampak"),
    ("tindakan_revisi", "Tindakan revisi"),
    ("contoh_revisi", "Contoh revisi"),
    ("status_contoh", "Status contoh revisi"),
    ("keterkaitan", "Hubungan dengan bagian lain"),
    ("keyakinan", "Keyakinan"),
    ("validasi_kutipan", "Validasi kutipan"),
]

# Mode ringkas hanya memuat inti temuan agar PDF lebih pendek.
FINDING_PDF_FIELDS_RINGKAS = [
    ("lokasi", "Lokasi"),
    ("kutipan_asli", "Kutipan asli"),
    ("masalah", "Masalah"),
    ("tindakan_revisi", "Tindakan revisi"),
    ("validasi_kutipan", "Validasi kutipan"),
]


def add_finding_to_pdf(story, finding, styles, mode="mendalam"):
    header = (
        f"{finding.get('id', '')} — Prioritas: {str(finding.get('prioritas', '')).upper()}"
    )
    fields = FINDING_PDF_FIELDS_RINGKAS if mode == "ringkas" else FINDING_PDF_FIELDS
    story.append(Paragraph(pdf_safe_text(header), styles["FieldTitle"]))
    for key, label in fields:
        value = finding.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "lokasi" and isinstance(value, dict):
            parts = [value.get("bagian") or ""]
            if value.get("paragraf"):
                parts.append(f"paragraf {value['paragraf']}")
            if value.get("kalimat"):
                parts.append(f"kalimat {value['kalimat']}")
            if value.get("penanda"):
                parts.append(f"({value['penanda']})")
            value = " ".join(str(part) for part in parts if part)
        if key == "keterkaitan" and isinstance(value, list):
            value = "; ".join(
                f"{item.get('bagian', '')}: {item.get('penjelasan', '')}"
                for item in value
                if isinstance(item, dict)
            )
            if not value.strip("; :"):
                continue
        story.append(Paragraph(pdf_safe_text(label), styles["FieldLabel"]))
        add_pdf_value(story, value, styles)


SECTION_STAGE_EXTRA_PDF_FIELDS = {
    "abstrak": [
        ("pemeriksaan_unsur", "Pemeriksaan Unsur Abstrak"),
        ("ketidaksesuaian_dengan_artikel", "Ketidaksesuaian dengan Artikel"),
    ],
    "pendahuluan": [
        ("peta_fungsi_paragraf", "Peta Fungsi Paragraf"),
        ("evaluasi_gap_penelitian", "Evaluasi Gap Penelitian"),
        ("evaluasi_tujuan_dan_rumusan_masalah", "Evaluasi Tujuan dan Rumusan Masalah"),
    ],
    "metodologi": [
        ("pemeriksaan_komponen", "Pemeriksaan Komponen Metodologi"),
        ("kesesuaian_metode_dengan_tujuan", "Kesesuaian Metode dengan Tujuan"),
    ],
    "hasil_pembahasan": [
        ("interpretasi_tabel", "Interpretasi Tabel"),
        ("analisis_tema", "Analisis Tema (Kualitatif)"),
        ("analisis_pembahasan_per_paragraf", "Analisis Pembahasan per Paragraf"),
        ("versi_revisi_hasil", "Versi Revisi Hasil"),
        ("versi_revisi_pembahasan", "Versi Revisi Pembahasan"),
    ],
    "kesimpulan": [
        ("matriks_klaim", "Matriks Klaim Kesimpulan"),
    ],
    "konsistensi": [
        ("matriks_keselarasan", "Matriks Keselarasan Lintas Bagian"),
        ("statistik_sitasi", "Statistik Sitasi (Deterministik)"),
    ],
}

PDF_ANALYSIS_STAGES = [
    ("profil_artikel", "Profil Artikel"),
    ("judul", "Judul"),
    ("abstrak", "Abstrak"),
    ("pendahuluan", "Pendahuluan"),
    ("metodologi", "Metodologi"),
    ("hasil_pembahasan", "Hasil dan Pembahasan"),
    ("kesimpulan", "Kesimpulan"),
    ("konsistensi", "Konsistensi Lintas Bagian"),
    ("sitasi_apa", "Sitasi dan Daftar Pustaka"),
    ("referensi_tambahan", "Rekomendasi Referensi Tambahan"),
]


def add_stage_to_pdf(story, stage_key, stage_data, styles, mode="mendalam"):
    if not isinstance(stage_data, dict) or not stage_data:
        story.append(Paragraph("Belum ada hasil.", styles["BodyText"]))
        return

    if stage_key == "profil_artikel":
        add_pdf_value(story, stage_data.get("klasifikasi_artikel", stage_data), styles)
        return

    if stage_key == "judul":
        for key, label in [
            ("judul_awal", "Judul Awal"),
            ("evaluasi_judul", "Evaluasi Judul"),
            ("alternatif_judul", "Alternatif Judul"),
            ("judul_rekomendasi", "Judul Rekomendasi"),
            ("skor", "Skor"),
        ]:
            if stage_data.get(key) not in (None, "", []):
                story.append(Paragraph(pdf_safe_text(label), styles["FieldTitle"]))
                add_pdf_value(story, stage_data[key], styles)
        for finding in stage_data.get("masalah_teridentifikasi", []):
            add_finding_to_pdf(story, finding, styles, mode)
        return

    if stage_key == "sitasi_apa":
        matching = citation_groups_for_display(stage_data)
        for key, label in [
            ("statistik", "Statistik Pencocokan"),
            ("sitasi_tanpa_referensi", "Sitasi Tanpa Referensi"),
            ("tahun_tidak_cocok", "Tahun Tidak Cocok"),
            ("kemungkinan_cocok", "Kemungkinan Cocok (Perlu Verifikasi)"),
            ("referensi_tidak_pernah_disitasi", "Referensi Tidak Pernah Disitasi"),
            ("referensi_duplikat", "Referensi Duplikat"),
            ("referensi_tidak_lengkap", "Referensi Tidak Lengkap"),
            ("sitasi_sekunder", "Kemungkinan Sitasi Sekunder"),
            ("referensi_bermasalah", "Referensi Bermasalah (Hasil Lama)"),
        ]:
            story.append(Paragraph(pdf_safe_text(label), styles["FieldTitle"]))
            add_pdf_value(story, matching.get(key, []), styles)
        if matching.get("catatan_akhir_sitasi"):
            story.append(Paragraph("Catatan Akhir Sitasi", styles["FieldTitle"]))
            add_pdf_value(story, matching["catatan_akhir_sitasi"], styles)
        evaluation = stage_data.get("evaluasi_ai") or {}
        if evaluation:
            story.append(Paragraph("Evaluasi Kualitas Referensi (AI)", styles["FieldTitle"]))
            add_pdf_value(story, evaluation, styles)
        return

    if stage_key == "referensi_tambahan":
        visible_keys = [
            "judul", "penulis", "tahun", "jurnal", "quartile_atau_sinta",
            "doi", "kategori", "alasan_relevan", "apa_7",
        ]
        story.append(Paragraph("Referensi Tambahan yang Direkomendasikan", styles["FieldTitle"]))
        add_pdf_value(
            story,
            [
                {key: reference.get(key, "") for key in visible_keys}
                for reference in stage_data.get("rekomendasi", [])
            ],
            styles,
        )
        story.append(Paragraph("Referensi Terpilih (APA 7)", styles["FieldTitle"]))
        add_pdf_value(
            story,
            [ref.get("apa_7", "") for ref in stage_data.get("referensi_dipilih", [])],
            styles,
        )
        return

    # Tahap analisis bagian dengan skema baku.
    for key, label in [
        ("ringkasan", "Ringkasan"),
        ("skor", "Skor"),
        ("status_kesiapan", "Status Kesiapan"),
        ("jumlah_masalah", "Jumlah Masalah"),
        ("prioritas_revisi", "Prioritas Revisi"),
    ]:
        if stage_data.get(key) not in (None, "", [], {}):
            story.append(Paragraph(pdf_safe_text(label), styles["FieldTitle"]))
            add_pdf_value(story, stage_data[key], styles)

    findings = stage_data.get("masalah_teridentifikasi", [])
    if findings:
        story.append(Paragraph("Daftar Masalah", styles["FieldTitle"]))
        for finding in findings:
            add_finding_to_pdf(story, finding, styles, mode)

    extra_fields = [] if mode == "ringkas" else SECTION_STAGE_EXTRA_PDF_FIELDS.get(stage_key, [])
    for key, label in extra_fields:
        if stage_data.get(key) not in (None, "", [], {}):
            story.append(Paragraph(pdf_safe_text(label), styles["FieldTitle"]))
            add_pdf_value(story, stage_data[key], styles)

    revision = stage_data.get("versi_revisi") or stage_data.get(
        _LEGACY_REVISION_FIELDS.get(stage_key, "")
    )
    if revision:
        story.append(Paragraph("Versi Revisi Utuh", styles["FieldTitle"]))
        add_pdf_value(story, revision, styles)

    if stage_data.get("catatan_data_yang_harus_dilengkapi"):
        story.append(
            Paragraph("Data yang Masih Harus Dilengkapi Penulis", styles["FieldTitle"])
        )
        add_pdf_value(story, stage_data["catatan_data_yang_harus_dilengkapi"], styles)

    if mode != "ringkas" and stage_data.get("masalah_dikecualikan"):
        story.append(
            Paragraph("Kriteria yang Tidak Diterapkan (Tidak Relevan)", styles["FieldTitle"])
        )
        for finding in stage_data["masalah_dikecualikan"]:
            add_finding_to_pdf(story, finding, styles, mode)


def draw_pdf_page(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D9E2E8"))
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#627085"))
    canvas.drawString(20 * mm, 10 * mm, "Laporan Hasil Reviu Artikel Ilmiah")
    canvas.drawRightString(190 * mm, 10 * mm, f"Halaman {document.page}")
    canvas.restoreState()


def build_review_pdf(result, pdf_path):
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0F5147"),
            fontSize=20,
            leading=25,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportMeta",
            parent=styles["Normal"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#627085"),
            fontSize=9,
            leading=13,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ModuleTitle",
            parent=styles["Heading1"],
            textColor=colors.HexColor("#146C5D"),
            fontSize=16,
            leading=20,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="FieldTitle",
            parent=styles["Heading2"],
            textColor=colors.HexColor("#233142"),
            fontSize=11,
            leading=14,
            spaceBefore=9,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="FieldLabel",
            parent=styles["Normal"],
            textColor=colors.HexColor("#0F5147"),
            fontSize=9,
            leading=12,
            leftIndent=6 * mm,
            spaceBefore=5,
            spaceAfter=2,
            fontName="Helvetica-Bold",
        )
    )
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13
    styles["BodyText"].spaceAfter = 6
    styles.add(
        ParagraphStyle(
            name="ReviewBullet",
            parent=styles["BodyText"],
            leftIndent=7 * mm,
            firstLineIndent=-4 * mm,
            bulletIndent=2 * mm,
        )
    )

    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=22 * mm,
        title="Laporan Hasil Reviu Artikel Ilmiah",
        author="Aplikasi Reviu Artikel Ilmiah AI",
    )
    filename = result.get("_filename", "Artikel ilmiah")
    created_at = result.get("_created_at", "")
    type_context = article_type_context(result)
    mode = analysis_mode(result)
    story = [
        Spacer(1, 12 * mm),
        Paragraph("Laporan Hasil Reviu Artikel Ilmiah", styles["ReportTitle"]),
        Paragraph(pdf_safe_text(filename), styles["ReportMeta"]),
        Paragraph(
            pdf_safe_text(f"Dibuat: {created_at}" if created_at else "Hasil akhir analisis"),
            styles["ReportMeta"],
        ),
        Paragraph(
            pdf_safe_text(
                f"Jenis artikel: {type_context['label']} (sumber: {type_context['sumber']})"
            ),
            styles["ReportMeta"],
        ),
        Paragraph(
            pdf_safe_text(f"Mode analisis: {ANALYSIS_MODE_LABELS[mode]}"),
            styles["ReportMeta"],
        ),
        Spacer(1, 12 * mm),
    ]

    for section_index, (stage_key, title) in enumerate(PDF_ANALYSIS_STAGES):
        if section_index:
            story.append(Spacer(1, 6 * mm))
        story.append(
            Paragraph(f"{section_index + 1}. {pdf_safe_text(title)}", styles["ModuleTitle"])
        )
        add_stage_to_pdf(story, stage_key, result.get(stage_key, {}), styles, mode)

    document.build(story, onFirstPage=draw_pdf_page, onLaterPages=draw_pdf_page)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not re.fullmatch(r"[a-z0-9@._-]{3,80}", username):
            flash("Username minimal 3 karakter dan hanya boleh huruf, angka, @ . _ -")
        elif len(password) < 8:
            flash("Password minimal 8 karakter.")
        elif password != confirm:
            flash("Konfirmasi password tidak sama.")
        elif find_user_row(username) is not None:
            flash("Username sudah terdaftar. Silakan login.")
        else:
            with get_db() as connection:
                connection.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (
                        username,
                        generate_password_hash(password),
                        datetime.now().isoformat(),
                    ),
                )
            flash("Akun berhasil dibuat. Silakan login.")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        row = find_user_row(username)
        if row is None or not check_password_hash(row["password_hash"], password):
            flash("Username atau password salah.")
        else:
            # Session baru setiap login: tidak ada API key lama yang terbawa.
            session.clear()
            login_user(User(row["id"], row["username"]))
            flash("Login berhasil. Masukkan OpenAI API key Anda untuk memulai sesi analisis.")
            return redirect(url_for("api_key_page"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    clear_session_api_key()
    logout_user()
    session.clear()
    flash("Anda telah logout. API key Anda telah dihapus dari sesi.")
    return redirect(url_for("login"))


@app.route("/api-key", methods=["GET", "POST"])
def api_key_page():
    if request.method == "POST":
        api_key = (request.form.get("api_key") or "").strip()
        if not api_key:
            flash("API key belum diisi.")
        else:
            error_message = validate_api_key(api_key)
            if error_message:
                flash(error_message)
            else:
                session[API_KEY_SESSION_FIELD] = api_key
                flash("API key valid dan disimpan untuk sesi ini.")
                return redirect(url_for("index"))
        return render_template("api_key.html", has_api_key=bool(get_session_api_key()))

    return render_template("api_key.html", has_api_key=bool(get_session_api_key()))


@app.route("/api-key/delete", methods=["POST"])
def delete_api_key():
    clear_session_api_key()
    flash("API key telah dihapus dari sesi. Masukkan kembali untuk melanjutkan analisis.")
    return redirect(url_for("api_key_page"))


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        workflow_steps=get_workflow_steps(),
    )


@app.route("/test-ai", methods=["POST"])
def test_ai():
    try:
        reply = test_openai_connection()
        flash(f"✅ Koneksi OpenAI berhasil dengan model {get_model_name()}.\nBalasan model: {reply}")
    except Exception as exc:
        flash(f"Tes koneksi AI gagal: {safe_error_message(exc)}")

    return redirect(url_for("index"))


@app.route("/download-review/<output_name>", methods=["GET"])
def download_review(output_name):
    safe_output_name = secure_filename(output_name)
    result = load_result(safe_output_name)
    if not result:
        flash("Hasil reviu tidak ditemukan.")
        return redirect(url_for("index"))

    if not is_review_complete(result):
        flash("PDF hanya dapat diunduh setelah semua tahap analisis selesai.")
        return redirect(url_for("index"))

    pdf_name = f"{Path(safe_output_name).stem}.pdf"
    pdf_path = user_output_dir() / pdf_name
    build_review_pdf(result, pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name=pdf_name)


@app.route("/delete-review/<output_name>", methods=["POST"])
def delete_review(output_name):
    safe_output_name = secure_filename(output_name)
    result = load_result(safe_output_name)
    if not result:
        flash("Hasil reviu tidak ditemukan atau sudah dihapus.")
        return redirect(url_for("index"))

    output_path = user_output_dir() / safe_output_name
    pdf_path = user_output_dir() / f"{Path(safe_output_name).stem}.pdf"
    uploaded_name = secure_filename(result.get("_filename", ""))

    output_path.unlink(missing_ok=True)
    pdf_path.unlink(missing_ok=True)
    if uploaded_name and not uploaded_file_is_used_elsewhere(uploaded_name, safe_output_name):
        uploaded_path = user_upload_dir() / uploaded_name
        uploaded_path.unlink(missing_ok=True)

    flash("Hasil reviu dan file terkait berhasil dihapus.")
    return redirect(url_for("index"))


@app.route("/analyze", methods=["POST"])
def analyze():
    uploaded_file = request.files.get("article")

    if not uploaded_file or uploaded_file.filename == "":
        flash("Silakan pilih file artikel .docx terlebih dahulu.")
        return redirect(url_for("index"))

    if not allowed_file(uploaded_file.filename):
        flash("Format file harus .docx.")
        return redirect(url_for("index"))

    filename = secure_filename(uploaded_file.filename)
    saved_path = user_upload_dir() / filename
    uploaded_file.save(saved_path)

    try:
        structure = extract_article_structure(saved_path)
        if not structure["full_text"].strip():
            flash("Teks artikel tidak ditemukan di file .docx.")
            return redirect(url_for("index"))

        heuristic_profile = detect_article_profile(structure)
        chosen_mode = (request.form.get("mode_analisis") or DEFAULT_ANALYSIS_MODE).strip().lower()
        if chosen_mode not in ANALYSIS_MODES:
            chosen_mode = DEFAULT_ANALYSIS_MODE
        result = {
            "_uploaded": True,
            "_filename": filename,
            "_created_at": datetime.now().isoformat(),
            "_profil_heuristik": heuristic_profile,
            "_jenis_artikel_pilihan": "otomatis",
            "_mode_analisis": chosen_mode,
        }
        output_name = save_result(filename, result)
        flash(
            f"Mode analisis: {ANALYSIS_MODE_LABELS[chosen_mode]}. "
            "Jenis artikel terdeteksi (heuristik): "
            f"{article_type_label(heuristic_profile.get('jenis_artikel'))} "
            f"(keyakinan {heuristic_profile.get('tingkat_keyakinan', 'rendah')}). "
            "Anda dapat mengubahnya melalui pilihan \"Ubah Jenis Artikel\"."
        )
    except Exception as exc:
        flash(safe_error_message(exc))
        return redirect(url_for("index"))

    return render_template("result.html", **result_template_context(filename, output_name, result))


def run_stage_route(module_key):
    """Alur bersama seluruh tahap analisis: muat file, jaga urutan, jalankan handler."""
    filename = secure_filename(request.form.get("filename", ""))
    output_name = secure_filename(request.form.get("output_name", ""))
    saved_path = user_upload_dir() / filename

    if not filename or not saved_path.exists():
        flash("File artikel tidak ditemukan. Silakan unggah artikel kembali.")
        return redirect(url_for("index"))

    result = load_result(output_name) if output_name else None
    if result is None:
        flash("Hasil analisis awal tidak ditemukan. Silakan analisis artikel dari awal.")
        return redirect(url_for("index"))
    if not guard_module_order(result, module_key):
        return render_template(
            "result.html", **result_template_context(filename, output_name, result)
        )

    try:
        structure = extract_article_structure(saved_path)
        handler = STAGE_HANDLERS[module_key]
        result[module_key] = handler(structure, result)
        update_result(output_name, result)
    except Exception as exc:
        flash(safe_error_message(exc))

    return render_template(
        "result.html", **result_template_context(filename, output_name, result)
    )


@app.route("/analyze-profile", methods=["POST"])
def analyze_profile():
    return run_stage_route("profil_artikel")


@app.route("/analyze-title", methods=["POST"])
def analyze_title():
    return run_stage_route("judul")


@app.route("/analyze-abstract", methods=["POST"])
def analyze_abstract():
    return run_stage_route("abstrak")


@app.route("/analyze-introduction", methods=["POST"])
def analyze_introduction():
    return run_stage_route("pendahuluan")


@app.route("/analyze-methodology", methods=["POST"])
def analyze_methodology():
    return run_stage_route("metodologi")


@app.route("/analyze-results-discussion", methods=["POST"])
def analyze_results_discussion():
    return run_stage_route("hasil_pembahasan")


@app.route("/analyze-conclusion", methods=["POST"])
def analyze_conclusion():
    return run_stage_route("kesimpulan")


@app.route("/analyze-cross-section", methods=["POST"])
def analyze_cross_section():
    return run_stage_route("konsistensi")


@app.route("/analyze-reference-citation", methods=["POST"])
def analyze_reference_citation():
    return run_stage_route("sitasi_apa")


@app.route("/set-article-type", methods=["POST"])
def set_article_type():
    filename = secure_filename(request.form.get("filename", ""))
    output_name = secure_filename(request.form.get("output_name", ""))
    choice = (request.form.get("jenis_artikel") or "otomatis").strip()

    result = load_result(output_name) if output_name else None
    if result is None:
        flash("Hasil analisis tidak ditemukan.")
        return redirect(url_for("index"))

    if choice not in ARTICLE_TYPE_LABELS:
        flash("Pilihan jenis artikel tidak dikenali.")
    else:
        # Koreksi pengguna terhadap deteksi otomatis; bukti teks deteksi tetap disimpan.
        result["_jenis_artikel_pilihan"] = choice
        update_result(output_name, result)
        if choice == "otomatis":
            flash("Jenis artikel dikembalikan ke deteksi otomatis.")
        else:
            flash(
                f"Jenis artikel diubah menjadi: {ARTICLE_TYPE_LABELS[choice]}. "
                "Analisis berikutnya akan memakai kriteria jenis ini."
            )

    return render_template(
        "result.html", **result_template_context(filename, output_name, result)
    )


@app.route("/analyze-reference-recommendations", methods=["POST"])
def analyze_reference_recommendations():
    filename = secure_filename(request.form.get("filename", ""))
    output_name = secure_filename(request.form.get("output_name", ""))
    saved_path = user_upload_dir() / filename

    if not filename or not saved_path.exists():
        flash("File artikel tidak ditemukan. Silakan unggah artikel kembali.")
        return redirect(url_for("index"))

    result = load_result(output_name) if output_name else None
    if result is None:
        flash("Hasil revisi tidak ditemukan. Silakan mulai kembali.")
        return redirect(url_for("index"))
    if not guard_module_order(result, "referensi_tambahan"):
        return render_template("result.html", **result_template_context(filename, output_name, result))

    try:
        structure = extract_article_structure(saved_path)
        reference_section = get_section(structure, "daftar_pustaka")
        recommendation_result = find_verified_reference_recommendations(result, structure)
        recommendation_result["referensi_asli"] = (reference_section or {}).get("text", "")
        result["referensi_tambahan"] = recommendation_result
        update_result(output_name, result)
    except Exception as exc:
        flash(f"Pencarian referensi gagal: {safe_error_message(exc)}")

    return render_template("result.html", **result_template_context(filename, output_name, result))


@app.route("/add-recommended-reference", methods=["POST"])
def add_recommended_reference():
    filename = secure_filename(request.form.get("filename", ""))
    output_name = secure_filename(request.form.get("output_name", ""))
    doi = normalize_doi(request.form.get("doi", ""))
    result = load_result(output_name) if output_name else None

    if result is None or not result.get("referensi_tambahan"):
        flash("Hasil rekomendasi referensi tidak ditemukan.")
        return redirect(url_for("index"))

    recommendations = result["referensi_tambahan"].get("rekomendasi", [])
    selected_reference = next(
        (item for item in recommendations if normalize_doi(item.get("doi")) == doi),
        None,
    )
    if selected_reference is None:
        flash("Referensi tidak valid atau tidak berasal dari hasil pencarian.")
    else:
        selected = result["referensi_tambahan"].setdefault("referensi_dipilih", [])
        if not any(normalize_doi(item.get("doi")) == doi for item in selected):
            selected.append(selected_reference)
            update_result(output_name, result)
            flash("Referensi berhasil ditambahkan ke daftar pustaka pilihan.")
        else:
            flash("Referensi tersebut sudah ditambahkan.")

    return render_template(
        "result.html",
        **result_template_context(filename, output_name, result),
    )



if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=not IS_PRODUCTION,
    )
