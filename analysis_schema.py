"""Skema bersama untuk objek masalah dan validasi keluaran model.

Semua bagian artikel memakai satu skema temuan universal sehingga tampilan,
PDF, dan pengujian dapat memprosesnya secara seragam.
"""

import json
import re


PRIORITY_ORDER = {"kritis": 0, "mayor": 1, "minor": 2}
VALID_PRIORITIES = set(PRIORITY_ORDER)
VALID_CONFIDENCE = {"tinggi", "sedang", "rendah"}
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
    # Simpan field tambahan yang berguna dari model.
    for key in ("validasi_kutipan", "kutipan_valid", "catatan_validasi", "memerlukan_data_penulis"):
        if key in raw:
            finding[key] = raw[key]

    if not finding["id"]:
        finding["id"] = f"{section_code}-{index + 1:02d}"

    priority = str(finding["prioritas"]).strip().lower()
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
