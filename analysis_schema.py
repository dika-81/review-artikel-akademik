"""Skema bersama untuk objek masalah dan validasi keluaran model.

Semua bagian artikel memakai satu skema temuan universal sehingga tampilan,
PDF, dan pengujian dapat memprosesnya secara seragam.
"""

import json
import re


PRIORITY_ORDER = {"kritis": 0, "mayor": 1, "minor": 2}
VALID_PRIORITIES = set(PRIORITY_ORDER)
PRIORITY_ALIASES = {"critical": "kritis", "kritikal": "kritis", "major": "mayor"}
VALID_CONFIDENCE = {"tinggi", "sedang", "rendah"}
CONFIDENCE_ORDER = {"tinggi": 0, "sedang": 1, "rendah": 2}

# Mode analisis: "ringkas" (default unggahan baru) atau "mendalam".
# Hasil lama tanpa field mode diperlakukan sebagai mode mendalam lama.
MODE_RINGKAS = "ringkas"
MODE_MENDALAM = "mendalam"
ANALYSIS_MODES = (MODE_RINGKAS, MODE_MENDALAM)
DEFAULT_ANALYSIS_MODE = MODE_RINGKAS
LEGACY_ANALYSIS_MODE = MODE_MENDALAM
MODE_MAX_FINDINGS = {MODE_RINGKAS: 5, MODE_MENDALAM: 8}
NO_MAJOR_ISSUES_SUMMARY = (
    "Tidak ditemukan masalah mayor yang memerlukan revisi pada tahap ini."
)

# Pola temuan minor kosmetik yang tidak berdampak pada mutu akademik.
COSMETIC_MINOR_PATTERN = re.compile(
    r"tata\s*bahasa|ejaan|typo|salah\s*ketik|saltik|tanda\s*baca|kapitalisasi|"
    r"huruf\s*kapital|diksi|pilihan\s*kata|gaya\s*(?:bahasa|penulisan|selingkung)|"
    r"variasi\s*(?:gaya|kalimat)|cetak\s*miring|italik|spasi|tata\s*letak|"
    r"format\s*(?:penulisan|kecil)|pengulangan\s*kata|repetisi\s*kata|kosmetik",
    re.IGNORECASE,
)
VALID_EXAMPLE_STATUS = {
    "dapat digunakan",
    "dapat langsung digunakan",
    "dapat langsung digunakan setelah diverifikasi penulis",
    "template",
    "memerlukan data penulis",
}
MAX_FINDINGS_PER_SECTION = 15

FINDING_TEMPLATE = {
    "id": "",
    "prioritas": "minor",
    "lokasi": {"bagian": "", "paragraf": None, "kalimat": None, "penanda": ""},
    "kutipan_asli": "",
    "jenis_masalah": "",
    "kriteria_yang_digunakan": "",
    "alasan_kriteria_relevan": "",
    "masalah": "",
    "alasan": "",
    "dampak": "",
    "tindakan_revisi": "",
    "contoh_revisi": "",
    "status_contoh": "template",
    "keterkaitan": [],
    "keyakinan": "sedang",
}


class ModelJSONError(RuntimeError):
    """Keluaran model tidak dapat diparse menjadi JSON valid."""


def _strip_code_fences(content):
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content, count=1)
        content = re.sub(r"\s*```$", "", content, count=1)
    return content.strip()


def _extract_json_object(content):
    """Ambil blok objek JSON pertama yang seimbang kurung kurawalnya."""
    start = content.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return None


