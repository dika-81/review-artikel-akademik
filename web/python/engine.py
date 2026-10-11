"""Antarmuka mesin reviu untuk worker JavaScript (versi web).

Padanan rute Flask di app.py tanpa login, session, atau file server:
artikel (.docx) dan hasil reviu disimpan di browser oleh JavaScript, lalu
dikirim ke fungsi-fungsi ini. Setiap fungsi menerima dan mengembalikan
string JSON agar mudah dilewatkan antara JavaScript dan Python.

Format balasan: {"ok": true, "result": {...}, "message": "..."} atau
{"ok": false, "error": "pesan untuk pengguna", "result": {...}}.
"""

import hashlib
import io
import json
import os
import tempfile
from datetime import datetime

import app_core as core
import web_runtime
from analysis_schema import ANALYSIS_MODES, DEFAULT_ANALYSIS_MODE
from article_profile import ARTICLE_TYPE_LABELS, article_type_label, detect_article_profile
from article_structure import extract_article_structure, get_section

_structure_cache = {"digest": None, "structure": None}


def _reply(ok, result=None, message="", error="", **extra):
    payload = {"ok": ok, "result": result, "message": message, "error": error}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _structure(docx_bytes):
    # Dari worker, isi file datang sebagai JsProxy Uint8Array.
    data = docx_bytes.to_bytes() if hasattr(docx_bytes, "to_bytes") else bytes(docx_bytes)
    digest = hashlib.sha256(data).hexdigest()
    if _structure_cache["digest"] != digest:
        _structure_cache["structure"] = extract_article_structure(io.BytesIO(data))
        _structure_cache["digest"] = digest
    return _structure_cache["structure"]


def configure(settings_json):
    settings = json.loads(settings_json or "{}")
    web_runtime.configure(
        api_key=settings.get("api_key"),
        model=settings.get("model"),
        max_output_tokens=settings.get("max_output_tokens"),
        timeout_seconds=settings.get("timeout_seconds"),
        scholarly_email=settings.get("scholarly_email"),
    )
    return _reply(True, message="Pengaturan diterapkan.")


def test_connection():
    try:
        reply = web_runtime.test_openai_connection()
    except Exception as exc:
        return _reply(False, error=f"Tes koneksi AI gagal: {web_runtime.safe_error_message(exc)}")
    return _reply(
        True,
        message=(
            f"Koneksi OpenAI berhasil dengan model {web_runtime.get_model_name()}.\n"
            f"Balasan model: {reply}"
        ),
    )


def start_review(docx_bytes, filename, mode=None):
    """Padanan rute /analyze: ekstraksi struktur dan profil heuristik."""
    if not core.allowed_file(filename or ""):
        return _reply(False, error="Format file harus .docx.")
    try:
        structure = _structure(docx_bytes)
    except Exception as exc:
        return _reply(False, error=web_runtime.safe_error_message(exc))
    if not structure["full_text"].strip():
        return _reply(False, error="Teks artikel tidak ditemukan di file .docx.")

    heuristic_profile = detect_article_profile(structure)
    chosen_mode = (mode or DEFAULT_ANALYSIS_MODE).strip().lower()
    if chosen_mode not in ANALYSIS_MODES:
        chosen_mode = DEFAULT_ANALYSIS_MODE
    result = {
        "_uploaded": True,
        "_filename": os.path.basename(filename),
        "_created_at": datetime.now().isoformat(),
        "_profil_heuristik": heuristic_profile,
        "_jenis_artikel_pilihan": "otomatis",
        "_mode_analisis": chosen_mode,
    }
    message = (
        f"Mode analisis: {core.ANALYSIS_MODE_LABELS[chosen_mode]}. "
        "Jenis artikel terdeteksi (heuristik): "
        f"{article_type_label(heuristic_profile.get('jenis_artikel'))} "
        f"(keyakinan {heuristic_profile.get('tingkat_keyakinan', 'rendah')}). "
        "Anda dapat mengubahnya melalui pilihan \"Ubah Jenis Artikel\"."
    )
    return _reply(True, result=result, message=message)


def _guard(result, module_key):
    if core.module_is_unlocked(result, module_key):
        return None
    return "Tombol ini masih terkunci. Jalankan analisis sebelumnya sesuai urutan terlebih dahulu."


