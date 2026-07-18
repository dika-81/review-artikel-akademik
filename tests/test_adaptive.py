"""Pengujian klasifikasi jenis artikel dan mesin aturan adaptif."""

import pytest

from article_profile import (
    active_modules,
    build_adaptive_rules_text,
    detect_article_profile,
    effective_article_type,
    filter_false_positive_findings,
    methodology_components_for,
)
from article_structure import extract_article_structure
from docx_fixtures import (
    CONCEPTUAL_ARTICLE,
    MIXED_METHODS_ARTICLE,
    NO_HEADING_ARTICLE,
    PHENOMENOLOGY_ARTICLE,
    PTK_ARTICLE,
    QUALITATIVE_CASE_STUDY,
    QUANTITATIVE_EXPERIMENT,
    RND_ARTICLE,
    SLR_ARTICLE,
    SURVEY_ARTICLE,
    THEMATIC_INTERVIEW_ARTICLE,
    build_docx,
)


def profile_for(paragraphs, tmp_path, name):
    path = build_docx(paragraphs, path=tmp_path / name)
    return detect_article_profile(extract_article_structure(path))


@pytest.mark.parametrize(
    "paragraphs, expected, name",
    [
        (QUANTITATIVE_EXPERIMENT, "kuantitatif_eksperimen", "kuant.docx"),
        (SURVEY_ARTICLE, "kuantitatif_survei", "survei.docx"),
        (QUALITATIVE_CASE_STUDY, "kualitatif_studi_kasus", "kasus.docx"),
        (PHENOMENOLOGY_ARTICLE, "fenomenologi", "fenomenologi.docx"),
        (THEMATIC_INTERVIEW_ARTICLE, "kualitatif_studi_kasus", "tematik.docx"),
        (MIXED_METHODS_ARTICLE, "mixed_methods", "mixed.docx"),
        (PTK_ARTICLE, "ptk", "ptk.docx"),
        (RND_ARTICLE, "rnd", "rnd.docx"),
        (SLR_ARTICLE, "slr", "slr.docx"),
        (CONCEPTUAL_ARTICLE, "konseptual", "konseptual.docx"),
    ],
)
def test_article_types_detected(paragraphs, expected, name, tmp_path):
    profile = profile_for(paragraphs, tmp_path, name)
    assert profile["jenis_artikel"] == expected, profile
    assert profile["bukti_teks"], "klasifikasi wajib menyertakan bukti teks"
    for evidence in profile["bukti_teks"]:
        assert evidence["kutipan"]
        assert evidence["lokasi"]


def test_uncertain_article_marked_low_confidence(tmp_path):
    profile = profile_for(NO_HEADING_ARTICLE, tmp_path, "tanpa.docx")
    assert profile["tingkat_keyakinan"] == "rendah"
    assert "perlu dikonfirmasi penulis" in profile["catatan"]


def test_qualitative_not_criticized_for_missing_statistics():
    findings = [
        {
            "id": "MET-01",
            "prioritas": "mayor",
            "masalah": "Uji normalitas tidak tersedia dalam artikel.",
            "jenis_masalah": "kelengkapan statistik",
            "alasan": "Uji prasyarat wajib sebelum uji-t.",
        },
        {
            "id": "MET-02",
            "prioritas": "mayor",
            "masalah": "Proses pengodean data wawancara belum dijelaskan rinci.",
            "jenis_masalah": "keterlacakan analisis",
            "alasan": "Pembaca perlu tahu transformasi data mentah menjadi tema.",
        },
    ]
    kept, excluded = filter_false_positive_findings(findings, "fenomenologi")
    assert len(excluded) == 1
    assert "normalitas" in excluded[0]["masalah"].lower()
    assert "tidak diterapkan" in excluded[0]["status_kriteria"]
    assert len(kept) == 1
    assert "pengodean" in kept[0]["masalah"]


def test_quantitative_not_criticized_for_missing_saturation():
    findings = [
        {
            "id": "MET-01",
            "prioritas": "mayor",
            "masalah": "Saturasi data tidak tersedia sehingga kecukupan informan diragukan.",
            "jenis_masalah": "kecukupan data",
        },
        {
            "id": "MET-02",
            "prioritas": "mayor",
            "masalah": "Teknik sampling purposive tidak disertai alasan pemilihan kelas.",
            "jenis_masalah": "teknik sampling",
        },
    ]
    kept, excluded = filter_false_positive_findings(findings, "kuantitatif_eksperimen")
    assert len(excluded) == 1
    assert "saturasi" in excluded[0]["masalah"].lower()
    assert len(kept) == 1


def test_literature_review_not_asked_for_field_participants():
    findings = [
        {
            "id": "MET-01",
            "prioritas": "kritis",
            "masalah": "Tidak ada partisipan penelitian lapangan yang dilibatkan.",
            "jenis_masalah": "partisipan",
        }
    ]
    kept, excluded = filter_false_positive_findings(findings, "slr")
    assert kept == []
    assert len(excluded) == 1


def test_conceptual_not_asked_for_instruments():
    findings = [
        {
            "id": "MET-01",
            "prioritas": "mayor",
            "masalah": "Instrumen penelitian tidak tersedia dalam artikel.",
            "jenis_masalah": "instrumen",
        }
    ]
    kept, excluded = filter_false_positive_findings(findings, "konseptual")
    assert kept == []
    assert len(excluded) == 1


def test_mixed_methods_rules_include_integration():
    rules = build_adaptive_rules_text("mixed_methods")
    assert "integrasi" in rules.lower()
    components = methodology_components_for("mixed_methods")
    assert any("titik integrasi" in c for c in components)
    assert set(active_modules("mixed_methods")) == {"kuantitatif", "kualitatif", "mixed"}


def test_adaptive_rules_forbid_irrelevant_demands_for_qualitative():
    rules = build_adaptive_rules_text("kualitatif_studi_kasus")
    assert "JANGAN menandai" in rules
    assert "normalitas" in rules.lower()


def test_user_override_takes_precedence():
    result = {
        "_jenis_artikel_pilihan": "ptk",
        "profil_artikel": {
            "klasifikasi_artikel": {"jenis_artikel": "kuantitatif_eksperimen"}
        },
    }
    type_key, source = effective_article_type(result)
    assert type_key == "ptk"
    assert source == "pilihan pengguna"

    result["_jenis_artikel_pilihan"] = "otomatis"
    type_key, source = effective_article_type(result)
    assert type_key == "kuantitatif_eksperimen"
    assert source == "klasifikasi AI"
