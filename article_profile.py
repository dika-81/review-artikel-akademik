"""Identifikasi jenis artikel dan mesin aturan analisis adaptif.

Klasifikasi awal dilakukan secara deterministik dari bukti teks (bukan sekadar
kata kunci tunggal: sinyal dikumpulkan dari beberapa dimensi — desain,
pengumpulan data, teknik analisis, dan struktur/tujuan), lalu dapat
dikonfirmasi oleh model dan dikoreksi pengguna.
"""

import re

from article_structure import build_sentence_index

# Dimensi sinyal: sebuah jenis artikel baru dianggap meyakinkan bila terdapat
# bukti pada lebih dari satu dimensi, bukan satu kata kunci saja.
APPROACH_SIGNALS = {
    "kuantitatif_eksperimen": {
        "label": "Kuantitatif – Eksperimen/Kuasi Eksperimen",
        "pendekatan": "kuantitatif",
        "modules": ["kuantitatif"],
        "signals": {
            "desain": [
                r"kuasi[\s-]?eksperimen", r"quasi[\s-]?experiment", r"true experiment",
                r"pre[\s-]?experimental", r"nonequivalent control group",
                r"pretest[\s-]?posttest", r"kelompok (?:kontrol|eksperimen)",
                r"kelas (?:kontrol|eksperimen)", r"control group", r"experimental group",
                r"randomized controlled",
            ],
            "pengumpulan": [
                r"\btes\b", r"\bpretest\b", r"\bposttest\b", r"pre[\s-]?test",
                r"post[\s-]?test", r"soal", r"instrumen tes", r"achievement test",
            ],
            "analisis": [
                r"uji[\s-]?t\b", r"\bt-test\b", r"paired sample", r"independent sample",
                r"\banova\b", r"\bancova\b", r"\bmancova\b", r"\bmanova\b",
                r"n[\s-]?gain", r"effect size", r"cohen", r"uji normalitas",
                r"uji homogenitas", r"shapiro", r"levene", r"mann[\s-]?whitney",
                r"wilcoxon", r"nilai p\b", r"p\s*[<=>]\s*0[.,]0", r"signifikan",
            ],
            "tujuan": [
                r"pengaruh", r"efektivitas", r"effectiveness", r"meningkatkan hasil",
                r"perbedaan (?:hasil|kemampuan)", r"improve", r"effect of",
            ],
        },
    },
    "kuantitatif_survei": {
        "label": "Kuantitatif – Survei/Korelasional",
        "pendekatan": "kuantitatif",
        "modules": ["kuantitatif"],
        "signals": {
            "desain": [
                r"survei", r"\bsurvey\b", r"korelasional", r"correlational",
                r"cross[\s-]?sectional", r"ex post facto", r"expost facto",
            ],
            "pengumpulan": [r"kuesioner", r"angket", r"questionnaire", r"skala likert", r"likert"],
            "analisis": [
                r"regresi", r"regression", r"korelasi", r"correlation", r"pearson",
                r"spearman", r"\bsem\b", r"structural equation", r"path analysis",
                r"uji normalitas", r"deskriptif kuantitatif",
            ],
            "tujuan": [r"hubungan antara", r"relationship between", r"kontribusi", r"pengaruh"],
        },
    },
    "kualitatif_studi_kasus": {
        "label": "Kualitatif – Studi Kasus",
        "pendekatan": "kualitatif",
        "modules": ["kualitatif"],
        "signals": {
            "desain": [r"studi kasus", r"case study", r"pendekatan kualitatif", r"qualitative"],
            "pengumpulan": [
                r"wawancara", r"interview", r"observasi partisipan", r"dokumentasi",
                r"catatan lapangan", r"field note", r"informan", r"partisipan",
            ],
            "analisis": [
                r"analisis tematik", r"thematic analysis", r"reduksi data", r"triangulasi",
                r"triangulation", r"member check", r"koding", r"coding", r"kategorisasi",
                r"miles (?:dan|and|&) huberman",
            ],
            "tujuan": [r"mendeskripsikan", r"menggambarkan", r"memahami", r"mengeksplorasi", r"explore"],
        },
    },
    "fenomenologi": {
        "label": "Kualitatif – Fenomenologi",
        "pendekatan": "kualitatif",
        "modules": ["kualitatif"],
        "signals": {
            "desain": [r"fenomenologi", r"phenomenolog"],
            "pengumpulan": [r"wawancara mendalam", r"in[\s-]?depth interview", r"pengalaman partisipan", r"lived experience"],
            "analisis": [r"bracketing", r"epoche", r"horizonalisasi", r"makna pengalaman", r"esensi pengalaman"],
            "tujuan": [r"pengalaman", r"makna", r"experience"],
        },
    },
    "etnografi": {
        "label": "Kualitatif – Etnografi",
        "pendekatan": "kualitatif",
        "modules": ["kualitatif"],
        "signals": {
            "desain": [r"etnografi", r"ethnograph"],
            "pengumpulan": [r"observasi partisipan", r"participant observation", r"imersi", r"budaya"],
            "analisis": [r"analisis domain", r"analisis taksonomi", r"pola budaya"],
            "tujuan": [r"budaya", r"kebiasaan", r"komunitas", r"culture"],
        },
    },
    "grounded_theory": {
        "label": "Kualitatif – Grounded Theory",
        "pendekatan": "kualitatif",
        "modules": ["kualitatif"],
        "signals": {
            "desain": [r"grounded theory"],
            "pengumpulan": [r"theoretical sampling", r"wawancara"],
            "analisis": [r"open coding", r"axial coding", r"selective coding", r"konstanta komparatif", r"constant comparative"],
            "tujuan": [r"membangun teori", r"menghasilkan teori"],
        },
    },
    "analisis_isi": {
        "label": "Kualitatif – Analisis Isi",
        "pendekatan": "kualitatif",
        "modules": ["kualitatif"],
        "signals": {
            "desain": [r"analisis isi", r"content analysis", r"analisis konten"],
            "pengumpulan": [r"dokumen", r"teks", r"buku teks", r"korpus", r"artefak"],
            "analisis": [r"kategori", r"koding", r"unit analisis"],
            "tujuan": [r"menganalisis isi", r"muatan"],
        },
    },
    "mixed_methods": {
        "label": "Mixed Methods",
        "pendekatan": "mixed methods",
        "modules": ["kuantitatif", "kualitatif", "mixed"],
        "signals": {
            "desain": [
                r"mixed[\s-]?method", r"metode campuran", r"explanatory sequential",
                r"exploratory sequential", r"convergent", r"embedded design", r"concurrent",
            ],
            "pengumpulan": [r"kuantitatif dan kualitatif", r"angket dan wawancara", r"tes dan wawancara"],
            "analisis": [r"integrasi data", r"joint display", r"meta[\s-]?inference", r"triangulasi metode"],
            "tujuan": [r"menggabungkan", r"memperdalam hasil kuantitatif"],
        },
    },
    "ptk": {
        "label": "Penelitian Tindakan Kelas (PTK)",
        "pendekatan": "penelitian tindakan kelas",
        "modules": ["ptk"],
        "signals": {
            "desain": [
                r"penelitian tindakan kelas", r"\bptk\b", r"classroom action research",
                r"action research", r"kemmis", r"mc\s?taggart",
            ],
            "pengumpulan": [r"observasi", r"lembar observasi", r"refleksi"],
            "analisis": [r"siklus\s*(?:i{1,3}|[123])", r"antarsiklus", r"indikator keberhasilan", r"ketuntasan"],
            "tujuan": [r"memperbaiki pembelajaran", r"meningkatkan (?:aktivitas|hasil belajar|kemampuan)"],
        },
    },
    "rnd": {
        "label": "Penelitian dan Pengembangan (R&D)/Design-Based Research",
        "pendekatan": "penelitian pengembangan",
        "modules": ["rnd"],
        "signals": {
            "desain": [
                r"research and development", r"\br\s*&\s*d\b", r"penelitian (?:dan )?pengembangan",
                r"\baddie\b", r"4[\s-]?d\b", r"borg (?:dan|and|&) gall", r"design[\s-]?based research",
                r"\bdbr\b", r"plomp", r"dick (?:dan|and|&) carey",
            ],
            "pengumpulan": [r"validasi ahli", r"uji coba (?:produk|terbatas|lapangan)", r"angket respon", r"lembar validasi"],
            "analisis": [r"kelayakan", r"kepraktisan", r"kevalidan", r"skor validasi"],
            "tujuan": [r"mengembangkan", r"menghasilkan produk", r"develop"],
        },
    },
    "slr": {
        "label": "Systematic Literature Review/Scoping Review",
        "pendekatan": "kajian literatur sistematis",
        "modules": ["slr"],
        "signals": {
            "desain": [
                r"systematic (?:literature )?review", r"\bslr\b", r"scoping review", r"\bprisma\b",
            ],
            "pengumpulan": [
                r"basis data", r"database", r"scopus", r"web of science", r"\beric\b",
                r"google scholar", r"string pencarian", r"search string", r"kata kunci pencarian",
            ],
            "analisis": [r"kriteria inklusi", r"kriteria eksklusi", r"screening", r"ekstraksi data", r"penilaian kualitas"],
            "tujuan": [r"memetakan penelitian", r"sintesis", r"tren penelitian"],
        },
    },
    "meta_analisis": {
        "label": "Meta-Analisis",
        "pendekatan": "meta-analisis",
        "modules": ["meta", "slr"],
        "signals": {
            "desain": [r"meta[\s-]?anal"],
            "pengumpulan": [r"kriteria inklusi", r"basis data", r"database"],
            "analisis": [
                r"effect size gabungan", r"random effect", r"fixed effect", r"heterogenitas",
                r"forest plot", r"funnel plot", r"publication bias", r"hedges", r"i\^?2",
            ],
            "tujuan": [r"menggabungkan hasil", r"ukuran efek"],
        },
    },
    "studi_literatur": {
        "label": "Studi Literatur Naratif",
        "pendekatan": "kajian literatur",
        "modules": ["literatur"],
        "signals": {
            "desain": [r"studi literatur", r"kajian literatur", r"literature review", r"kajian pustaka", r"library research", r"studi kepustakaan"],
            "pengumpulan": [r"sumber pustaka", r"artikel terdahulu", r"buku", r"jurnal"],
            "analisis": [r"sintesis", r"analisis deskriptif", r"kajian kritis"],
            "tujuan": [r"mengkaji", r"menelaah", r"memetakan"],
        },
    },
    "konseptual": {
        "label": "Artikel Konseptual/Teoretis",
        "pendekatan": "konseptual",
        "modules": ["konseptual"],
        "signals": {
            "desain": [r"artikel konseptual", r"kajian teoretis", r"conceptual paper", r"theoretical paper", r"gagasan konseptual"],
            "pengumpulan": [r"telaah konsep", r"analisis konsep"],
            "analisis": [r"proposisi", r"kerangka konseptual", r"argumentasi"],
            "tujuan": [r"menawarkan konsep", r"membangun kerangka", r"merumuskan konsep"],
        },
    },
    "evaluatif": {
        "label": "Penelitian Evaluatif",
        "pendekatan": "penelitian evaluatif",
        "modules": ["evaluatif"],
        "signals": {
            "desain": [r"penelitian evaluat", r"evaluation research", r"model cipp", r"\bcipp\b", r"kirkpatrick", r"discrepancy"],
            "pengumpulan": [r"dokumen program", r"wawancara", r"angket", r"observasi"],
            "analisis": [r"kriteria evaluasi", r"standar", r"ketercapaian program"],
            "tujuan": [r"mengevaluasi", r"menilai (?:program|kebijakan|implementasi)"],
        },
    },
}