def run_stage(docx_bytes, result_json, module_key):
    """Padanan run_stage_route: jalankan satu tahap analisis."""
    result = json.loads(result_json)
    if module_key not in core.STAGE_HANDLERS:
        return _reply(False, result=result, error="Tahap analisis tidak dikenali.")
    locked = _guard(result, module_key)
    if locked:
        return _reply(False, result=result, error=locked)
    try:
        structure = _structure(docx_bytes)
        result[module_key] = core.STAGE_HANDLERS[module_key](structure, result)
    except Exception as exc:
        return _reply(False, result=result, error=web_runtime.safe_error_message(exc))
    return _reply(True, result=result)


def run_reference_recommendations(docx_bytes, result_json):
    result = json.loads(result_json)
    locked = _guard(result, "referensi_tambahan")
    if locked:
        return _reply(False, result=result, error=locked)
    try:
        structure = _structure(docx_bytes)
        reference_section = get_section(structure, "daftar_pustaka")
        recommendation = core.find_verified_reference_recommendations(result, structure)
        recommendation["referensi_asli"] = (reference_section or {}).get("text", "")
        result["referensi_tambahan"] = recommendation
    except Exception as exc:
        return _reply(
            False,
            result=result,
            error=f"Pencarian referensi gagal: {web_runtime.safe_error_message(exc)}",
        )
    return _reply(True, result=result)


def add_recommended_reference(result_json, doi):
    result = json.loads(result_json)
    doi = core.normalize_doi(doi)
    if not result.get("referensi_tambahan"):
        return _reply(False, result=result, error="Hasil rekomendasi referensi tidak ditemukan.")
    recommendations = result["referensi_tambahan"].get("rekomendasi", [])
    selected_reference = next(
        (item for item in recommendations if core.normalize_doi(item.get("doi")) == doi),
        None,
    )
    if selected_reference is None:
        return _reply(
            False, result=result,
            error="Referensi tidak valid atau tidak berasal dari hasil pencarian.",
        )
    selected = result["referensi_tambahan"].setdefault("referensi_dipilih", [])
    if any(core.normalize_doi(item.get("doi")) == doi for item in selected):
        return _reply(True, result=result, message="Referensi tersebut sudah ditambahkan.")
    selected.append(selected_reference)
    return _reply(
        True, result=result, message="Referensi berhasil ditambahkan ke daftar pustaka pilihan."
    )


def set_article_type(result_json, choice):
    result = json.loads(result_json)
    choice = (choice or "otomatis").strip()
    if choice not in ARTICLE_TYPE_LABELS:
        return _reply(False, result=result, error="Pilihan jenis artikel tidak dikenali.")
    # Koreksi pengguna terhadap deteksi otomatis; bukti teks deteksi tetap disimpan.
    result["_jenis_artikel_pilihan"] = choice
    if choice == "otomatis":
        message = "Jenis artikel dikembalikan ke deteksi otomatis."
    else:
        message = (
            f"Jenis artikel diubah menjadi: {ARTICLE_TYPE_LABELS[choice]}. "
            "Analisis berikutnya akan memakai kriteria jenis ini."
        )
    return _reply(True, result=result, message=message)


def view_context(result_json):
    """Data turunan untuk tampilan hasil (padanan result_template_context)."""
    result = json.loads(result_json)
    mode = core.analysis_mode(result)
    context = {
        "review_complete": core.is_review_complete(result),
        "workflow_steps": core.get_workflow_steps(result),
        "article_type": core.article_type_context(result),
        "citation_groups": core.citation_groups_for_display(result.get("sitasi_apa")),
        "analysis_mode": mode,
        "analysis_mode_label": core.ANALYSIS_MODE_LABELS[mode],
        "pdf_available": core.PDF_AVAILABLE,
    }
    return _reply(True, result=result, context=context)


def build_pdf(result_json):
    """Kembalikan isi PDF (bytes); melempar RuntimeError bila tidak bisa dibuat."""
    result = json.loads(result_json)
    if not core.PDF_AVAILABLE:
        raise RuntimeError("Pembuat PDF belum tersedia di browser ini.")
    if not core.is_review_complete(result):
        raise RuntimeError("PDF hanya dapat diunduh setelah semua tahap analisis selesai.")
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "reviu.pdf")
        core.build_review_pdf(result, path)
        with open(path, "rb") as handle:
            return handle.read()
