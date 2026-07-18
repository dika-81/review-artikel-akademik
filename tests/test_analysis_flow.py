"""Pengujian alur analisis dengan mock OpenAI: schema, validasi bukti, robustness."""

import json

import pytest

import app as app_module
from flask import render_template
from analysis_schema import (
    ModelJSONError,
    normalize_section_result,
    parse_model_json,
)
from article_structure import extract_article_structure
from conftest import register_and_login, set_valid_api_key
from docx_fixtures import QUANTITATIVE_EXPERIMENT, build_docx


FAKE_KEY = "sk-test-kunci-palsu-123"


# ---------------------------------------------------------------------------
# Parsing dan normalisasi JSON model
# ---------------------------------------------------------------------------

def test_parse_model_json_with_code_fence_and_trailing_comma():
    content = '```json\n{"ringkasan": "ok", "skor": 80,}\n```'
    assert parse_model_json(content)["skor"] == 80


def test_parse_model_json_with_surrounding_text():
    content = 'Berikut hasilnya:\n{"ringkasan": "ok"}\nSemoga membantu.'
    assert parse_model_json(content)["ringkasan"] == "ok"


def test_parse_model_json_invalid_raises():
    with pytest.raises(ModelJSONError):
        parse_model_json("bukan json sama sekali")


def test_normalize_section_result_defaults_and_sorting():
    data = {
        "ringkasan": "tes",
        "skor": "85",
        "masalah_teridentifikasi": [
            {"prioritas": "minor", "masalah": "kecil"},
            {"prioritas": "kritis", "masalah": "besar"},
            "masalah berupa string",
        ],
    }
    result = normalize_section_result(data, "ABS", "Abstrak")
    findings = result["masalah_teridentifikasi"]
    assert findings[0]["prioritas"] == "kritis"
    assert result["jumlah_masalah"] == {"kritis": 1, "mayor": 0, "minor": 2}
    assert result["skor"] == 85
    assert findings[0]["id"].startswith("ABS-")
    assert result["prioritas_revisi"], "prioritas revisi diturunkan dari temuan kritis/mayor"


def test_normalize_section_result_caps_findings_at_15():
    data = {
        "masalah_teridentifikasi": [
            {"prioritas": "minor", "masalah": f"masalah {i}"} for i in range(20)
        ]
    }
    result = normalize_section_result(data, "MET", "Metodologi")
    assert len(result["masalah_teridentifikasi"]) == 15
    assert len(result["masalah_tambahan_ringkas"]) == 5
    assert any("melebihi" in note for note in result["catatan_data_yang_harus_dilengkapi"])


def test_normalize_section_result_never_hides_critical_or_major_findings():
    data = {
        "masalah_teridentifikasi": [
            {"prioritas": "kritis", "masalah": f"masalah penting {i}"}
            for i in range(18)
        ]
        + [
            {"prioritas": "minor", "masalah": f"masalah minor {i}"}
            for i in range(3)
        ]
    }
    result = normalize_section_result(data, "MET", "Metodologi")
    findings = result["masalah_teridentifikasi"]
    assert len(findings) == 18
    assert all(finding["prioritas"] == "kritis" for finding in findings)
    assert len(result["masalah_tambahan_ringkas"]) == 3
    assert any(
        "seluruhnya tetap dipertahankan" in note
        for note in result["catatan_data_yang_harus_dilengkapi"]
    )


# ---------------------------------------------------------------------------
# Pemanggilan model: JSON rusak, keluaran terpotong
# ---------------------------------------------------------------------------

def test_openai_chat_json_repairs_broken_json_once(monkeypatch):
    calls = []

    def fake_call(system_prompt, user_prompt, force_json=False):
        calls.append(system_prompt)
        if len(calls) == 1:
            return "hasil analisis: {tidak valid}"
        return '{"ringkasan": "diperbaiki"}'

    monkeypatch.setattr(app_module, "call_openai_chat", fake_call)
    data = app_module.openai_chat_json("sys", "user")
    assert data["ringkasan"] == "diperbaiki"
    assert len(calls) == 2