# Bagian yang paling menentukan klasifikasi (bobot lebih besar).
_PRIORITY_SECTIONS = {"metodologi": 2.0, "abstrak": 1.5, "awal": 1.2}

ARTICLE_TYPE_CHOICES = [
    ("otomatis", "Deteksi otomatis"),
    ("kuantitatif_eksperimen", "Kuantitatif (eksperimen/kuasi eksperimen)"),
    ("kuantitatif_survei", "Kuantitatif (survei/korelasional)"),
    ("kualitatif_studi_kasus", "Kualitatif (studi kasus/tematik)"),
    ("fenomenologi", "Kualitatif (fenomenologi)"),
    ("etnografi", "Kualitatif (etnografi)"),
    ("grounded_theory", "Kualitatif (grounded theory)"),
    ("analisis_isi", "Kualitatif (analisis isi)"),
    ("mixed_methods", "Mixed methods"),
    ("ptk", "Penelitian Tindakan Kelas"),
    ("rnd", "R&D / Design-Based Research"),
    ("studi_literatur", "Studi literatur naratif"),
    ("slr", "Systematic/Scoping review"),
    ("meta_analisis", "Meta-analisis"),
    ("konseptual", "Artikel konseptual/teoretis"),
    ("evaluatif", "Penelitian evaluatif"),
    ("lainnya", "Lainnya (dinyatakan penulis)"),
]

