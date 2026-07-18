"""Ekstraksi struktur artikel dari DOCX.

Modul ini mengubah dokumen .docx menjadi struktur bagian -> paragraf -> kalimat
dengan ID stabil (misalnya INTRO-P03-S02), mempertahankan tabel sebagai blok
terpisah, dan menyediakan utilitas pencarian/validasi kutipan asli.
"""

import re
from difflib import SequenceMatcher

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph as DocxParagraph


MAX_ARTICLE_CHARS = 300_000

SECTION_DEFINITIONS = [
    # (key, label, code, heading keywords)
    ("abstrak", "Abstrak", "ABS", {"abstrak", "abstract"}),
    (
        "pendahuluan",
        "Pendahuluan",
        "INTRO",
        {"pendahuluan", "introduction", "latar belakang", "background"},
    ),
    (
        "metodologi",
        "Metodologi",
        "MET",
        {
            "metode",
            "metodologi",
            "metode penelitian",
            "metodologi penelitian",
            "desain penelitian",
            "prosedur penelitian",
            "metode dan prosedur penelitian",
            "method",
            "methods",
            "methodology",
            "research method",
            "research methods",
            "materials and methods",
            "methods and materials",
            "research design",
            "research procedure",
            "research procedures",
        },
    ),
    (
        "hasil_pembahasan",
        "Hasil dan Pembahasan",
        "HP",
        {
            "hasil",
            "hasil penelitian",
            "hasil dan pembahasan",
            "pembahasan",
            "results",
            "result",
            "results and discussion",
            "discussion",
            "temuan",
            "temuan penelitian",
            "findings",
            "research findings",
        },
    ),
    (
        "kesimpulan",
        "Kesimpulan",
        "KES",
        {"kesimpulan", "simpulan", "conclusion", "conclusions", "penutup"},
    ),
    (
        "daftar_pustaka",
        "Daftar Pustaka",
        "REF",
        {"daftar pustaka", "referensi", "references", "bibliography", "daftar rujukan"},
    ),
    ("lampiran", "Lampiran", "LAM", {"lampiran", "appendix", "appendices"}),
]

SECTION_LABELS = {key: label for key, label, _, _ in SECTION_DEFINITIONS}
SECTION_LABELS.update({"awal": "Awal Artikel (judul/identitas)", "artikel": "Artikel"})
SECTION_CODES = {key: code for key, _, code, _ in SECTION_DEFINITIONS}
SECTION_CODES.update({"awal": "AWL", "artikel": "ART"})

# Kata kunci yang menandai akhir abstrak walau bukan heading section utama.
ABSTRACT_INLINE_STOPS = re.compile(r"\b(?:keywords|kata\s+kunci)\b\s*:?", re.IGNORECASE)

_ABBREVIATIONS = [
    "dkk", "et al", "e.g", "i.e", "cf", "vol", "no", "hlm", "pp", "ed",
    "eds", "dr", "prof", "st", "m.pd", "s.pd", "m.si", "s.si", "m.sc",
    "ph.d", "h.j", "jr", "sr", "kab", "kec", "prov", "tabel", "gambar",
]


