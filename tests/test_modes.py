"""Pengujian dua mode analisis: ringkas (default) dan mendalam."""

import json

from flask import render_template

import app as app_module
import prompts
from analysis_schema import (
    NO_MAJOR_ISSUES_SUMMARY,
    apply_mode_limits,
    is_cosmetic_minor,
    normalize_section_result,
    resolve_analysis_mode,
)
from conftest import register_and_login, set_valid_api_key
from docx_fixtures import (
    QUANTITATIVE_EXPERIMENT,
    build_docx,
    build_sdt_citation_docx,
)


FAKE_KEY = "sk-test-kunci-palsu-123"


def make_findings(count, priority="mayor", **extra):
    return [
        {
            "id": f"ABS-{i + 1:02d}",
            "prioritas": priority,
            "kutipan_asli": f"Kutipan {i}",
            "masalah": f"Masalah {i}",
            "tindakan_revisi": f"Revisi {i}",
            **extra,
        }
        for i in range(count)
    ]


def normalized(findings):
    return normalize_section_result(
        {"masalah_teridentifikasi": findings}, "ABS", "Abstrak"
    )


# ---------------------------------------------------------------------------
# 1. Default mode ringkas
# ---------------------------------------------------------------------------

def test_upload_defaults_to_ringkas_mode(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    buffer = build_docx(QUANTITATIVE_EXPERIMENT)
    response = client.post(
        "/analyze",
        data={"article": (buffer, "artikel.docx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "Analisis Ringkas".encode() in response.data
    saved = json.loads(
        next(app_module.OUTPUT_DIR.glob("*/artikel-*.json")).read_text(encoding="utf-8")
    )
    assert saved["_mode_analisis"] == "ringkas"


def test_upload_can_choose_mendalam_mode(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    buffer = build_docx(QUANTITATIVE_EXPERIMENT)
    client.post(
        "/analyze",
        data={"article": (buffer, "artikel.docx"), "mode_analisis": "mendalam"},
        content_type="multipart/form-data",
    )
    saved = json.loads(
        next(app_module.OUTPUT_DIR.glob("*/artikel-*.json")).read_text(encoding="utf-8")
    )
    assert saved["_mode_analisis"] == "mendalam"


def test_index_page_offers_mode_choice(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    response = client.get("/")
    assert "Analisis Ringkas".encode() in response.data
    assert "Analisis Mendalam".encode() in response.data
    assert b'value="ringkas" checked' in response.data


# ---------------------------------------------------------------------------
# 2-5. Batas temuan dan filter minor
# ---------------------------------------------------------------------------

def test_ringkas_caps_findings_at_5():
    data = apply_mode_limits(normalized(make_findings(9, "mayor")), "ringkas")
    assert len(data["masalah_teridentifikasi"]) == 5
    assert any(
        "tidak ditampilkan" in note
        for note in data["catatan_data_yang_harus_dilengkapi"]
    )


def test_mendalam_caps_findings_at_8():
    data = apply_mode_limits(normalized(make_findings(12, "mayor")), "mendalam")
    assert len(data["masalah_teridentifikasi"]) == 8


def test_ringkas_drops_all_minor_findings():
    findings = make_findings(2, "kritis") + make_findings(3, "minor")
    data = apply_mode_limits(normalized(findings), "ringkas")
    priorities = [f["prioritas"] for f in data["masalah_teridentifikasi"]]
    assert priorities == ["kritis", "kritis"]


def test_cosmetic_minor_findings_are_dropped_in_mendalam():
    cosmetic = {
        "prioritas": "minor",
        "jenis_masalah": "tata bahasa",
        "masalah": "Ejaan kata 'dilaksanakan' kurang tepat dan ada typo kecil.",
    }
    substantive = {
        "prioritas": "minor",
        "jenis_masalah": "interpretasi data",
        "masalah": "Interpretasi persentase pada paragraf 3 membingungkan pembaca.",
    }
    assert is_cosmetic_minor(cosmetic)
    assert not is_cosmetic_minor(substantive)
    data = apply_mode_limits(normalized([cosmetic, substantive]), "mendalam")
    remaining = [f["masalah"] for f in data["masalah_teridentifikasi"]]
    assert len(remaining) == 1
    assert "Interpretasi" in remaining[0]


def test_critical_and_major_findings_are_kept():
    findings = (
        make_findings(2, "kritis")
        + make_findings(2, "mayor")
        + [
            {
                "prioritas": "minor",
                "jenis_masalah": "gaya bahasa",
                "masalah": "Variasi gaya penulisan.",
            }
        ]
    )
    for mode in ("ringkas", "mendalam"):
        data = apply_mode_limits(normalized(list(findings)), mode)
        priorities = [f["prioritas"] for f in data["masalah_teridentifikasi"]]
        assert priorities.count("kritis") == 2
        assert priorities.count("mayor") == 2
        assert "minor" not in priorities


def test_ringkas_empty_findings_get_default_summary():
    data = apply_mode_limits(normalized([]), "ringkas")
    assert data["masalah_teridentifikasi"] == []
    assert data["ringkasan"] == NO_MAJOR_ISSUES_SUMMARY


# ---------------------------------------------------------------------------
# Prompt sesuai mode
# ---------------------------------------------------------------------------

def test_ringkas_prompt_limits_findings_and_omits_audit_fields():
    prompt = prompts.build_abstract_prompt(
        {"jenis_artikel": "Kuantitatif"},
        "kuantitatif_eksperimen",
        None,
        "konteks",
        mode="ringkas",
    )
    assert "Maksimal 5 temuan" in prompt
    assert "pemeriksaan_unsur" not in prompt
    assert "versi_revisi" not in prompt
    assert "kritis dan mayor" in prompt


def test_mendalam_prompt_limits_findings_and_keeps_detail_fields():
    prompt = prompts.build_abstract_prompt(
        {"jenis_artikel": "Kuantitatif"},
        "kuantitatif_eksperimen",
        None,
        "konteks",
        mode="mendalam",
    )
    assert "Maksimal 8 temuan" in prompt
    assert "pemeriksaan_unsur" in prompt
    assert "contoh_revisi" in prompt


def test_stage_handlers_pass_mode_to_prompts(client, monkeypatch):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    buffer = build_docx(QUANTITATIVE_EXPERIMENT)
    client.post(
        "/analyze",
        data={"article": (buffer, "artikel.docx")},
        content_type="multipart/form-data",
    )
    output_name = next(
        path.name for path in app_module.OUTPUT_DIR.glob("*/artikel-*.json")
    )
    saved_path = next(app_module.OUTPUT_DIR.glob(f"*/{output_name}"))
    result = json.loads(saved_path.read_text(encoding="utf-8"))
    result["profil_artikel"] = {
        "klasifikasi_artikel": {"jenis_artikel": "kuantitatif_eksperimen"}
    }
    result["judul"] = {"judul_rekomendasi": "Judul"}
    saved_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    prompts_seen = []

    def fake_openai_json(system_prompt, user_prompt):
        prompts_seen.append(user_prompt)
        return {"ringkasan": "ok", "masalah_teridentifikasi": []}

    monkeypatch.setattr(app_module, "openai_chat_json", fake_openai_json)
    response = client.post(
        "/analyze-abstract",
        data={"filename": "artikel.docx", "output_name": output_name},
    )
    assert response.status_code == 200
    assert "MODE RINGKAS" in prompts_seen[0]
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["abstrak"]["mode_analisis"] == "ringkas"


# ---------------------------------------------------------------------------
# 6-8. Tampilan sesuai mode, tanpa tabel horizontal
# ---------------------------------------------------------------------------

RICH_FINDING = {
    "id": "ABS-01",
    "prioritas": "mayor",
    "lokasi": {"bagian": "Abstrak", "paragraf": 1, "kalimat": 1, "penanda": "ABS-P01-S01"},
    "kutipan_asli": "Kutipan asli.",
    "jenis_masalah": "ketidaklengkapan",
    "masalah": "Metode belum lengkap.",
    "alasan": "Alasan akademik penting.",
    "dampak": "Pembaca salah memahami metode.",
    "tindakan_revisi": "Lengkapi metode.",
    "contoh_revisi": "Contoh revisi kalimat metode.",
    "status_contoh": "template",
    "keterkaitan": [],
    "keyakinan": "tinggi",
}


def render_result(flask_app, result):
    with flask_app.test_request_context("/"):
        return render_template(
            "result.html",
            **app_module.result_template_context("a.docx", "a.json", result),
        )


def base_result(mode):
    result = {
        "_uploaded": True,
        "_filename": "a.docx",
        "_profil_heuristik": {"jenis_artikel": "kuantitatif_eksperimen"},
        "abstrak": {
            "ringkasan": "Ringkasan tahap.",
            "skor": 80,
            "masalah_teridentifikasi": [dict(RICH_FINDING)],
        },
    }
    if mode:
        result["_mode_analisis"] = mode
    return result


def test_ringkas_display_hides_reason_impact_and_example(flask_app):
    html = render_result(flask_app, base_result("ringkas"))
    assert "Mode: Analisis Ringkas" in html
    assert "Metode belum lengkap." in html
    assert "Lengkapi metode." in html
    assert "Alasan akademik penting." not in html
    assert "Pembaca salah memahami metode." not in html
    assert "Contoh revisi kalimat metode." not in html


def test_mendalam_display_keeps_reason_and_collapsible_example(flask_app):
    html = render_result(flask_app, base_result("mendalam"))
    assert "Mode: Analisis Mendalam" in html
    assert "Alasan akademik penting." in html
    assert "Contoh revisi kalimat metode." in html
    assert "Lihat contoh revisi" in html


def test_result_page_uses_vertical_cards_not_horizontal_tables(flask_app):
    result = base_result("mendalam")
    result["abstrak"]["pemeriksaan_unsur"] = [
        {"unsur": "tujuan", "status": "kurang rinci", "bukti": "-", "catatan": "Perlu dilengkapi."}
    ]
    result["kesimpulan"] = {
        "ringkasan": "Ringkasan kesimpulan.",
        "masalah_teridentifikasi": [],
        "matriks_klaim": [
            {"klaim_kesimpulan": "Klaim A", "status": "tidak didukung", "alasan": "Tidak ada bukti."}
        ],
    }
    html = render_result(flask_app, result)
    assert "<table" not in html
    assert "Perlu dilengkapi." in html
    assert "Klaim A" in html
    assert "record-card" in html


def test_citation_stage_keeps_deterministic_stats_in_both_modes(client, monkeypatch):
    """Regresi: mode analisis tidak boleh memutus data sitasi deterministik.

    Statistik dihitung oleh kode Python sebelum rendering; mode hanya
    memengaruhi penjelasan AI, bukan hasil pencocokan.
    """
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    monkeypatch.setattr(
        app_module,
        "openai_chat_json",
        lambda system, prompt: {"ringkasan_kualitas_referensi": "ok"},
    )
    completed_stages = (
        "profil_artikel",
        "judul",
        "abstrak",
        "pendahuluan",
        "metodologi",
        "hasil_pembahasan",
        "kesimpulan",
        "konsistensi",
    )
    for mode in ("ringkas", "mendalam"):
        filename = f"sdt-{mode}.docx"
        client.post(
            "/analyze",
            data={
                "article": (build_sdt_citation_docx(), filename),
                "mode_analisis": mode,
            },
            content_type="multipart/form-data",
        )
        saved_path = next(app_module.OUTPUT_DIR.glob(f"*/sdt-{mode}-*.json"))
        result = json.loads(saved_path.read_text(encoding="utf-8"))
        for key in completed_stages:
            result[key] = {"ringkasan": "selesai"}
        saved_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

        response = client.post(
            "/analyze-reference-citation",
            data={"filename": filename, "output_name": saved_path.name},
        )
        assert response.status_code == 200
        saved = json.loads(saved_path.read_text(encoding="utf-8"))
        stats = saved["sitasi_apa"]["pencocokan"]["statistik"]
        assert stats["jumlah_sitasi_terdeteksi"] == 2, mode
        assert stats["jumlah_referensi"] == 2, mode
        assert stats["cocok_pasti"] == 2, mode
        assert "Jumlah Sitasi Terdeteksi: 2".encode() in response.data
        assert "Jumlah Referensi: 2".encode() in response.data


# ---------------------------------------------------------------------------
# 9. Kompatibilitas hasil lama
# ---------------------------------------------------------------------------

def test_legacy_result_without_mode_treated_as_mendalam(flask_app):
    assert resolve_analysis_mode(None) == "mendalam"
    assert app_module.analysis_mode({}) == "mendalam"
    html = render_result(flask_app, base_result(None))
    assert "Mode: Analisis Mendalam" in html
    assert "Alasan akademik penting." in html


def test_ringkas_pdf_is_shorter_than_mendalam_pdf(tmp_path):
    ringkas_result = base_result("ringkas")
    mendalam_result = base_result("mendalam")
    mendalam_result["abstrak"]["pemeriksaan_unsur"] = [
        {"unsur": "tujuan", "status": "kurang rinci", "catatan": "Perlu dilengkapi."}
    ]
    ringkas_result["abstrak"]["pemeriksaan_unsur"] = list(
        mendalam_result["abstrak"]["pemeriksaan_unsur"]
    )
    ringkas_pdf = tmp_path / "ringkas.pdf"
    mendalam_pdf = tmp_path / "mendalam.pdf"
    app_module.build_review_pdf(ringkas_result, ringkas_pdf)
    app_module.build_review_pdf(mendalam_result, mendalam_pdf)
    assert ringkas_pdf.exists() and mendalam_pdf.exists()
    assert ringkas_pdf.stat().st_size < mendalam_pdf.stat().st_size