ARTICLE_TYPE_LABELS = {key: label for key, label in ARTICLE_TYPE_CHOICES}


def detect_article_profile(structure):
    """Klasifikasi deterministik berbasis bukti teks dari beberapa dimensi sinyal."""
    sentence_index = build_sentence_index(structure)
    scores = {}
    evidence = {}

    for approach_key, config in APPROACH_SIGNALS.items():
        dims_hit = {}
        approach_evidence = []
        for dimension, patterns in config["signals"].items():
            for pattern in patterns:
                regex = re.compile(pattern, re.IGNORECASE)
                for item in sentence_index:
                    weight = _PRIORITY_SECTIONS.get(item["section"], 1.0)
                    if regex.search(item["text"]):
                        dims_hit[dimension] = max(dims_hit.get(dimension, 0), weight)
                        if len(approach_evidence) < 6:
                            approach_evidence.append(
                                {
                                    "dimensi": dimension,
                                    "lokasi": (
                                        f"{item['section_label']} paragraf "
                                        f"{item['paragraph_number']} kalimat "
                                        f"{item['sentence_number']} ({item['id']})"
                                    ),
                                    "kutipan": item["text"][:300],
                                }
                            )
                        break  # satu bukti per pola cukup
        if dims_hit:
            scores[approach_key] = sum(dims_hit.values()) + 0.5 * len(dims_hit)
            evidence[approach_key] = {
                "dimensi_terpenuhi": sorted(dims_hit.keys()),
                "bukti_teks": approach_evidence,
            }

    if not scores:
        return {
            "jenis_artikel": "belum_teridentifikasi",
            "label": "Belum teridentifikasi",
            "pendekatan_penelitian": "belum jelas",
            "desain_penelitian": "belum dinyatakan",
            "tingkat_keyakinan": "rendah",
            "bukti_teks": [],
            "alternatif_kemungkinan": [],
            "catatan": (
                "Jenis atau desain penelitian belum dinyatakan secara cukup jelas "
                "dan perlu dikonfirmasi penulis."
            ),
            "sumber": "heuristik",
        }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_key, best_score = ranked[0]
    best_dims = len(evidence[best_key]["dimensi_terpenuhi"])
    margin = best_score - (ranked[1][1] if len(ranked) > 1 else 0)

    # Mixed methods menang bila sinyal kuantitatif dan kualitatif sama-sama kuat
    # ATAU desain mixed dinyatakan eksplisit.
    if "mixed_methods" in scores and best_key != "mixed_methods":
        mixed_dims = evidence["mixed_methods"]["dimensi_terpenuhi"]
        if "desain" in mixed_dims:
            best_key = "mixed_methods"
            best_score = scores["mixed_methods"]
            best_dims = len(mixed_dims)

    if best_dims >= 3 and margin >= 1.0:
        confidence = "tinggi"
    elif best_dims >= 2:
        confidence = "sedang"
    else:
        confidence = "rendah"

    config = APPROACH_SIGNALS[best_key]
    alternatives = [
        {
            "jenis": APPROACH_SIGNALS[key]["label"],
            "kunci": key,
            "skor": round(score, 2),
        }
        for key, score in ranked[1:4]
        if score >= best_score * 0.6
    ]

    catatan = ""
    if confidence == "rendah":
        catatan = (
            "Jenis atau desain penelitian belum dinyatakan secara cukup jelas "
            "dan perlu dikonfirmasi penulis."
        )

    return {
        "jenis_artikel": best_key,
        "label": config["label"],
        "pendekatan_penelitian": config["pendekatan"],
        "desain_penelitian": config["label"],
        "tingkat_keyakinan": confidence,
        "bukti_teks": evidence[best_key]["bukti_teks"],
        "dimensi_terpenuhi": evidence[best_key]["dimensi_terpenuhi"],
        "alternatif_kemungkinan": alternatives,
        "catatan": catatan,
        "sumber": "heuristik",
    }