def test_openai_chat_json_unrepairable_raises_clear_error(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "call_openai_chat",
        lambda *args, **kwargs: "tetap bukan json",
    )
    with pytest.raises(RuntimeError) as excinfo:
        app_module.openai_chat_json("sys", "user")
    assert "JSON valid" in str(excinfo.value)


def test_truncated_output_raises_explicit_message(client, monkeypatch):
    class FakeIncomplete:
        reason = "max_output_tokens"

    class FakeResponse:
        status = "incomplete"
        incomplete_details = FakeIncomplete()
        output_text = '{"sebagian": true'

    class FakeResponses:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    monkeypatch.setattr(app_module, "build_user_client", lambda key: FakeClient())
    monkeypatch.setattr(app_module, "get_session_api_key", lambda: FAKE_KEY)
    with pytest.raises(RuntimeError) as excinfo:
        app_module.call_openai_chat("sys", "user", force_json=True)
    assert "terpotong" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Alur tahap dengan mock model
# ---------------------------------------------------------------------------

def upload_article(client, tmp_path):
    buffer = build_docx(QUANTITATIVE_EXPERIMENT)
    response = client.post(
        "/analyze",
        data={"article": (buffer, "artikel.docx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    output_name = next(
        path.name for path in app_module.OUTPUT_DIR.glob("*/artikel-*.json")
    )
    return output_name


def test_upload_shows_detected_article_type(client, monkeypatch, tmp_path):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    buffer = build_docx(QUANTITATIVE_EXPERIMENT)
    response = client.post(
        "/analyze",
        data={"article": (buffer, "artikel.docx")},
        content_type="multipart/form-data",
    )
    assert "Jenis artikel terdeteksi".encode() in response.data
    assert "Ubah Jenis Artikel".encode() in response.data
    assert "Kuantitatif".encode() in response.data


def test_user_can_override_article_type(client, monkeypatch, tmp_path):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    output_name = upload_article(client, tmp_path)

    response = client.post(
        "/set-article-type",
        data={
            "filename": "artikel.docx",
            "output_name": output_name,
            "jenis_artikel": "ptk",
        },
    )
    assert "Penelitian Tindakan Kelas".encode() in response.data
    saved = json.loads(
        next(app_module.OUTPUT_DIR.glob(f"*/{output_name}")).read_text(encoding="utf-8")
    )
    assert saved["_jenis_artikel_pilihan"] == "ptk"
    # Bukti deteksi heuristik tidak dihapus oleh koreksi pengguna.
    assert saved["_profil_heuristik"]["jenis_artikel"] == "kuantitatif_eksperimen"


def test_abstract_stage_validates_quotes_and_keeps_real_ones(client, monkeypatch, tmp_path):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    output_name = upload_article(client, tmp_path)

    fake_analysis = {
        "ringkasan": "Abstrak belum mencerminkan seluruh instrumen.",
        "skor": 70,
        "status_kesiapan": "perlu revisi mayor",
        "masalah_teridentifikasi": [
            {
                "id": "ABS-01",
                "prioritas": "mayor",
                "lokasi": {"bagian": "Abstrak", "paragraf": 1, "kalimat": 2, "penanda": "ABS-P01-S02"},
                "kutipan_asli": "Data dikumpulkan melalui angket.",
                "jenis_masalah": "ketidaklengkapan metode",
                "masalah": "Abstrak hanya menyebut angket, padahal metodologi menyebut tiga instrumen.",
                "alasan": "Abstrak harus mewakili metode.",
                "dampak": "Pembaca memperoleh gambaran metode yang tidak lengkap.",
                "tindakan_revisi": "Sebutkan seluruh instrumen.",
                "contoh_revisi": "Data dikumpulkan melalui tes pemahaman konsep, lembar observasi, dan angket respons.",
                "status_contoh": "dapat digunakan",
                "keterkaitan": [{"bagian": "Metodologi", "penjelasan": "Metodologi menyebut tiga instrumen."}],
                "keyakinan": "tinggi",
            },
            {
                "id": "ABS-02",
                "prioritas": "kritis",
                "kutipan_asli": "Kalimat karangan yang tidak ada di artikel sama sekali dan sangat panjang sekali.",
                "masalah": "Temuan dengan kutipan palsu.",
            },
        ],
        "pemeriksaan_unsur": [
            {"unsur": "tujuan", "status": "ada", "bukti": "Penelitian ini bertujuan", "catatan": ""}
        ],
        "versi_revisi": "Versi abstrak revisi.",
        "catatan_data_yang_harus_dilengkapi": [],
    }
    monkeypatch.setattr(
        app_module, "openai_chat_json", lambda system, prompt: dict(fake_analysis)
    )
    # Lewati tahap profil dan judul agar abstrak terbuka.
    saved_path = next(app_module.OUTPUT_DIR.glob(f"*/{output_name}"))
    result = json.loads(saved_path.read_text(encoding="utf-8"))
    result["profil_artikel"] = {"klasifikasi_artikel": {"jenis_artikel": "kuantitatif_eksperimen"}}
    result["judul"] = {"judul_rekomendasi": "Judul"}
    saved_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    response = client.post(
        "/analyze-abstract",
        data={"filename": "artikel.docx", "output_name": output_name},
    )
    assert response.status_code == 200
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    findings = saved["abstrak"]["masalah_teridentifikasi"]
    by_id = {f["id"]: f for f in findings}
    assert by_id["ABS-01"]["kutipan_valid"] is True
    assert by_id["ABS-01"]["validasi_kutipan"] == "terverifikasi"
    # Nomor paragraf sesuai hasil ekstraksi (lokasi terverifikasi ditambahkan sistem).
    assert by_id["ABS-01"]["lokasi_terverifikasi"]["bagian"] == "Abstrak"
    assert by_id["ABS-01"]["lokasi_terverifikasi"]["paragraf"] == 1
    # Keterkaitan abstrak <-> metodologi dipertahankan.
    assert by_id["ABS-01"]["keterkaitan"][0]["bagian"] == "Metodologi"
    # Kutipan palsu ditandai tidak valid, bukan ditampilkan sebagai bukti benar.
    assert by_id["ABS-02"]["kutipan_valid"] is False
    assert by_id["ABS-02"]["validasi_kutipan"] == "tidak_ditemukan"
    # Badge tampil di halaman hasil.
    assert "Perlu verifikasi".encode() in response.data
    assert "Kutipan terverifikasi".encode() in response.data


def test_abstract_prompt_contains_methodology_context(tmp_path):
    path = build_docx(QUANTITATIVE_EXPERIMENT, path=tmp_path / "artikel.docx")
    structure = extract_article_structure(path)
    context = app_module._abstract_context(structure)
    assert "kuasi eksperimen" in context
    assert "Metodologi" in context
    assert "[MET-P01-S01]" in context


def test_conclusion_prompt_contains_results_context(tmp_path):
    import prompts

    path = build_docx(QUANTITATIVE_EXPERIMENT, path=tmp_path / "artikel.docx")
    structure = extract_article_structure(path)
    from article_structure import format_section_for_prompt, get_section

    prompt = prompts.build_conclusion_prompt(
        {"jenis_artikel": "Kuantitatif"},
        "kuantitatif_eksperimen",
        format_section_for_prompt(get_section(structure, "kesimpulan")),
        f"Hasil:\n{get_section(structure, 'hasil_pembahasan')['text']}",
    )
    assert "matriks_klaim" in prompt
    assert "82,4" in prompt  # klaim kesimpulan dapat dibandingkan dengan hasil


def test_results_prompt_links_tables(tmp_path):
    import prompts

    path = build_docx(
        QUANTITATIVE_EXPERIMENT,
        tables=[[["Kelas", "Rata-rata"], ["Eksperimen", "82,4"]]],
        path=tmp_path / "artikel.docx",
    )
    structure = extract_article_structure(path)
    from article_structure import format_section_for_prompt, get_section

    tables_text = "\n".join(t["text"] for t in structure["tables"])
    prompt = prompts.build_results_discussion_prompt(
        {"jenis_artikel": "Kuantitatif"},
        "kuantitatif_eksperimen",
        format_section_for_prompt(get_section(structure, "hasil_pembahasan")),
        tables_text,
        "konteks",
    )
    assert "interpretasi_tabel" in prompt
    assert "82,4" in prompt


def test_finalize_filters_irrelevant_findings_for_qualitative(tmp_path):
    from docx_fixtures import QUALITATIVE_CASE_STUDY

    path = build_docx(QUALITATIVE_CASE_STUDY, path=tmp_path / "kual.docx")
    structure = extract_article_structure(path)
    data = {
        "masalah_teridentifikasi": [
            {
                "prioritas": "mayor",
                "kutipan_asli": "Data dianalisis secara tematik melalui pengodean, kategorisasi, dan perumusan tema.",
                "masalah": "Uji normalitas tidak tersedia dalam artikel.",
                "jenis_masalah": "statistik",
            },
            {
                "prioritas": "mayor",
                "kutipan_asli": "Data dikumpulkan melalui wawancara mendalam, observasi partisipan, dan dokumentasi terhadap lima informan guru.",
                "masalah": "Strategi pemilihan lima informan belum dijelaskan.",
                "jenis_masalah": "pemilihan informan",
            },
        ]
    }
    final = app_module.finalize_section_result(
        data, structure, "metodologi", "kualitatif_studi_kasus"
    )
    kept_ids = [f["masalah"] for f in final["masalah_teridentifikasi"]]
    assert any("informan" in m for m in kept_ids)
    assert all("normalitas" not in m.lower() for m in kept_ids)
    assert final["masalah_dikecualikan"]
    assert "tidak diterapkan" in final["masalah_dikecualikan"][0]["status_kriteria"]


@pytest.mark.parametrize(
    "type_key, expected_prompt_text",
    [
        ("kuantitatif_eksperimen", "uji asumsi/prasyarat"),
        ("kualitatif_studi_kasus", "refleksivitas peneliti"),
        ("mixed_methods", "titik integrasi"),
        ("ptk", "rancangan siklus"),
        ("rnd", "validasi ahli"),
        ("studi_literatur", "risiko cherry-picking"),
        ("slr", "string pencarian"),
        ("konseptual", "proposisi"),
    ],
)
def test_methodology_route_uses_adaptive_prompt_for_required_article_types(
    client, monkeypatch, tmp_path, type_key, expected_prompt_text
):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    output_name = upload_article(client, tmp_path)
    saved_path = next(app_module.OUTPUT_DIR.glob(f"*/{output_name}"))
    result = json.loads(saved_path.read_text(encoding="utf-8"))
    result.update(
        {
            "_jenis_artikel_pilihan": type_key,
            "profil_artikel": {
                "klasifikasi_artikel": {"jenis_artikel": type_key}
            },
            "judul": {"judul_rekomendasi": "Judul"},
            "abstrak": {"versi_revisi": "Abstrak"},
            "pendahuluan": {"versi_revisi": "Pendahuluan"},
        }
    )
    saved_path.write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    prompts_seen = []

    def fake_openai_json(system_prompt, user_prompt):
        prompts_seen.append(user_prompt)
        return {
            "ringkasan": "Prompt metodologi terhubung.",
            "masalah_teridentifikasi": [],
        }

    monkeypatch.setattr(app_module, "openai_chat_json", fake_openai_json)
    response = client.post(
        "/analyze-methodology",
        data={"filename": "artikel.docx", "output_name": output_name},
    )

    assert response.status_code == 200
    assert prompts_seen
    assert "analisis METODOLOGI" in prompts_seen[0]
    assert expected_prompt_text.lower() in prompts_seen[0].lower()
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["metodologi"]["ringkasan"] == "Prompt metodologi terhubung."


def test_all_ai_stage_routes_call_their_detailed_prompt(client, monkeypatch, tmp_path):
    register_and_login(client)
    set_valid_api_key(client, monkeypatch, FAKE_KEY)
    output_name = upload_article(client, tmp_path)
    prompts_seen = []

    def fake_openai_json(system_prompt, user_prompt):
        prompts_seen.append(user_prompt)
        if "identifikasi jenis artikel" in user_prompt:
            return {
                "klasifikasi_artikel": {
                    "jenis_artikel": "kuantitatif_eksperimen",
                    "tingkat_keyakinan": "tinggi",
                    "bukti_teks": [],
                }
            }
        if "evaluasi JUDUL" in user_prompt:
            return {
                "judul_awal": "Judul",
                "judul_rekomendasi": "Judul rekomendasi",
                "masalah_teridentifikasi": [],
            }
        return {
            "ringkasan": "Prompt rinci dipanggil.",
            "masalah_teridentifikasi": [],
        }

    monkeypatch.setattr(app_module, "openai_chat_json", fake_openai_json)
    routes = [
        "/analyze-profile",
        "/analyze-title",
        "/analyze-abstract",
        "/analyze-introduction",
        "/analyze-methodology",
        "/analyze-results-discussion",
        "/analyze-conclusion",
        "/analyze-cross-section",
        "/analyze-reference-citation",
    ]
    for route in routes:
        response = client.post(
            route,
            data={"filename": "artikel.docx", "output_name": output_name},
        )
        assert response.status_code == 200

    expected_signatures = [
        "identifikasi jenis artikel",
        "evaluasi JUDUL",
        "analisis ABSTRAK",
        "analisis PENDAHULUAN",
        "analisis METODOLOGI",
        "analisis HASIL dan PEMBAHASAN",
        "analisis KESIMPULAN",
        "KESELARASAN LINTAS BAGIAN",
        "jelaskan temuan pencocokan",
    ]
    combined = "\n".join(prompts_seen)
    for signature in expected_signatures:
        assert signature in combined
    cross_prompt = next(
        prompt for prompt in prompts_seen if "KESELARASAN LINTAS BAGIAN" in prompt
    )
    assert "[AWL-P01-S01]" in cross_prompt
    assert "[MET-P01-S01]" in cross_prompt


def test_legacy_results_keep_download_and_citation_display(flask_app, tmp_path):
    legacy_result = {
        "_uploaded": True,
        "_filename": "lama.docx",
        "judul": {"judul_rekomendasi": "Judul lama"},
        "abstrak": {"abstrak_revisi": "Abstrak lama"},
        "pendahuluan": {"pendahuluan_revisi": "Pendahuluan lama"},
        "metodologi": {"metodologi_revisi": "Metodologi lama"},
        "hasil_pembahasan": {
            "hasil_pembahasan_revisi": "Hasil dan pembahasan lama"
        },
        "kesimpulan": {"kesimpulan_revisi": "Kesimpulan lama"},
        "sitasi_apa": {
            "sitasi_tanpa_referensi": [
                {"sitasi": "Sumberlama (2020)", "catatan": "Belum ada referensi"}
            ],
            "referensi_tidak_disitasi": ["Referensi Lama (2019)."],
            "referensi_bermasalah": [
                {"referensi_asli": "Entri Lama", "masalah": "Format belum lengkap"}
            ],
            "catatan_akhir_sitasi": "Catatan sitasi hasil lama tetap terlihat.",
        },
        "referensi_tambahan": {"rekomendasi": [], "referensi_dipilih": []},
    }

    assert app_module.is_review_complete(legacy_result)
    groups = app_module.citation_groups_for_display(legacy_result["sitasi_apa"])
    assert groups["referensi_tidak_pernah_disitasi"] == [
        "Referensi Lama (2019)."
    ]
    with flask_app.test_request_context("/"):
        html = render_template(
            "result.html",
            **app_module.result_template_context(
                "lama.docx", "lama.json", legacy_result
            ),
        )
    assert "Sumberlama (2020)" in html
    assert "Entri Lama" in html
    assert "Catatan sitasi hasil lama tetap terlihat." in html
    assert "Unduh Laporan PDF" in html
    pdf_path = tmp_path / "legacy.pdf"
    app_module.build_review_pdf(legacy_result, pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000