def parse_model_json(content):
    """Parse JSON model dengan perbaikan deterministik terkontrol.

    Urutan: apa adanya -> tanpa code fence -> ekstraksi blok {..} ->
    pembersihan trailing comma. Bila tetap gagal, lempar ModelJSONError agar
    pemanggil dapat melakukan satu kali koreksi terkontrol.
    """
    candidates = []
    stripped = _strip_code_fences(str(content))
    candidates.append(stripped)
    extracted = _extract_json_object(stripped)
    if extracted:
        candidates.append(extracted)
    for candidate in list(candidates):
        candidates.append(re.sub(r",\s*([}\]])", r"\1", candidate))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ModelJSONError("OpenAI API mengembalikan respons yang bukan JSON valid.")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_finding(raw, section_code, index):
    """Normalisasi satu objek masalah ke skema universal."""
    finding = dict(FINDING_TEMPLATE)
    if isinstance(raw, str):
        finding["masalah"] = raw
        raw = {}
    elif not isinstance(raw, dict):
        raw = {}
    for key in FINDING_TEMPLATE:
        if key in raw and raw[key] is not None:
            finding[key] = raw[key]
    # Alias skema mode: "status_data" setara dengan "status_contoh".
    if not raw.get("status_contoh") and raw.get("status_data"):
        finding["status_contoh"] = raw["status_data"]
    # Simpan field tambahan yang berguna dari model.
    for key in ("validasi_kutipan", "kutipan_valid", "catatan_validasi", "memerlukan_data_penulis"):
        if key in raw:
            finding[key] = raw[key]

    if not finding["id"]:
        finding["id"] = f"{section_code}-{index + 1:02d}"

    priority = str(finding["prioritas"]).strip().lower()
    priority = PRIORITY_ALIASES.get(priority, priority)
    finding["prioritas"] = priority if priority in VALID_PRIORITIES else "minor"

    confidence = str(finding["keyakinan"]).strip().lower()
    finding["keyakinan"] = confidence if confidence in VALID_CONFIDENCE else "sedang"

    lokasi = finding.get("lokasi")
    if not isinstance(lokasi, dict):
        lokasi = {"penanda": str(lokasi) if lokasi else ""}
    finding["lokasi"] = {
        "bagian": str(lokasi.get("bagian") or ""),
        "paragraf": _as_int(lokasi.get("paragraf")),
        "kalimat": _as_int(lokasi.get("kalimat")),
        "penanda": str(lokasi.get("penanda") or ""),
    }

    status_contoh = str(finding.get("status_contoh") or "").strip().lower()
    if status_contoh not in VALID_EXAMPLE_STATUS:
        finding["status_contoh"] = "template"

    keterkaitan = []
    for item in _as_list(finding.get("keterkaitan")):
        if isinstance(item, dict):
            keterkaitan.append(
                {
                    "bagian": str(item.get("bagian") or ""),
                    "penjelasan": str(item.get("penjelasan") or item.get("kutipan") or ""),
                }
            )
        elif item:
            keterkaitan.append({"bagian": "", "penjelasan": str(item)})
    finding["keterkaitan"] = keterkaitan

    for key in ("kutipan_asli", "jenis_masalah", "masalah", "alasan", "dampak",
                "tindakan_revisi", "contoh_revisi", "kriteria_yang_digunakan",
                "alasan_kriteria_relevan"):
        finding[key] = str(finding.get(key) or "")

    return finding


def sort_findings(findings):
    return sorted(
        findings,
        key=lambda f: (
            PRIORITY_ORDER.get(f.get("prioritas"), 3),
            0 if f.get("kutipan_valid", True) else 1,
        ),
    )


def count_by_priority(findings):
    counts = {"kritis": 0, "mayor": 0, "minor": 0}
    for finding in findings:
        priority = finding.get("prioritas", "minor")
        counts[priority] = counts.get(priority, 0) + 1
    return counts