def effective_article_type(result):
    """Jenis artikel efektif: pilihan pengguna > klasifikasi AI > heuristik."""
    override = result.get("_jenis_artikel_pilihan")
    if override and override not in ("", "otomatis"):
        return override, "pilihan pengguna"
    profil = result.get("profil_artikel") or {}
    klasifikasi = profil.get("klasifikasi_artikel") or {}
    if klasifikasi.get("jenis_artikel") in APPROACH_SIGNALS:
        return klasifikasi["jenis_artikel"], "klasifikasi AI"
    heuristik = result.get("_profil_heuristik") or {}
    if heuristik.get("jenis_artikel") in APPROACH_SIGNALS:
        return heuristik["jenis_artikel"], "deteksi heuristik"
    return "belum_teridentifikasi", "belum teridentifikasi"


def article_type_label(type_key):
    if type_key in APPROACH_SIGNALS:
        return APPROACH_SIGNALS[type_key]["label"]
    return ARTICLE_TYPE_LABELS.get(type_key, "Belum teridentifikasi")


def active_modules(type_key):
    if type_key in APPROACH_SIGNALS:
        return APPROACH_SIGNALS[type_key]["modules"]
    if type_key == "lainnya":
        return ["universal"]
    return ["universal"]


# ---------------------------------------------------------------------------
# Kriteria per modul (dipakai untuk membangun prompt adaptif)
# ---------------------------------------------------------------------------

