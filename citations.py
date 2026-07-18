"""Pencocokan sitasi dan daftar pustaka secara deterministik (tanpa AI).

Model bahasa hanya dipakai untuk menjelaskan masalah dan memberi saran format;
penentuan pasangan sitasi-referensi dilakukan oleh kode di modul ini.
"""

import re
import unicodedata
from difflib import SequenceMatcher


YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})([a-z]?)\b")

# Sitasi dalam kurung: "(Nama, 2020)", "(Nama & Nama, 2020; Lain dkk., 2021a)".
PAREN_CITATION = re.compile(r"\(([^()]*(?:19|20)\d{2}[a-z]?[^()]*)\)")

# Sitasi naratif: "Nama (2020)", "Nama dan Nama (2020)", "Nama et al. (2020a)".
NARRATIVE_CITATION = re.compile(
    r"\b([A-ZÀ-Ý][\w'’\-]+(?:\s*(?:&|dan|and)\s*[A-ZÀ-Ý][\w'’\-]+)?"
    r"(?:\s+(?:dkk\.?|et\s+al\.?))?)\s*\(((?:19|20)\d{2}[a-z]?)\)"
)

_ET_AL = re.compile(r"\b(?:dkk\.?|et\s+al\.?)", re.IGNORECASE)
_CONNECTORS = re.compile(r"\s*(?:&|\bdan\b|\band\b)\s*", re.IGNORECASE)
_SECONDARY = re.compile(r"\b(?:dalam|dikutip dalam|as cited in|\bin\b)\b", re.IGNORECASE)
_LEADING_NOISE = re.compile(
    r"^(?:lihat|see|cf\.?|misalnya|e\.g\.?|i\.e\.?|bandingkan|dalam)\s+", re.IGNORECASE
)


