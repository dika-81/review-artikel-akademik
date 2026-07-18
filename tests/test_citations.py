"""Pengujian parser sitasi-daftar pustaka deterministik."""

import pytest

from article_structure import extract_article_structure
from citations import (
    extract_citations,
    extract_references,
    parse_citation_segment,
    run_citation_check,
)
from docx_fixtures import build_docx


CITATION_ARTICLE = [
    "Judul Artikel Uji Sitasi",
    "Abstrak",
    "Abstrak singkat untuk pengujian sitasi.",
    "Pendahuluan",
    "Media pembelajaran berperan penting (Widodo, 2021). "
    "Sari dan Putra menegaskan hal serupa (Sari & Putra, 2020). "
    "Menurut Rahman dkk. (2019), pembelajaran realistik efektif. "
    "Kajian lain juga mendukung (Lestari, 2018; Nugroho, 2022a). "
    "Pendapat OECD (2023) memperkuat argumen ini. "
    "Temuan awal Piaget (1970, dalam Santrock, 2011) masih relevan. "
    "Ada pula klaim dari sumber yang hilang (Hilangsekali, 2020). "
    "Tahun yang keliru juga diuji (Widada, 2021).",
    "Kesimpulan",
    "Kesimpulan singkat.",
    "Daftar Pustaka",
    "Widodo, A. (2021). Media manipulatif dalam pembelajaran geometri. Jurnal Pendidikan Dasar, 12(1), 1-12.",
    "Sari, D., & Putra, R. (2020). Visualisasi bangun datar melalui tangram. Jurnal Matematika Sekolah, 8(2), 45-58.",
    "Rahman, T., Ahmad, B., & Chandra, D. (2019). Pembelajaran matematika realistik di sekolah dasar. Jurnal Elemen, 5(1), 20-31.",
    "Lestari, P. (2018). Strategi pembelajaran aktif untuk sekolah dasar kelas rendah. Jurnal Ilmu Pendidikan, 4(2), 100-112.",
    "Nugroho, S. (2022a). Media digital interaktif untuk pembelajaran sains dasar. Jurnal Teknologi Pendidikan, 10(1), 15-27.",
    "OECD. (2023). Education at a glance 2023. OECD Publishing.",
    "Santrock, J. (2011). Educational psychology. McGraw-Hill.",
    "Widada, K. (2022). Evaluasi pembelajaran tematik terpadu di sekolah dasar. Jurnal Evaluasi Pendidikan, 3(1), 55-64.",
    "Tidakdisitasi, Z. (2020). Artikel yang tidak pernah dikutip dalam naskah ini sama sekali. Jurnal Sunyi, 1(1), 1-10.",
    "Widodo, A. (2021). Media manipulatif dalam pembelajaran geometri. Jurnal Pendidikan Dasar, 12(1), 1-12.",
]


@pytest.fixture()
def citation_structure(tmp_path):
    path = build_docx(CITATION_ARTICLE, path=tmp_path / "sitasi.docx")
    return extract_article_structure(path)


@pytest.fixture()
def check_result(citation_structure):
    return run_citation_check(citation_structure)


def test_parse_citation_segment_variants():
    assert parse_citation_segment("Widodo, 2021")["penulis_pertama"] == "widodo"
    parsed = parse_citation_segment("Sari & Putra, 2020")
    assert parsed["penulis_pertama"] == "sari"
    parsed = parse_citation_segment("Rahman dkk., 2019")
    assert parsed["penulis_pertama"] == "rahman"
    parsed = parse_citation_segment("Nugroho, 2022a")
    assert (parsed["tahun"], parsed["huruf"]) == ("2022", "a")
    assert parse_citation_segment("tanpa tahun sama sekali") is None


def test_citations_extracted_with_locations(citation_structure):
    citations = extract_citations(citation_structure)
    texts = [c["sitasi_teks"] for c in citations]
    assert any("Widodo, 2021" in t for t in texts)
    assert any("Rahman dkk." in t for t in texts)  # naratif dkk.
    assert any("Nugroho, 2022a" in t for t in texts)  # tahun berakhiran huruf
    assert any("OECD" in t for t in texts)  # organisasi
    widodo = next(c for c in citations if "Widodo, 2021" in c["sitasi_teks"])
    assert "Pendahuluan paragraf 1 kalimat 1" in widodo["lokasi"]


def test_references_extracted_as_entries(citation_structure):
    references = extract_references(citation_structure)
    assert len(references) == 10
    assert references[0]["penulis_pertama"] == "widodo"
    assert references[0]["tahun"] == "2021"


def test_citation_without_reference_detected(check_result):
    missing = check_result["pencocokan"]["sitasi_tanpa_referensi"]
    assert any("Hilangsekali" in item["sitasi_teks"] for item in missing)


def test_reference_never_cited_detected(check_result):
    uncited = check_result["pencocokan"]["referensi_tidak_pernah_disitasi"]
    assert any("Tidakdisitasi" in item["referensi"] for item in uncited)


def test_year_mismatch_detected(check_result):
    mismatches = check_result["pencocokan"]["tahun_tidak_cocok"]
    assert any("Widada" in item["sitasi_teks"] for item in mismatches)
    widada = next(item for item in mismatches if "Widada" in item["sitasi_teks"])
    assert "2021" in widada["alasan"] and "2022" in widada["alasan"]


def test_duplicate_references_detected(check_result):
    duplicates = check_result["pencocokan"]["referensi_duplikat"]
    assert any("Widodo" in item["referensi"] for item in duplicates)


def test_secondary_citation_flagged(check_result):
    secondary = check_result["pencocokan"]["sitasi_sekunder"]
    assert any("Santrock" in item["sitasi_teks"] or "dalam" in item["sitasi_teks"] for item in secondary)


def test_exact_matches_found(check_result):
    matched = check_result["pencocokan"]["cocok"]
    matched_texts = " ".join(item["sitasi_teks"] for item in matched)
    assert "Widodo, 2021" in matched_texts
    assert "Sari & Putra, 2020" in matched_texts
    assert "Nugroho, 2022a" in matched_texts


def test_statistics_summary(check_result):
    stats = check_result["pencocokan"]["statistik"]
    assert stats["jumlah_referensi"] == 10
    assert stats["sitasi_tanpa_referensi"] >= 1
    assert stats["referensi_duplikat"] >= 1
    assert stats["tahun_tidak_cocok"] >= 1