UNIVERSAL_METHOD_COMPONENTS = [
    "kesesuaian metode dengan tujuan/pertanyaan penelitian",
    "kejelasan desain penelitian",
    "konteks penelitian",
    "sumber data dan unit analisis",
    "pemilihan subjek/partisipan/kasus/dokumen/sumber",
    "teknik pengumpulan data",
    "instrumen atau pedoman pengumpulan data",
    "prosedur penelitian",
    "teknik analisis data",
    "upaya menjaga mutu/keabsahan hasil",
    "etika penelitian",
    "keterbatasan metodologis",
    "reproduktibilitas/keterlacakan prosedur",
]

MODULE_COMPONENTS = {
    "kuantitatif": [
        "variabel dan definisi operasional",
        "populasi, sampel, teknik sampling, dan ukuran sampel",
        "desain eksperimen/survei serta kelompok perlakuan dan pembanding (bila ada)",
        "instrumen, indikator, validitas, dan reliabilitas",
        "statistik deskriptif",
        "uji asumsi/prasyarat sesuai uji yang benar-benar dipakai",
        "uji hipotesis/estimasi parameter (nilai statistik, df, p, CI bila tersedia)",
        "effect size/N-gain bila relevan dengan desain",
        "penanganan data hilang dan pencilan",
        "perangkat lunak analisis",
        "ketepatan interpretasi statistik",
    ],
    "kualitatif": [
        "paradigma/pendekatan kualitatif dan alasan pemilihan desain",
        "konteks, setting, karakteristik dan strategi pemilihan informan",
        "jumlah informan dan kecukupan/kejenuhan data",
        "posisi, peran, dan refleksivitas peneliti",
        "teknik wawancara/observasi/dokumentasi dan pedomannya",
        "proses perekaman, transkripsi, dan pengodean",
        "pembentukan kategori dan tema",
        "strategi keabsahan: triangulasi, member checking, peer debriefing, audit trail",
        "kredibilitas, transferabilitas, dependabilitas, konfirmabilitas",
        "penanganan negative cases",
        "etika, anonimitas, dan kerahasiaan",
    ],
    "mixed": [
        "alasan penggunaan mixed methods",
        "jenis desain (convergent/explanatory/exploratory/embedded)",
        "prioritas dan urutan pengumpulan data",
        "titik integrasi dan cara menghubungkan sampel",
        "cara hasil kuantitatif dan kualitatif digabungkan (joint display bila relevan)",
        "penanganan ketidaksesuaian antartemuan dan meta-inference",
        "kualitas masing-masing komponen",
    ],
    "ptk": [
        "identifikasi masalah pembelajaran, subjek, dan konteks kelas",
        "rancangan siklus: perencanaan, tindakan, observasi, refleksi",
        "indikator keberhasilan dan dasar keputusan melanjutkan siklus",
        "perubahan tindakan antarsiklus",
        "peran guru dan peneliti",
        "bukti peningkatan antarsiklus dan refleksi proses",
    ],
    "rnd": [
        "model dan tahapan pengembangan",
        "analisis kebutuhan dan rancangan produk",
        "validasi ahli, revisi produk, dan keputusan revisi",
        "uji coba, karakteristik pengguna, dan instrumen evaluasi",
        "kepraktisan, kelayakan, dan efektivitas (bila diuji)",
        "iterasi desain, produk akhir, dan batas penggunaan produk",
    ],
    "literatur": [
        "fokus kajian dan dasar pemilihan literatur",
        "cakupan sumber",
        "strategi sintesis dan keterlacakan argumen",
        "keseimbangan perspektif dan risiko cherry-picking",
    ],
    "slr": [
        "pertanyaan kajian dan protokol",
        "basis data, kata kunci, string pencarian, rentang waktu",
        "kriteria inklusi/eksklusi dan proses screening",
        "jumlah artikel tiap tahap, penghapusan duplikat, diagram alir",
        "penilaian kualitas studi dan ekstraksi data",
        "teknik sintesis dan keterbatasan pencarian",
    ],
    "meta": [
        "kriteria studi dan ukuran efek beserta transformasinya",
        "model fixed/random effects dan heterogenitas",
        "analisis moderator, publication bias, sensitivity analysis",
        "forest plot/funnel plot dan ketergantungan effect size",
        "interpretasi hasil gabungan",
    ],
    "konseptual": [
        "kejelasan masalah konseptual dan definisi konsep",
        "konsistensi terminologi",
        "kerangka argumen, proposisi, dan hubungan antarkonsep",
        "dasar literatur dan kritik terhadap teori sebelumnya",
        "kontribusi konseptual, batas klaim, implikasi teoretis",
        "kemungkinan pengujian empiris",
    ],
    "evaluatif": [
        "objek dan model evaluasi yang digunakan",
        "kriteria dan standar evaluasi",
        "sumber data evaluasi dan teknik pengumpulan",
        "analisis ketercapaian dan rekomendasi keputusan",
    ],
    "universal": [],
}