def strip_accents(text):
    return "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def normalize_author(name):
    cleaned = strip_accents(str(name)).lower()
    cleaned = re.sub(r"[^a-z\s'-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _first_author_from_citation(author_text):
    """Ambil nama keluarga penulis pertama dari potongan sitasi."""
    text = _LEADING_NOISE.sub("", author_text.strip())
    text = _ET_AL.sub("", text)
    first = _CONNECTORS.split(text)[0]
    first = first.split(",")[0]
    return normalize_author(first)


def parse_citation_segment(segment):
    """Parse satu segmen sitasi, misal "Nama & Nama, 2020a" -> dict atau None."""
    match = YEAR_PATTERN.search(segment)
    if not match:
        return None
    year, letter = match.group(1), match.group(2)
    author_part = segment[: match.start()].strip().rstrip(",").strip()
    secondary = bool(_SECONDARY.search(segment))
    if not author_part and secondary:
        # Bentuk "(1970, dalam Santrock, 2011)": ambil sumber sekunder setelah penanda.
        rest = _SECONDARY.split(segment, maxsplit=1)[-1].strip()
        rest_match = YEAR_PATTERN.search(rest)
        rest_author = rest[: rest_match.start()].strip().rstrip(",").strip() if rest_match else ""
        if rest_match and rest_author:
            year, letter = rest_match.group(1), rest_match.group(2)
            author_part = rest_author
    if not author_part:
        return None
    return {
        "penulis_pertama": _first_author_from_citation(author_part),
        "tahun": year,
        "huruf": letter,
        "sekunder": secondary,
    }


def extract_citations(structure):
    """Ekstrak semua sitasi dalam teks beserta lokasinya (bagian/paragraf/kalimat)."""
    citations = []
    for key in structure["order"]:
        if key == "daftar_pustaka":
            continue
        section = structure["sections"][key]
        for paragraph in section["paragraphs"]:
            for sentence in paragraph["sentences"]:
                text = sentence["text"]
                lokasi = (
                    f"{section['label']} paragraf {paragraph['paragraph_number']} "
                    f"kalimat {sentence['sentence_number']}"
                )
                consumed_spans = []
                for paren_match in PAREN_CITATION.finditer(text):
                    consumed_spans.append(paren_match.span())
                    inner = paren_match.group(1)
                    for segment in inner.split(";"):
                        parsed = parse_citation_segment(segment)
                        if parsed and parsed["penulis_pertama"]:
                            citations.append(
                                {
                                    **parsed,
                                    "sitasi_teks": f"({segment.strip()})",
                                    "bentuk": "parenthetical",
                                    "lokasi": lokasi,
                                    "id_kalimat": sentence["id"],
                                }
                            )
                for narrative in NARRATIVE_CITATION.finditer(text):
                    # Jangan hitung ganda nama di dalam kurung yang sudah diproses.
                    if any(
                        start <= narrative.start() < end
                        for start, end in consumed_spans
                    ):
                        continue
                    author_text, year_text = narrative.group(1), narrative.group(2)
                    year_match = YEAR_PATTERN.search(year_text)
                    citations.append(
                        {
                            "penulis_pertama": _first_author_from_citation(author_text),
                            "tahun": year_match.group(1),
                            "huruf": year_match.group(2),
                            "sekunder": False,
                            "sitasi_teks": f"{author_text} ({year_text})",
                            "bentuk": "naratif",
                            "lokasi": lokasi,
                            "id_kalimat": sentence["id"],
                        }
                    )
    return citations


def extract_references(structure):
    """Ekstrak entri daftar pustaka sebagai daftar terpisah."""
    section = structure["sections"].get("daftar_pustaka")
    references = []
    if not section:
        return references
    for paragraph in section["paragraphs"]:
        text = paragraph["text"].strip()
        if not text or len(text) < 15:
            continue
        match = YEAR_PATTERN.search(text)
        year = match.group(1) if match else ""
        letter = match.group(2) if match else ""
        first_chunk = text.split(",")[0]
        first_author = normalize_author(re.sub(r"\(.*", "", first_chunk))
        title_part = text[match.end():].strip(" .)") if match else text
        references.append(
            {
                "nomor": len(references) + 1,
                "teks": text,
                "penulis_pertama": first_author,
                "tahun": year,
                "huruf": letter,
                "judul_perkiraan": title_part[:120],
                "lengkap": bool(year) and len(text) >= 40,
                "id_paragraf": paragraph["id"],
            }
        )
    return references


def _author_similarity(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_citations_references(citations, references):
    """Cocokkan sitasi dengan daftar pustaka secara deterministik."""
    results = {
        "cocok": [],
        "kemungkinan_cocok": [],
        "sitasi_tanpa_referensi": [],
        "tahun_tidak_cocok": [],
        "sitasi_sekunder": [],
        "referensi_tidak_pernah_disitasi": [],
        "referensi_duplikat": [],
        "referensi_tidak_lengkap": [],
        "statistik": {},
    }

    cited_reference_indices = set()
    seen_citation_keys = set()

    for citation in citations:
        key = (
            citation["penulis_pertama"],
            citation["tahun"],
            citation["huruf"],
            citation["lokasi"],
            citation["sitasi_teks"],
        )
        if key in seen_citation_keys:
            continue
        seen_citation_keys.add(key)

        if citation.get("sekunder"):
            results["sitasi_sekunder"].append(
                {
                    "sitasi_teks": citation["sitasi_teks"],
                    "lokasi": citation["lokasi"],
                    "referensi_pasangan": None,
                    "status": "perlu verifikasi",
                    "alasan": "Terindikasi sitasi sekunder (memakai kata 'dalam').",
                    "saran": (
                        "Usahakan mengutip sumber primer; bila tidak memungkinkan, "
                        "pastikan format sitasi sekunder sesuai APA 7."
                    ),
                }
            )

        exact = None
        year_mismatch = None
        fuzzy = None
        fuzzy_ratio = 0.0
        for index, reference in enumerate(references):
            similarity = _author_similarity(
                citation["penulis_pertama"], reference["penulis_pertama"]
            )
            same_year = (
                citation["tahun"] == reference["tahun"]
                and citation["huruf"] == reference["huruf"]
            )
            if similarity >= 0.95 and same_year:
                exact = (index, reference)
                break
            if similarity >= 0.95 and citation["tahun"] != reference["tahun"]:
                year_mismatch = year_mismatch or (index, reference)
            elif similarity >= 0.8 and same_year and similarity > fuzzy_ratio:
                fuzzy, fuzzy_ratio = (index, reference), similarity

        if exact:
            index, reference = exact
            cited_reference_indices.add(index)
            results["cocok"].append(
                {
                    "sitasi_teks": citation["sitasi_teks"],
                    "lokasi": citation["lokasi"],
                    "referensi_pasangan": reference["teks"],
                    "status": "cocok",
                    "alasan": "Nama penulis pertama dan tahun sama persis.",
                    "saran": "",
                }
            )
        elif fuzzy:
            index, reference = fuzzy
            cited_reference_indices.add(index)
            results["kemungkinan_cocok"].append(
                {
                    "sitasi_teks": citation["sitasi_teks"],
                    "lokasi": citation["lokasi"],
                    "referensi_pasangan": reference["teks"],
                    "status": "perlu verifikasi",
                    "alasan": (
                        "Nama penulis mirip tetapi tidak identik "
                        f"(kemiripan {fuzzy_ratio:.2f}); kemungkinan salah eja."
                    ),
                    "saran": "Samakan ejaan nama penulis pada sitasi dan daftar pustaka.",
                }
            )
        elif year_mismatch:
            index, reference = year_mismatch
            cited_reference_indices.add(index)
            results["tahun_tidak_cocok"].append(
                {
                    "sitasi_teks": citation["sitasi_teks"],
                    "lokasi": citation["lokasi"],
                    "referensi_pasangan": reference["teks"],
                    "status": "tidak cocok",
                    "alasan": (
                        f"Tahun pada sitasi ({citation['tahun']}{citation['huruf']}) "
                        f"berbeda dengan daftar pustaka ({reference['tahun']}{reference['huruf']})."
                    ),
                    "saran": "Periksa sumber asli lalu samakan tahun pada salah satu sisi.",
                }
            )
        else:
            results["sitasi_tanpa_referensi"].append(
                {
                    "sitasi_teks": citation["sitasi_teks"],
                    "lokasi": citation["lokasi"],
                    "referensi_pasangan": None,
                    "status": "tidak cocok",
                    "alasan": "Tidak ada entri daftar pustaka dengan penulis dan tahun yang sesuai.",
                    "saran": "Tambahkan entri daftar pustaka lengkap atau hapus sitasi ini.",
                }
            )

    for index, reference in enumerate(references):
        if index not in cited_reference_indices:
            results["referensi_tidak_pernah_disitasi"].append(
                {
                    "referensi": reference["teks"],
                    "status": "tidak pernah disitasi",
                    "alasan": (
                        "Tidak ditemukan sitasi dalam teks dengan penulis "
                        f"'{reference['penulis_pertama']}' dan tahun "
                        f"{reference['tahun'] or 'tidak diketahui'}."
                    ),
                    "saran": "Sitasi referensi ini dalam teks atau hapus dari daftar pustaka.",
                }
            )
        if not reference["lengkap"]:
            results["referensi_tidak_lengkap"].append(
                {
                    "referensi": reference["teks"],
                    "status": "tidak lengkap",
                    "alasan": (
                        "Entri tidak memuat tahun terbit atau terlalu pendek untuk "
                        "memuat unsur bibliografi lengkap (penulis, tahun, judul, sumber)."
                    ),
                    "saran": "Lengkapi unsur bibliografi sesuai APA 7.",
                }
            )

    for i, ref_a in enumerate(references):
        for ref_b in references[i + 1 :]:
            same_key = (
                ref_a["penulis_pertama"] == ref_b["penulis_pertama"]
                and ref_a["tahun"] == ref_b["tahun"]
                and ref_a["tahun"]
            )
            title_similarity = SequenceMatcher(
                None,
                ref_a["judul_perkiraan"].lower(),
                ref_b["judul_perkiraan"].lower(),
            ).ratio()
            whole_similarity = SequenceMatcher(
                None, ref_a["teks"].lower(), ref_b["teks"].lower()
            ).ratio()
            if (same_key and title_similarity >= 0.8) or whole_similarity >= 0.92:
                results["referensi_duplikat"].append(
                    {
                        "referensi": ref_a["teks"],
                        "duplikat_dengan": ref_b["teks"],
                        "status": "duplikat",
                        "alasan": "Dua entri memiliki penulis, tahun, dan judul yang hampir identik.",
                        "saran": "Gabungkan menjadi satu entri; bila memang dua karya berbeda tahun sama, gunakan akhiran 2024a/2024b.",
                    }
                )

    results["statistik"] = {
        "jumlah_sitasi_terdeteksi": len(seen_citation_keys),
        "jumlah_referensi": len(references),
        "cocok_pasti": len(results["cocok"]),
        "kemungkinan_cocok": len(results["kemungkinan_cocok"]),
        "sitasi_tanpa_referensi": len(results["sitasi_tanpa_referensi"]),
        "tahun_tidak_cocok": len(results["tahun_tidak_cocok"]),
        "referensi_tidak_pernah_disitasi": len(results["referensi_tidak_pernah_disitasi"]),
        "referensi_duplikat": len(results["referensi_duplikat"]),
        "referensi_tidak_lengkap": len(results["referensi_tidak_lengkap"]),
        "sitasi_sekunder": len(results["sitasi_sekunder"]),
    }
    return results


def run_citation_check(structure):
    citations = extract_citations(structure)
    references = extract_references(structure)
    matching = match_citations_references(citations, references)
    return {
        "sitasi_terdeteksi": [
            {
                "sitasi_teks": c["sitasi_teks"],
                "lokasi": c["lokasi"],
                "bentuk": c["bentuk"],
            }
            for c in citations
        ],
        "referensi_terdeteksi": [
            {"nomor": r["nomor"], "teks": r["teks"]} for r in references
        ],
        "pencocokan": matching,
        "catatan_metode": (
            "Pencocokan dilakukan secara deterministik oleh kode Python "
            "(normalisasi nama penulis pertama, tahun, huruf a/b, dkk./et al.); "
            "model AI hanya menjelaskan masalah dan menyarankan format."
        ),
    }
