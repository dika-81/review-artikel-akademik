"""Pengujian ekstraksi struktur DOCX, penomoran, dan validasi kutipan."""

import pytest

from article_structure import (
    extract_article_structure,
    get_section,
    locate_quote,
    split_sentences,
    validate_findings_quotes,
)
from docx_fixtures import (
    ENGLISH_ARTICLE,
    NO_HEADING_ARTICLE,
    QUANTITATIVE_EXPERIMENT,
    build_docx,
)


@pytest.fixture()
def quantitative_structure(tmp_path):
    path = build_docx(
        QUANTITATIVE_EXPERIMENT,
        tables=[[["Kelas", "Rata-rata"], ["Eksperimen", "82,4"], ["Kontrol", "71,2"]]],
        path=tmp_path / "artikel.docx",
    )
    return extract_article_structure(path)


def test_sections_detected_with_headings(quantitative_structure):
    sections = quantitative_structure["sections"]
    for key in ("abstrak", "pendahuluan", "metodologi", "hasil_pembahasan", "kesimpulan", "daftar_pustaka"):
        assert sections[key]["detected"], f"bagian {key} harus terdeteksi"
    assert not quantitative_structure["fallback"]


def test_paragraph_and_sentence_numbering(quantitative_structure):
    intro = quantitative_structure["sections"]["pendahuluan"]
    assert intro["paragraphs"][0]["paragraph_number"] == 1
    assert intro["paragraphs"][0]["id"] == "INTRO-P01"
    first_sentence = intro["paragraphs"][0]["sentences"][0]
    assert first_sentence["id"] == "INTRO-P01-S01"
    assert "geometri" in first_sentence["text"].lower()
    # Paragraf kedua pendahuluan memuat tujuan penelitian.
    assert intro["paragraphs"][1]["paragraph_number"] == 2


def test_sentence_split_protects_abbreviations():
    sentences = split_sentences(
        "Menurut Sari dkk. (2020), nilai p sebesar 0.05 dianggap batas. Hal ini penting."
    )
    assert len(sentences) == 2
    assert "dkk." in sentences[0]
    assert "0.05" in sentences[0]


def test_tables_tracked_with_section_location(quantitative_structure):
    tables = quantitative_structure["tables"]
    assert len(tables) == 1
    table = tables[0]
    assert table["table_number"] == 1
    assert table["rows"][0][0] == "Kelas"
    assert table["id"].endswith("-T01")
    # Tabel ditambahkan di akhir dokumen fixture sehingga menempel pada bagian terakhir.
    assert table["section"] in quantitative_structure["sections"]


def test_no_heading_article_uses_safe_fallback(tmp_path):
    path = build_docx(NO_HEADING_ARTICLE, path=tmp_path / "tanpa_heading.docx")
    structure = extract_article_structure(path)
    assert structure["fallback"]
    artikel = get_section(structure, "pendahuluan")
    assert artikel is not None
    assert artikel["key"] == "artikel"
    assert artikel["paragraphs"], "fallback harus tetap memuat paragraf"
    assert structure["notes"]


def test_english_article_processed(tmp_path):
    path = build_docx(ENGLISH_ARTICLE, path=tmp_path / "english.docx")
    structure = extract_article_structure(path)
    assert structure["sections"]["metodologi"]["detected"]
    assert structure["sections"]["hasil_pembahasan"]["detected"]
    assert "quasi-experimental" in structure["sections"]["metodologi"]["text"].lower()


def test_locate_quote_exact(quantitative_structure):
    located = locate_quote(
        "Sampel dipilih dengan purposive sampling", quantitative_structure
    )
    assert located["status"] == "eksak"
    assert located["lokasi"]["bagian"] == "Metodologi"
    assert located["lokasi"]["paragraf"] == 1


def test_locate_quote_fuzzy_autocorrect(quantitative_structure):
    located = locate_quote(
        "Rata-rata posttest kelas eksperimen adalah 82,4 sedangkan kontrol 71,2.",
        quantitative_structure,
    )
    assert located["status"] == "dikoreksi"
    assert "82,4" in located["kutipan_terkoreksi"]


def test_locate_quote_not_found(quantitative_structure):
    located = locate_quote(
        "Kalimat ini sepenuhnya karangan model dan tidak pernah ada dalam artikel manapun.",
        quantitative_structure,
    )
    assert located["status"] == "tidak_ditemukan"


def test_finding_without_quote_marked_invalid(quantitative_structure):
    findings = [{"id": "MET-01", "masalah": "Teknik sampling kurang dijelaskan"}]
    validated, stats = validate_findings_quotes(findings, quantitative_structure)
    assert validated[0]["kutipan_valid"] is False
    assert validated[0]["validasi_kutipan"] == "tanpa_kutipan"
    assert validated[0]["keyakinan"] == "rendah"
    assert stats["tidak_valid"] == 1


def test_finding_with_fabricated_quote_flagged(quantitative_structure):
    findings = [
        {
            "id": "MET-02",
            "kutipan_asli": "Penelitian ini menggunakan wawancara mendalam dengan tiga puluh partisipan ahli.",
            "masalah": "Klaim palsu",
        }
    ]
    validated, stats = validate_findings_quotes(findings, quantitative_structure)
    assert validated[0]["kutipan_valid"] is False
    assert validated[0]["validasi_kutipan"] == "tidak_ditemukan"
    assert stats["tidak_valid"] == 1


def test_finding_with_real_quote_verified_and_located(quantitative_structure):
    findings = [
        {
            "id": "ABS-01",
            "kutipan_asli": "Data dikumpulkan melalui angket.",
            "masalah": "Abstrak tidak menyebut seluruh instrumen",
        }
    ]
    validated, stats = validate_findings_quotes(findings, quantitative_structure)
    assert validated[0]["kutipan_valid"] is True
    assert validated[0]["validasi_kutipan"] == "terverifikasi"
    assert validated[0]["lokasi_terverifikasi"]["bagian"] == "Abstrak"
    assert stats["terverifikasi"] == 1