# Kriteria yang TIDAK boleh diminta pada jenis artikel tertentu, dipakai untuk
# (1) instruksi prompt dan (2) filter false positive pada temuan model.
IRRELEVANT_DEMANDS = {
    "kualitatif": [
        r"uji normalitas", r"uji homogenitas", r"nilai p\b", r"p[\s-]?value",
        r"effect size", r"n[\s-]?gain", r"uji reliabilitas", r"cronbach",
        r"uji statistik", r"uji hipotesis statistik", r"generalisasi statistik",
        r"jumlah sampel (?:tidak|kurang) memadai", r"kelompok kontrol", r"uji[\s-]?t\b",
        r"\banova\b",
    ],
    "kuantitatif": [
        r"saturasi", r"kejenuhan data", r"member check", r"triangulasi sumber",
        r"refleksivitas", r"transferabilitas", r"konfirmabilitas", r"dependabilitas",
        r"tidak ada wawancara",
    ],
    "literatur": [
        r"partisipan lapangan", r"sampel (?:siswa|peserta didik|mahasiswa)",
        r"populasi dan sampel", r"uji normalitas", r"uji statistik",
        r"instrumen (?:tes|angket)", r"kelompok kontrol", r"tidak ada partisipan",
    ],
    "slr": [
        r"partisipan lapangan", r"sampel (?:siswa|peserta didik|mahasiswa)",
        r"populasi dan sampel", r"uji normalitas", r"kelompok kontrol",
        r"tidak ada partisipan",
    ],
    "meta": [
        r"partisipan lapangan", r"wawancara", r"kelompok kontrol",
    ],
    "konseptual": [
        r"instrumen penelitian", r"partisipan", r"sampel", r"uji statistik",
        r"uji normalitas", r"kelompok kontrol", r"reliabilitas", r"validitas instrumen",
        r"teknik sampling",
    ],
    "ptk": [
        r"generalisasi statistik", r"kelompok kontrol", r"randomisasi",
    ],
    "rnd": [
        r"kelompok kontrol wajib", r"saturasi",
    ],
    "mixed": [],
    "kuantitatif_tambahan": [],
    "universal": [],
    "evaluatif": [],
}

_ABSENCE_MARKERS = re.compile(
    r"\b(tidak ada|tidak tersedia|tidak dilaporkan|tidak disebut|tidak dijelaskan|"
    r"belum ada|belum tersedia|belum dilaporkan|belum disebut|belum dijelaskan|"
    r"tanpa|hilang|missing|not reported|absent|perlu ditambahkan uji|tidak memadai)\b",
    re.IGNORECASE,
)