def normalize_heading(text):
    normalized = re.sub(
        r"^\s*(?:bab\s+)?[ivxlcdm\d]+[\.\)]?\s+", "", text, flags=re.IGNORECASE
    )
    normalized = re.sub(r"[^a-zA-Z\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def heading_matches(text, keywords):
    """Cocokkan baris terhadap kata kunci heading.

    Baris hanya dianggap heading bila pendek (bukan kalimat naratif yang
    kebetulan memuat kata seperti "hasil").
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 70:
        return False
    normalized = normalize_heading(stripped)
    if not normalized:
        return False
    if normalized in keywords:
        return True
    return any(
        normalized.startswith(keyword) and len(normalized) <= len(keyword) + 20
        for keyword in keywords
    )


def match_section_heading(text):
    for key, _label, _code, keywords in SECTION_DEFINITIONS:
        if heading_matches(text, keywords):
            return key
    return None


def split_sentences(text):
    """Pecah paragraf menjadi kalimat dengan perlindungan singkatan umum."""
    if not text.strip():
        return []
    protected = text
    # Lindungi titik pada singkatan dan inisial agar tidak dianggap akhir kalimat.
    for abbreviation in _ABBREVIATIONS:
        pattern = re.compile(
            r"\b" + re.escape(abbreviation) + r"\.", re.IGNORECASE
        )
        protected = pattern.sub(
            lambda match: match.group(0).replace(".", "․"), protected
        )
    # Inisial nama: "A." / "J. W."
    protected = re.sub(r"\b([A-Z])\.(?=\s*[A-Z])", r"\1․", protected)
    # Angka desimal: 0.05 / 3.14
    protected = re.sub(r"(?<=\d)\.(?=\d)", "․", protected)

    parts = re.split(r"(?<=[.!?])\s+(?=[^\sa-z])", protected)
    sentences = []
    for part in parts:
        restored = part.replace("․", ".").strip()
        if restored:
            sentences.append(restored)
    return sentences


def _iter_block_items(document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _new_section(key):
    return {
        "key": key,
        "label": SECTION_LABELS.get(key, key.title()),
        "code": SECTION_CODES.get(key, key[:3].upper()),
        "detected": False,
        "heading": None,
        "paragraphs": [],
        "tables": [],
    }


def _append_paragraph(section, text):
    number = len(section["paragraphs"]) + 1
    code = section["code"]
    paragraph = {
        "paragraph_number": number,
        "id": f"{code}-P{number:02d}",
        "text": text,
        "sentences": [
            {
                "sentence_number": index + 1,
                "id": f"{code}-P{number:02d}-S{index + 1:02d}",
                "text": sentence,
            }
            for index, sentence in enumerate(split_sentences(text))
        ],
    }
    section["paragraphs"].append(paragraph)


def extract_article_structure(path):
    """Ekstrak struktur artikel: bagian, paragraf bernomor, kalimat, dan tabel."""
    try:
        document = Document(path)
    except Exception as exc:
        raise RuntimeError(
            "File tidak dapat dibaca. Pastikan file adalah dokumen .docx yang valid dan tidak rusak."
        ) from exc

    sections = {"awal": _new_section("awal")}
    order = ["awal"]
    current = sections["awal"]
    tables = []
    table_counter = 0
    heading_found = False
    in_abstract_body = False

    for block in _iter_block_items(document):
        if isinstance(block, Table):
            table_counter += 1
            rows = []
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(cells)
            table = {
                "table_number": table_counter,
                "id": f"{current['code']}-T{table_counter:02d}",
                "section": current["key"],
                "section_label": current["label"],
                "rows": rows,
                "text": "\n".join(" | ".join(row) for row in rows),
            }
            tables.append(table)
            current["tables"].append(table)
            continue

        text = block.text.strip()
        if not text:
            continue

        section_key = match_section_heading(text)
        if section_key:
            heading_found = True
            in_abstract_body = section_key == "abstrak"
            if section_key not in sections:
                sections[section_key] = _new_section(section_key)
                order.append(section_key)
            current = sections[section_key]
            current["detected"] = True
            current["heading"] = current["heading"] or text
            # Teks setelah tanda ":" pada baris heading (mis. "Abstrak: ...").
            if ":" in text:
                inline = text.split(":", 1)[1].strip()
                if inline:
                    _append_paragraph(current, inline)
            continue

        if in_abstract_body:
            match = ABSTRACT_INLINE_STOPS.search(text)
            if match:
                before = text[: match.start()].strip()
                if before:
                    _append_paragraph(current, before)
                keywords_text = text[match.start():].strip()
                if keywords_text:
                    current["keywords_line"] = keywords_text
                in_abstract_body = False
                continue

        _append_paragraph(current, text)

    for section in sections.values():
        section["text"] = "\n".join(
            paragraph["text"] for paragraph in section["paragraphs"]
        )

    full_text_parts = []
    for key in order:
        section = sections[key]
        if section["heading"]:
            full_text_parts.append(section["heading"])
        if section["text"]:
            full_text_parts.append(section["text"])
    for table in tables:
        if table["text"]:
            full_text_parts.append(table["text"])
    full_text = "\n".join(part for part in full_text_parts if part)

    if len(full_text) > MAX_ARTICLE_CHARS:
        raise RuntimeError(
            "Artikel terlalu panjang untuk diproses. Bagi artikel menjadi bagian yang lebih "
            "kecil atau kurangi lampiran, lalu unggah kembali."
        )

    notes = []
    fallback = not heading_found
    if fallback:
        # Artikel tanpa heading: seluruh isi diperlakukan sebagai satu bagian
        # "artikel" agar analisis tetap dapat berjalan dengan aman.
        artikel = _new_section("artikel")
        artikel["detected"] = True
        for paragraph in sections["awal"]["paragraphs"]:
            _append_paragraph(artikel, paragraph["text"])
        artikel["tables"] = tables
        artikel["text"] = "\n".join(p["text"] for p in artikel["paragraphs"])
        sections["artikel"] = artikel
        order.append("artikel")
        notes.append(
            "Tidak ditemukan heading bagian (Abstrak, Pendahuluan, dst.). Seluruh isi "
            "diperlakukan sebagai satu bagian sehingga penomoran paragraf bersifat global."
        )

    return {
        "sections": sections,
        "order": order,
        "tables": tables,
        "full_text": full_text,
        "fallback": fallback,
        "notes": notes,
    }


def get_section(structure, key):
    section = structure["sections"].get(key)
    if section and (section["paragraphs"] or section["detected"]):
        return section
    if structure.get("fallback"):
        return structure["sections"].get("artikel")
    return section


def section_payload(section, max_chars=None):
    """Representasi JSON ringkas sebuah bagian untuk dikirim ke model."""
    if not section:
        return {"section": None, "detected": False, "paragraphs": []}
    paragraphs = []
    total = 0
    for paragraph in section["paragraphs"]:
        entry = {
            "paragraph_number": paragraph["paragraph_number"],
            "id": paragraph["id"],
            "sentences": [
                {
                    "sentence_number": sentence["sentence_number"],
                    "id": sentence["id"],
                    "text": sentence["text"],
                }
                for sentence in paragraph["sentences"]
            ],
        }
        paragraphs.append(entry)
        total += len(paragraph["text"])
        if max_chars and total > max_chars:
            break
    payload = {
        "section": section["label"],
        "detected": section["detected"],
        "heading": section["heading"],
        "paragraphs": paragraphs,
    }
    if section.get("tables"):
        payload["tables"] = [
            {
                "table_number": table["table_number"],
                "id": table["id"],
                "rows": table["rows"][:30],
            }
            for table in section["tables"]
        ]
    return payload


def format_section_for_prompt(section, max_chars=None):
    """Teks bagian dengan penanda [ID paragraf-kalimat] agar model merujuk lokasi."""
    if not section or not section["paragraphs"]:
        return "(bagian tidak terdeteksi atau kosong)"
    lines = []
    total = 0
    for paragraph in section["paragraphs"]:
        sentence_parts = [
            f"[{sentence['id']}] {sentence['text']}"
            for sentence in paragraph["sentences"]
        ]
        line = f"Paragraf {paragraph['paragraph_number']}: " + " ".join(sentence_parts)
        lines.append(line)
        total += len(line)
        if max_chars and total > max_chars:
            lines.append("[... bagian dipotong untuk batch berikutnya ...]")
            break
    for table in section.get("tables", []):
        lines.append(
            f"[{table['id']}] Tabel {table['table_number']}:\n{table['text'][:2000]}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Pencarian dan validasi kutipan
# ---------------------------------------------------------------------------

def normalize_for_match(text):
    return re.sub(r"[^0-9a-zà-öø-ÿ]+", " ", str(text).lower()).strip()


def build_sentence_index(structure):
    index = []
    for key in structure["order"]:
        section = structure["sections"][key]
        for paragraph in section["paragraphs"]:
            for sentence in paragraph["sentences"]:
                index.append(
                    {
                        "section": key,
                        "section_label": section["label"],
                        "paragraph_number": paragraph["paragraph_number"],
                        "sentence_number": sentence["sentence_number"],
                        "id": sentence["id"],
                        "text": sentence["text"],
                        "norm": normalize_for_match(sentence["text"]),
                    }
                )
    return index


def locate_quote(quote, structure, sentence_index=None):
    """Cari kutipan dalam artikel.

    Mengembalikan dict dengan status:
    - "eksak": kutipan ditemukan persis (setelah normalisasi spasi/tanda baca);
    - "dikoreksi": ditemukan kalimat sangat mirip; kutipan dikoreksi otomatis;
    - "tidak_ditemukan": kutipan tidak dapat dibuktikan ada dalam artikel.
    """
    norm_quote = normalize_for_match(quote)
    if len(norm_quote) < 8:
        return {"status": "tidak_ditemukan", "lokasi": None, "kutipan_terkoreksi": None}

    if sentence_index is None:
        sentence_index = build_sentence_index(structure)

    for item in sentence_index:
        if not item["norm"]:
            continue
        if norm_quote in item["norm"] or item["norm"] in norm_quote:
            return {
                "status": "eksak",
                "lokasi": {
                    "bagian": item["section_label"],
                    "paragraf": item["paragraph_number"],
                    "kalimat": item["sentence_number"],
                    "penanda": item["id"],
                },
                "kutipan_terkoreksi": None,
            }

    # Cek pada teks tabel.
    for table in structure.get("tables", []):
        if norm_quote and norm_quote in normalize_for_match(table["text"]):
            return {
                "status": "eksak",
                "lokasi": {
                    "bagian": SECTION_LABELS.get(table["section"], table["section"]),
                    "paragraf": None,
                    "kalimat": None,
                    "penanda": table["id"],
                },
                "kutipan_terkoreksi": None,
            }

    best = None
    best_ratio = 0.0
    for item in sentence_index:
        if not item["norm"]:
            continue
        ratio = SequenceMatcher(None, norm_quote, item["norm"]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = item
    if best and best_ratio >= 0.75:
        return {
            "status": "dikoreksi",
            "lokasi": {
                "bagian": best["section_label"],
                "paragraf": best["paragraph_number"],
                "kalimat": best["sentence_number"],
                "penanda": best["id"],
            },
            "kutipan_terkoreksi": best["text"],
        }

    return {"status": "tidak_ditemukan", "lokasi": None, "kutipan_terkoreksi": None}


def validate_findings_quotes(findings, structure, sentence_index=None):
    """Validasi kutipan_asli setiap temuan terhadap teks artikel.

    Temuan tanpa kutipan atau dengan kutipan yang tidak ditemukan diberi tanda
    "perlu verifikasi" dan tingkat keyakinan diturunkan; kutipan yang sangat
    mirip dikoreksi otomatis satu kali dari teks artikel asli.
    """
    if sentence_index is None:
        sentence_index = build_sentence_index(structure)
    stats = {"terverifikasi": 0, "dikoreksi": 0, "tidak_valid": 0}
    for finding in findings:
        quote = str(finding.get("kutipan_asli") or "").strip()
        if not quote:
            finding["validasi_kutipan"] = "tanpa_kutipan"
            finding["kutipan_valid"] = False
            finding["keyakinan"] = "rendah"
            finding["catatan_validasi"] = (
                "Temuan tidak menyertakan kutipan asli sehingga belum dapat "
                "diverifikasi terhadap teks artikel."
            )
            stats["tidak_valid"] += 1
            continue

        located = locate_quote(quote, structure, sentence_index)
        if located["status"] == "eksak":
            finding["validasi_kutipan"] = "terverifikasi"
            finding["kutipan_valid"] = True
            finding["lokasi_terverifikasi"] = located["lokasi"]
            stats["terverifikasi"] += 1
        elif located["status"] == "dikoreksi":
            finding["kutipan_model"] = quote
            finding["kutipan_asli"] = located["kutipan_terkoreksi"]
            finding["validasi_kutipan"] = "dikoreksi_otomatis"
            finding["kutipan_valid"] = True
            finding["lokasi_terverifikasi"] = located["lokasi"]
            finding["catatan_validasi"] = (
                "Kutipan model tidak persis sama dengan teks artikel dan telah "
                "dikoreksi otomatis dari kalimat terdekat dalam artikel."
            )
            stats["dikoreksi"] += 1
        else:
            finding["validasi_kutipan"] = "tidak_ditemukan"
            finding["kutipan_valid"] = False
            finding["keyakinan"] = "rendah"
            finding["catatan_validasi"] = (
                "Kutipan ini tidak ditemukan dalam teks artikel; temuan perlu "
                "diverifikasi manual dan jangan dianggap bukti yang benar."
            )
            stats["tidak_valid"] += 1
    return findings, stats