def normalize_section_result(data, section_code, section_label):
    """Normalisasi hasil analisis satu bagian ke bentuk baku.

    Bentuk baku minimal:
    ringkasan, skor, status_kesiapan, jumlah_masalah, prioritas_revisi,
    masalah_teridentifikasi (array dinamis, diurutkan prioritas, maks 15),
    versi_revisi, catatan_data_yang_harus_dilengkapi.
    Field khusus bagian (pemeriksaan_unsur, peta_fungsi_paragraf, dst.) dibiarkan.
    """
    if not isinstance(data, dict):
        data = {}
    result = dict(data)

    # Mode ringkas boleh mengembalikan daftar temuan pada kunci "temuan".
    if not result.get("masalah_teridentifikasi") and result.get("temuan"):
        result["masalah_teridentifikasi"] = result.pop("temuan")
    findings_raw = _as_list(result.get("masalah_teridentifikasi"))
    findings = [
        normalize_finding(raw, section_code, index)
        for index, raw in enumerate(findings_raw)
    ]
    findings = sort_findings(findings)
    if len(findings) > MAX_FINDINGS_PER_SECTION:
        notes = _as_list(result.get("catatan_data_yang_harus_dilengkapi"))
        critical_and_major = [
            finding
            for finding in findings
            if finding.get("prioritas") in ("kritis", "mayor")
        ]
        if len(critical_and_major) > MAX_FINDINGS_PER_SECTION:
            overflow = [
                finding
                for finding in findings
                if finding.get("prioritas") == "minor"
            ]
            findings = critical_and_major
            notes.append(
                f"Jumlah masalah kritis/mayor ({len(critical_and_major)}) melebihi "
                f"batas ringkas {MAX_FINDINGS_PER_SECTION}; seluruhnya tetap "
                "dipertahankan agar tidak menyembunyikan temuan penting."
            )
        else:
            overflow = findings[MAX_FINDINGS_PER_SECTION:]
            findings = findings[:MAX_FINDINGS_PER_SECTION]
            notes.append(
                f"{len(overflow)} masalah minor tambahan diringkas karena melebihi "
                f"batas {MAX_FINDINGS_PER_SECTION} masalah utama per bagian."
            )
        result["catatan_data_yang_harus_dilengkapi"] = notes
        if overflow:
            result["masalah_tambahan_ringkas"] = [
                {
                    "id": finding.get("id"),
                    "masalah": finding.get("masalah"),
                    "prioritas": finding.get("prioritas"),
                }
                for finding in overflow
            ]
    result["masalah_teridentifikasi"] = findings
    result["jumlah_masalah"] = count_by_priority(findings)

    result["ringkasan"] = str(result.get("ringkasan") or "")
    score = _as_int(result.get("skor"), default=None)
    result["skor"] = max(0, min(100, score)) if score is not None else None
    result["status_kesiapan"] = str(result.get("status_kesiapan") or "")

    priorities = [str(item) for item in _as_list(result.get("prioritas_revisi")) if item]
    if not priorities:
        priorities = [
            f"{f['id']}: {f['tindakan_revisi'] or f['masalah']}"
            for f in findings
            if f.get("prioritas") in ("kritis", "mayor")
        ][:3]
    result["prioritas_revisi"] = priorities[:3]

    result["versi_revisi"] = str(result.get("versi_revisi") or "")
    result["catatan_data_yang_harus_dilengkapi"] = [
        str(item)
        for item in _as_list(result.get("catatan_data_yang_harus_dilengkapi"))
        if item
    ]
    result["_bagian"] = section_label
    return result


def resolve_analysis_mode(value):
    """Kembalikan mode valid; nilai kosong/tidak dikenal dianggap mode mendalam lama."""
    mode = str(value or "").strip().lower()
    return mode if mode in ANALYSIS_MODES else LEGACY_ANALYSIS_MODE


def is_cosmetic_minor(finding):
    """Temuan minor kosmetik (tata bahasa ringan, gaya, format kecil) yang dibuang."""
    if finding.get("prioritas") != "minor":
        return False
    text = " ".join(
        str(finding.get(key) or "") for key in ("jenis_masalah", "masalah")
    )
    return bool(COSMETIC_MINOR_PATTERN.search(text))