def irrelevant_demand_patterns(type_key):
    """Pola tuntutan yang tidak relevan bagi jenis artikel efektif."""
    modules = active_modules(type_key)
    patterns = []
    if "kualitatif" in modules and "kuantitatif" not in modules:
        patterns += IRRELEVANT_DEMANDS["kualitatif"]
    if "kuantitatif" in modules and "kualitatif" not in modules:
        patterns += IRRELEVANT_DEMANDS["kuantitatif"]
    for module in modules:
        if module in ("kualitatif", "kuantitatif"):
            continue
        patterns += IRRELEVANT_DEMANDS.get(module, [])
    if type_key in ("studi_literatur",):
        patterns += IRRELEVANT_DEMANDS["literatur"]
    return patterns


def filter_false_positive_findings(findings, type_key):
    """Pisahkan temuan yang menuntut komponen yang tidak relevan bagi desain artikel.

    Temuan tersebut tidak dihapus diam-diam, tetapi dipindahkan ke daftar
    "masalah_dikecualikan" dengan keterangan eksplisit.
    """
    patterns = [re.compile(p, re.IGNORECASE) for p in irrelevant_demand_patterns(type_key)]
    if not patterns:
        return findings, []
    kept, excluded = [], []
    for finding in findings:
        text = " ".join(
            str(finding.get(field, ""))
            for field in ("jenis_masalah", "masalah", "alasan", "tindakan_revisi", "kriteria_yang_digunakan")
        )
        demands_irrelevant = any(p.search(text) for p in patterns)
        claims_absence = bool(_ABSENCE_MARKERS.search(text))
        if demands_irrelevant and claims_absence:
            finding["status_kriteria"] = (
                "Kriteria ini tidak diterapkan karena tidak cukup relevan dengan "
                "desain artikel yang terdeteksi."
            )
            excluded.append(finding)
        else:
            kept.append(finding)
    return kept, excluded


def methodology_components_for(type_key):
    components = list(UNIVERSAL_METHOD_COMPONENTS)
    for module in active_modules(type_key):
        components += MODULE_COMPONENTS.get(module, [])
    return components


def build_adaptive_rules_text(type_key):
    """Teks aturan adaptif untuk disisipkan ke prompt analisis."""
    label = article_type_label(type_key)
    modules = active_modules(type_key)
    lines = [
        f"PROFIL ARTIKEL: {label} (modul analisis aktif: {', '.join(modules)}).",
        "Terapkan HANYA kriteria yang relevan dengan jenis artikel ini.",
    ]
    module_names = {
        "kuantitatif": "Modul kuantitatif",
        "kualitatif": "Modul kualitatif",
        "mixed": "Modul integrasi mixed methods",
        "ptk": "Modul penelitian tindakan kelas",
        "rnd": "Modul R&D/DBR",
        "literatur": "Modul studi literatur",
        "slr": "Modul systematic/scoping review",
        "meta": "Modul meta-analisis",
        "konseptual": "Modul artikel konseptual",
        "evaluatif": "Modul penelitian evaluatif",
        "universal": "Modul universal",
    }
    for module in modules:
        components = MODULE_COMPONENTS.get(module, [])
        if components:
            lines.append(
                f"{module_names.get(module, module)} — periksa sesuai relevansi: "
                + "; ".join(components) + "."
            )
    irrelevant = irrelevant_demand_patterns(type_key)
    if irrelevant:
        readable = ", ".join(
            re.sub(r"\\b|\[\\s-\]\?|\(\?:|\)", "", p) for p in irrelevant[:12]
        )
        lines.append(
            "JANGAN menandai komponen berikut sebagai hilang/kurang karena tidak "
            f"relevan untuk jenis artikel ini: {readable}."
        )
    lines.append(
        "Jika relevansi suatu kriteria meragukan, tulis: \"Kriteria ini tidak "
        "diterapkan karena tidak cukup relevan dengan desain artikel yang terdeteksi.\""
    )
    if type_key == "belum_teridentifikasi":
        lines.append(
            "Jenis artikel belum pasti. Gunakan hanya kriteria universal dan tuliskan "
            "bahwa desain perlu dikonfirmasi penulis; jangan menuntut komponen "
            "spesifik pendekatan tertentu."
        )
    return "\n".join(lines)