def sort_findings_for_mode(findings):
    """Urutkan: kritis -> mayor -> minor, kutipan valid dulu, keyakinan, lalu dampak."""
    return sorted(
        findings,
        key=lambda f: (
            PRIORITY_ORDER.get(f.get("prioritas"), 3),
            0 if f.get("kutipan_valid", True) else 1,
            CONFIDENCE_ORDER.get(f.get("keyakinan"), 1),
            0 if str(f.get("dampak") or "").strip() else 1,
        ),
    )


def apply_mode_limits(result, mode):
    """Potong temuan sesuai mode setelah parsing dan validasi.

    - ringkas: hanya kritis/mayor, maksimal 5 temuan.
    - mendalam: kritis/mayor + minor non-kosmetik, maksimal 8 temuan.
    Temuan minor kosmetik selalu dibuang tanpa dilaporkan.
    """
    mode = resolve_analysis_mode(mode)
    findings = _as_list(result.get("masalah_teridentifikasi"))
    if mode == MODE_RINGKAS:
        findings = [
            finding
            for finding in findings
            if finding.get("prioritas") in ("kritis", "mayor")
        ]
    else:
        findings = [
            finding for finding in findings if not is_cosmetic_minor(finding)
        ]
    findings = sort_findings_for_mode(findings)
    limit = MODE_MAX_FINDINGS[mode]
    overflow = findings[limit:]
    findings = findings[:limit]

    result["masalah_teridentifikasi"] = findings
    result["jumlah_masalah"] = count_by_priority(findings)
    result["mode_analisis"] = mode
    result.pop("masalah_tambahan_ringkas", None)

    important_overflow = [
        finding
        for finding in overflow
        if finding.get("prioritas") in ("kritis", "mayor")
    ]
    if important_overflow:
        notes = [
            str(item)
            for item in _as_list(result.get("catatan_data_yang_harus_dilengkapi"))
            if item
        ]
        notes.append(
            f"{len(important_overflow)} temuan kritis/mayor lain tidak ditampilkan "
            f"karena batas mode {mode} ({limit} temuan per tahap)."
        )
        result["catatan_data_yang_harus_dilengkapi"] = notes

    if not findings and not str(result.get("ringkasan") or "").strip():
        result["ringkasan"] = NO_MAJOR_ISSUES_SUMMARY

    priorities = [
        item
        for item in _as_list(result.get("prioritas_revisi"))
        if item
    ]
    if not priorities:
        priorities = [
            f"{f['id']}: {f.get('tindakan_revisi') or f.get('masalah')}"
            for f in findings
            if f.get("prioritas") in ("kritis", "mayor")
        ]
    result["prioritas_revisi"] = [str(item) for item in priorities][:3]
    return result


def merge_section_results(results, section_code, section_label):
    """Gabungkan hasil analisis beberapa batch paragraf tanpa kehilangan lokasi."""
    if not results:
        return normalize_section_result({}, section_code, section_label)
    merged = dict(results[0])
    findings = []
    notes = []
    priorities = []
    summaries = []
    scores = []
    for partial in results:
        findings.extend(_as_list(partial.get("masalah_teridentifikasi")))
        notes.extend(_as_list(partial.get("catatan_data_yang_harus_dilengkapi")))
        priorities.extend(_as_list(partial.get("prioritas_revisi")))
        if partial.get("ringkasan"):
            summaries.append(str(partial["ringkasan"]))
        score = _as_int(partial.get("skor"))
        if score is not None:
            scores.append(score)
    merged["masalah_teridentifikasi"] = findings
    merged["catatan_data_yang_harus_dilengkapi"] = list(dict.fromkeys(map(str, notes)))
    merged["prioritas_revisi"] = list(dict.fromkeys(map(str, priorities)))
    merged["ringkasan"] = " ".join(summaries)
    merged["skor"] = round(sum(scores) / len(scores)) if scores else None
    return normalize_section_result(merged, section_code, section_label)
