"""Pembangun prompt modular untuk seluruh tahap analisis.

Setiap prompt disusun dari blok yang sama:
1. Peran dan aturan bukti universal.
2. Aturan adaptif sesuai profil artikel (article_profile).
3. Instruksi khusus bagian.
4. Skema keluaran JSON (dengan objek masalah universal).
5. Bukti teks artikel dengan penanda paragraf/kalimat.
"""

import json

from article_profile import (
    build_adaptive_rules_text,
    methodology_components_for,
)
from article_structure import format_section_for_prompt


SYSTEM_ANALYST = (
    "Anda adalah reviewer artikel ilmiah berbahasa Indonesia yang teliti, "
    "berbasis bukti teks, dan konstruktif. Anda tidak pernah mengarang data, "
    "angka, kutipan, sumber, atau isi artikel yang tidak ada. "
    "Kembalikan jawaban HANYA dalam JSON valid tanpa teks lain."
)

MODE_RINGKAS = "ringkas"
MODE_MENDALAM = "mendalam"

FINDING_SCHEMA_RINGKAS = """
Setiap masalah dalam "masalah_teridentifikasi" WAJIB memakai skema minimal berikut
(jangan menambah field lain):
{
  "id": "KODE-NN (mis. ABS-01; kode bagian sesuai penanda kalimat)",
  "prioritas": "kritis/mayor",
  "lokasi": {
    "bagian": "nama bagian",
    "paragraf": nomor paragraf (angka, sesuai penomoran yang diberikan),
    "kalimat": nomor kalimat bila dapat ditentukan (angka atau null),
    "penanda": "ID kalimat seperti INTRO-P03-S02"
  },
  "kutipan_asli": "maksimal 1 kalimat pendek, salin persis dari artikel",
  "masalah": "maksimal 2 kalimat",
  "tindakan_revisi": "maksimal 2 kalimat"
}
""".strip()

FINDING_SCHEMA_MENDALAM = """
Setiap masalah dalam "masalah_teridentifikasi" WAJIB memakai skema berikut:
{
  "id": "KODE-NN (mis. ABS-01; kode bagian sesuai penanda kalimat)",
  "prioritas": "kritis/mayor/minor",
  "lokasi": {
    "bagian": "nama bagian",
    "paragraf": nomor paragraf (angka, sesuai penomoran yang diberikan),
    "kalimat": nomor kalimat bila dapat ditentukan (angka atau null),
    "penanda": "ID kalimat seperti INTRO-P03-S02, atau deskripsi penanda teks"
  },
  "kutipan_asli": "maksimal 2 kalimat yang BENAR-BENAR ada dalam artikel (salin persis)",
  "jenis_masalah": "kategori singkat masalah",
  "masalah": "penjelasan masalah",
  "alasan": "alasan akademik/metodologis, maksimal 3 kalimat",
  "dampak": "dampak terhadap kualitas artikel, maksimal 2 kalimat",
  "tindakan_revisi": "tindakan revisi yang disarankan",
  "contoh_revisi": "contoh revisi maksimal 1 paragraf pendek (tanpa mengarang data)",
  "status_contoh": "dapat digunakan / template / memerlukan data penulis",
  "keterkaitan": [{"bagian": "bagian lain", "penjelasan": "hubungannya"}],
  "keyakinan": "tinggi/sedang/rendah"
}
""".strip()


def finding_schema_text(mode=MODE_MENDALAM):
    if mode == MODE_RINGKAS:
        return FINDING_SCHEMA_RINGKAS
    return FINDING_SCHEMA_MENDALAM


# Kompatibilitas nama lama.
FINDING_SCHEMA_TEXT = FINDING_SCHEMA_MENDALAM

EVIDENCE_RULES = """
ATURAN BUKTI (wajib untuk semua temuan):
- Setiap masalah WAJIB memiliki "kutipan_asli" yang benar-benar terdapat dalam teks artikel; salin apa adanya, jangan diparafrase, jangan mengarang.
- Batasi kutipan pada kalimat/potongan yang diperlukan saja.
- Gunakan nomor paragraf dan kalimat persis seperti penanda [ID] yang diberikan. Jika nomor kalimat tidak dapat ditentukan, isi paragraf dan "penanda" deskriptif.
- Jangan memberi komentar umum tanpa bukti teks.
- Jangan menyatakan suatu informasi tidak ada sebelum memeriksa seluruh konteks yang diberikan.
- Bedakan dengan jelas empat kondisi: (a) informasi benar-benar tidak tersedia; (b) informasi tersedia di bagian lain tetapi belum dicantumkan di bagian ini; (c) informasi tersedia tetapi tidak konsisten; (d) informasi tersedia tetapi kurang rinci. Sebutkan kondisinya dalam "masalah".
- Untuk temuan "informasi tidak tersedia", isi "kutipan_asli" dengan kalimat terdekat yang membuktikan konteksnya (mis. kalimat yang seharusnya memuat informasi itu), bukan kutipan fiktif.
- Contoh revisi tidak boleh mengarang angka, data, sitasi, atau sumber baru. Bila membutuhkan data penulis, gunakan placeholder eksplisit seperti "[Tuliskan dasar pemilihan kelas III A dan III B sebagai sampel.]" dan set "status_contoh" = "memerlukan data penulis".
""".strip()

COMMON_FOCUS_RULES = """
- JANGAN melaporkan temuan minor kosmetik: tata bahasa ringan, pilihan kata,
  variasi gaya, pengulangan kecil yang tidak mengubah makna, masalah format
  kecil, atau saran opsional.
- Fokus HANYA pada masalah yang berdampak nyata terhadap validitas, konsistensi,
  interpretasi, atau keterbacaan substantif artikel.
- Jangan mengulang masalah yang sudah dilaporkan pada tahap lain, kecuali ada
  alasan lintas bagian yang jelas.
- Jangan menuliskan daftar unsur/aspek yang sudah benar dan jangan mengulang isi
  artikel sebagai rangkuman panjang.
""".strip()

OUTPUT_QUALITY_RINGKAS = f"""
KUALITAS KELUARAN (MODE RINGKAS):
- Maksimal 5 temuan; utamakan 3 temuan paling penting. Keluaran yang melebihi
  batas ini akan dipotong sistem.
- HANYA prioritas kritis dan mayor. Jangan melaporkan temuan minor.
{COMMON_FOCUS_RULES}
- Kutipan asli maksimal 1 kalimat pendek; "masalah" maksimal 2 kalimat;
  "tindakan_revisi" maksimal 2 kalimat.
- Tanpa uraian dampak, tanpa contoh revisi, tanpa bagian kekuatan, tanpa
  matriks/tabel audit.
- Isi "status_kesiapan" dan "skor" 0-100.
- Jika tidak ada masalah kritis/mayor, isi "masalah_teridentifikasi": [] dan
  "ringkasan": "Tidak ditemukan masalah mayor yang memerlukan revisi pada tahap ini."
""".strip()

OUTPUT_QUALITY_MENDALAM = f"""
KUALITAS KELUARAN (MODE MENDALAM):
- Maksimal 8 temuan; keluaran yang melebihi batas ini akan dipotong sistem.
- Prioritaskan kritis dan mayor. Temuan minor hanya boleh dilaporkan bila
  berdampak langsung pada validitas penelitian atau kejelasan interpretasi.
{COMMON_FOCUS_RULES}
- Kutipan asli maksimal 2 kalimat; "alasan" maksimal 3 kalimat; "dampak"
  maksimal 2 kalimat; "contoh_revisi" maksimal 1 paragraf pendek.
- Urutkan dari kritis -> mayor -> minor.
- Isi "jumlah_masalah" (kritis/mayor/minor), "prioritas_revisi" (maksimal tiga),
  "status_kesiapan", dan "skor" 0-100.
""".strip()


def output_quality_rules(mode=MODE_MENDALAM):
    if mode == MODE_RINGKAS:
        return OUTPUT_QUALITY_RINGKAS
    return OUTPUT_QUALITY_MENDALAM


def _context_block(name, text, limit=6000):
    text = (text or "").strip()
    if not text:
        return f"{name}: (tidak tersedia)"
    if limit and len(text) > limit:
        text = text[:limit] + "\n[...dipotong...]"
    return f"{name}:\n\"\"\"{text}\"\"\""


def _profile_block(profile_summary):
    return (
        "PROFIL ARTIKEL TERDETEKSI (gunakan sebagai dasar kriteria):\n"
        + json.dumps(profile_summary, ensure_ascii=False, indent=1)
    )


def base_output_schema(extra_fields="", mode=MODE_MENDALAM):
    if mode == MODE_RINGKAS:
        # Mode ringkas: skema minimal tanpa versi revisi dan tanpa field tambahan.
        return (
            "Format JSON wajib:\n"
            "{\n"
            '  "ringkasan": "maksimal 2 kalimat",\n'
            '  "skor": 0,\n'
            '  "status_kesiapan": "siap/perlu revisi minor/perlu revisi mayor",\n'
            '  "masalah_teridentifikasi": [ ...objek masalah skema minimal... ],\n'
            '  "catatan_data_yang_harus_dilengkapi": ["hanya bila ada data yang harus dilengkapi penulis"]\n'
            "}"
        )
    extra = (",\n" + extra_fields) if extra_fields else ""
    return (
        "Format JSON wajib:\n"
        "{\n"
        '  "ringkasan": "ringkasan evaluasi bagian",\n'
        '  "skor": 0,\n'
        '  "status_kesiapan": "siap/perlu revisi minor/perlu revisi mayor",\n'
        '  "jumlah_masalah": {"kritis": 0, "mayor": 0, "minor": 0},\n'
        '  "prioritas_revisi": ["prioritas 1", "prioritas 2", "prioritas 3"],\n'
        '  "masalah_teridentifikasi": [ ...objek masalah universal... ],\n'
        '  "versi_revisi": "versi revisi utuh bagian (tanpa mengarang data)",\n'
        '  "catatan_data_yang_harus_dilengkapi": ["catatan 1"]'
        f"{extra}\n"
        "}"
    )


# ---------------------------------------------------------------------------
# Klasifikasi artikel
# ---------------------------------------------------------------------------

def build_classification_prompt(structure, heuristic_profile):
    sections = structure["sections"]
    parts = []
    for key in ("awal", "abstrak", "pendahuluan", "metodologi", "hasil_pembahasan", "kesimpulan", "artikel"):
        section = sections.get(key)
        if section and section["paragraphs"]:
            parts.append(
                f"== {section['label']} ==\n"
                + format_section_for_prompt(section, max_chars=6000)
            )
    evidence_text = "\n\n".join(parts)

    return f"""
Tugas: identifikasi jenis artikel, pendekatan penelitian, dan desain penelitian
berdasarkan BUKTI TEKS, sebelum analisis rinci dilakukan.

Jangan menentukan jenis hanya dari satu kata kunci. Gunakan gabungan sinyal:
tujuan penelitian, pertanyaan penelitian, bentuk data, sumber data, teknik
pengumpulan data, desain, teknik analisis, struktur hasil, dan cara penulis
menarik kesimpulan.

Pilih "jenis_artikel" dari kunci berikut (atau "belum_teridentifikasi"):
kuantitatif_eksperimen, kuantitatif_survei, kualitatif_studi_kasus, fenomenologi,
etnografi, grounded_theory, analisis_isi, mixed_methods, ptk, rnd, slr,
meta_analisis, studi_literatur, konseptual, evaluatif.

Hasil deteksi heuristik awal (boleh Anda koreksi bila bukti teks menunjukkan lain):
{json.dumps(heuristic_profile, ensure_ascii=False, indent=1)}

Jika desain tidak dinyatakan secara jelas, JANGAN menebak dengan pasti; set
"tingkat_keyakinan": "rendah" dan tulis pada "catatan":
"Jenis atau desain penelitian belum dinyatakan secara cukup jelas dan perlu dikonfirmasi penulis."

Setiap bukti pada "bukti_teks" wajib berupa kutipan yang benar-benar ada dalam
teks di bawah, dengan lokasi memakai penanda [ID] yang diberikan.

Format JSON wajib:
{{
  "klasifikasi_artikel": {{
    "jenis_artikel": "salah satu kunci di atas",
    "pendekatan_penelitian": "...",
    "desain_penelitian": "...",
    "tingkat_keyakinan": "tinggi/sedang/rendah",
    "bukti_teks": [{{"lokasi": "Bagian paragraf N kalimat M (ID)", "kutipan": "..."}}],
    "alternatif_kemungkinan": ["kunci alternatif bila ada"],
    "catatan": "..."
  }}
}}

Teks artikel dengan penanda lokasi:
\"\"\"{evidence_text}\"\"\"
""".strip()


# ---------------------------------------------------------------------------
# Judul
# ---------------------------------------------------------------------------

def build_title_prompt(title_text, profile_summary, article_context, mode=MODE_MENDALAM):
    evaluation_note = (
        "maksimal 2 kalimat" if mode == MODE_RINGKAS else "evaluasi rinci"
    )
    return f"""
Tugas: evaluasi JUDUL artikel dan beri rekomendasi judul baru.

{_profile_block(profile_summary)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

Periksa: kejelasan, kesesuaian dengan isi/konteks artikel, kecocokan dengan jenis
penelitian terdeteksi, panjang, ambiguitas, dan daya tarik akademik. Jangan
mengarang variabel, lokasi, atau metode yang tidak ada.

Format JSON wajib:
{{
  "judul_awal": "judul asli",
  "evaluasi_judul": "{evaluation_note}",
  "masalah_teridentifikasi": [ ...objek masalah (kode ID: JDL)... ],
  "alternatif_judul": ["judul 1", "judul 2", "judul 3"],
  "judul_rekomendasi": "judul terbaik",
  "skor": 0
}}

{finding_schema_text(mode)}

Judul asli:
\"\"\"{title_text}\"\"\"

Konteks singkat artikel:
\"\"\"{article_context}\"\"\"
""".strip()


# ---------------------------------------------------------------------------
# Abstrak
# ---------------------------------------------------------------------------

ABSTRACT_ELEMENTS = [
    "latar belakang singkat", "masalah penelitian", "tujuan",
    "jenis dan desain penelitian", "partisipan/sampel/sumber data",
    "lokasi (bila relevan)", "perlakuan/prosedur inti (bila relevan)",
    "instrumen/pedoman pengumpulan data", "teknik pengumpulan data",
    "teknik analisis data", "hasil utama",
    "nilai statistik penting/effect size (hanya bila artikel kuantitatif dan tersedia)",
    "kontribusi/implikasi", "kata kunci",
]


def build_abstract_prompt(profile_summary, type_key, abstract_struct, context, mode=MODE_MENDALAM):
    elements = "\n".join(f"- {item}" for item in ABSTRACT_ELEMENTS)
    if mode == MODE_RINGKAS:
        detail_blocks = (
            "Gunakan daftar unsur di atas hanya sebagai acuan pemeriksaan; JANGAN "
            "membuat daftar status unsur. Laporkan kekurangan unsur penting "
            "langsung sebagai objek masalah.\n\n"
            + base_output_schema(mode=mode)
        )
    else:
        detail_blocks = (
            '"versi_revisi" adalah abstrak perbaikan utuh: tidak boleh mengarang '
            "angka; angka hanya boleh diambil dari bagian hasil artikel; informasi "
            "yang belum ada ditulis sebagai placeholder [ ... ] dan dicatat pada "
            '"catatan_data_yang_harus_dilengkapi".\n\n'
            + base_output_schema(
                '  "pemeriksaan_unsur": [{"unsur": "...", "status": "tidak ada/kurang rinci/tidak konsisten", "bukti": "kutipan atau -", "catatan": "..."}],\n'
                '  "ketidaksesuaian_dengan_artikel": [{"aspek": "...", "kutipan_abstrak": "...", "kutipan_artikel": "...", "lokasi_artikel": "...", "penjelasan": "..."}]',
                mode=mode,
            )
            + '\nCatatan: isi "pemeriksaan_unsur" HANYA untuk unsur yang bermasalah; '
            "jangan mencantumkan unsur yang sudah benar atau tidak relevan."
        )
    return f"""
Tugas: analisis ABSTRAK dan bandingkan dengan artikel lengkap
(khususnya metodologi, hasil utama, dan kesimpulan yang diberikan di bawah).

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

FOKUS UTAMA TAHAP INI: kelengkapan tujuan, metode, subjek, hasil utama, dan
kesimpulan dalam abstrak, serta ketidaksesuaian abstrak dengan isi artikel.

Unsur abstrak yang relevan untuk jenis artikel ini (acuan pemeriksaan):
{elements}

Periksa juga: klaim yang terlalu luas, klaim kausal yang tidak didukung desain,
dan istilah yang berubah-ubah. Setiap ketidaksesuaian abstrak dengan konteks
artikel (mis. jumlah/jenis instrumen berbeda, hasil "signifikan" tanpa nilai
statistik di bagian hasil) wajib dilaporkan sebagai objek masalah.

{detail_blocks}

{finding_schema_text(mode)}

Abstrak (dengan penanda lokasi):
\"\"\"{format_section_for_prompt(abstract_struct)}\"\"\"

Konteks artikel untuk pembandingan:
{context}
""".strip()


# ---------------------------------------------------------------------------
# Pendahuluan
# ---------------------------------------------------------------------------

INTRO_FUNCTIONS = (
    "konteks umum; masalah empiris; masalah teoretis; bukti lapangan; kajian "
    "penelitian terdahulu; solusi yang ditawarkan; gap penelitian; novelty; "
    "urgensi; tujuan penelitian; kontribusi penelitian"
)


def build_introduction_prompt(profile_summary, type_key, intro_struct, context, batch_note="", mode=MODE_MENDALAM):
    if mode == MODE_RINGKAS:
        detail_blocks = base_output_schema(mode=mode)
    else:
        detail_blocks = (
            '"versi_revisi" harus mempertahankan seluruh sitasi yang valid dan '
            "TIDAK boleh menambah sumber baru.\n\n"
            + base_output_schema(
                '  "peta_fungsi_paragraf": [{"paragraf": 1, "fungsi_yang_diharapkan": "...", "fungsi_aktual": "...", "status": "perlu revisi/tidak sesuai", "alasan": "...", "saran": "..."}],\n'
                '  "evaluasi_gap_penelitian": "...",\n'
                '  "evaluasi_tujuan_dan_rumusan_masalah": "..."',
                mode=mode,
            )
            + '\nCatatan: isi "peta_fungsi_paragraf" HANYA untuk paragraf yang '
            "bermasalah (perlu revisi/tidak sesuai); jangan mencantumkan paragraf "
            "yang sudah sesuai."
        )
    return f"""
Tugas: analisis PENDAHULUAN per paragraf.{batch_note}

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

FOKUS UTAMA TAHAP INI: kejelasan masalah penelitian, gap penelitian, novelty,
dukungan sitasi terhadap klaim, dan kejelasan tujuan penelitian.

Fungsi retorika pendahuluan sebagai acuan: {INTRO_FUNCTIONS}.

Periksa secara khusus: lompatan logika; klaim tanpa kutipan; kutipan yang tidak
mendukung klaim; data awal (observasi/pretest) yang sumber dan prosedurnya tidak
dijelaskan; gap penelitian yang hanya berupa klaim "belum banyak penelitian";
novelty yang belum dibedakan dari sekadar gabungan variabel; ketidaksesuaian
tujuan dengan judul; kesalahan konsep; generalisasi tidak tepat.

{detail_blocks}

{finding_schema_text(mode)}

Pendahuluan (dengan penanda lokasi):
\"\"\"{intro_struct}\"\"\"

Konteks artikel (judul, abstrak, metodologi ringkas):
{context}
""".strip()


# ---------------------------------------------------------------------------
# Metodologi
# ---------------------------------------------------------------------------

def build_methodology_prompt(profile_summary, type_key, method_struct, context, mode=MODE_MENDALAM):
    components = methodology_components_for(type_key)
    component_list = "\n".join(f"- {item}" for item in components)
    if mode == MODE_RINGKAS:
        detail_blocks = (
            "Gunakan daftar komponen di atas hanya sebagai acuan; JANGAN membuat "
            "daftar status komponen. Laporkan komponen penting yang tidak ada atau "
            "tidak konsisten langsung sebagai objek masalah.\n\n"
            + base_output_schema(mode=mode)
        )
    else:
        detail_blocks = (
            "Setiap komponen BERMASALAH dalam \"pemeriksaan_komponen\" memakai format:\n"
            '{"komponen": "...", "status": "sebagian/tidak ada/tidak konsisten",\n'
            '  "bukti": ["kutipan asli"], "masalah": "...", "saran": "...",\n'
            '  "memerlukan_data_penulis": true/false}\n\n'
            '"versi_revisi": JANGAN menulis ulang metodologi menjadi paragraf yang '
            "tampak lengkap dengan mengisi informasi yang tidak ada. Gunakan "
            "placeholder eksplisit, misalnya "
            '"[Tuliskan dasar pemilihan kelas III A dan III B sebagai sampel.]".\n\n'
            + base_output_schema(
                '  "pemeriksaan_komponen": [ ...hanya komponen bermasalah... ],\n'
                '  "kesesuaian_metode_dengan_tujuan": "..."',
                mode=mode,
            )
            + '\nCatatan: JANGAN mencantumkan komponen yang sudah lengkap atau '
            "tidak relevan dalam \"pemeriksaan_komponen\"."
        )
    return f"""
Tugas: analisis METODOLOGI per komponen sesuai jenis artikel.

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

FOKUS UTAMA TAHAP INI: desain; subjek/sampel/informan; teknik sampling;
instrumen; validitas/reliabilitas atau trustworthiness; prosedur; analisis
data; etika penelitian bila relevan.

Komponen yang relevan dengan jenis artikel ini (komponen yang tidak relevan
JANGAN dijadikan masalah):
{component_list}

Periksa pula ketidakkonsistenan internal (istilah berganti-ganti, jumlah
instrumen/butir tidak konsisten, urutan prosedur tidak sistematis, klaim kausal
melebihi kekuatan desain).

{detail_blocks}

{finding_schema_text(mode)}

Metodologi (dengan penanda lokasi):
\"\"\"{method_struct}\"\"\"

Konteks artikel (judul, abstrak, tujuan pada pendahuluan):
{context}
""".strip()


# ---------------------------------------------------------------------------
# Hasil dan Pembahasan
# ---------------------------------------------------------------------------

def build_results_discussion_prompt(profile_summary, type_key, section_struct, tables_text, context, batch_note="", mode=MODE_MENDALAM):
    if mode == MODE_RINGKAS:
        detail_blocks = base_output_schema(mode=mode)
    else:
        detail_blocks = (
            base_output_schema(
                '  "interpretasi_tabel": [{"tabel": "Tabel N", "angka_yang_dilaporkan": ["..."], "interpretasi_penulis": "...", "status_interpretasi": "tidak tepat/perlu verifikasi", "alasan": "...", "revisi_interpretasi": "..."}],\n'
                '  "analisis_tema": [{"tema": "...", "status": "perlu penguatan", "masalah": "...", "saran": "..."}],\n'
                '  "analisis_pembahasan_per_paragraf": [{"paragraf": 1, "hasil_yang_dibahas": "...", "masalah": "...", "saran": "..."}],\n'
                '  "versi_revisi_hasil": "...",\n'
                '  "versi_revisi_pembahasan": "..."',
                mode=mode,
            )
            + '\nCatatan: isi "interpretasi_tabel" HANYA untuk interpretasi yang tidak '
            'tepat atau perlu verifikasi; "analisis_tema" HANYA untuk tema yang perlu '
            'penguatan (bila ada data kualitatif); "analisis_pembahasan_per_paragraf" '
            "HANYA untuk paragraf pembahasan yang bermasalah. Jangan mencantumkan "
            "butir yang sudah baik."
        )
    return f"""
Tugas: analisis HASIL dan PEMBAHASAN secara terpisah walaupun berada dalam satu
heading, sesuai bentuk data artikel.{batch_note}

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

FOKUS UTAMA TAHAP INI: kesesuaian data dengan interpretasi; klaim tanpa bukti;
kesalahan statistik; pembahasan yang hanya mengulang hasil; tidak adanya dialog
dengan penelitian terdahulu.

ANALISIS HASIL — sesuaikan dengan bentuk data:
- Data kuantitatif: ketepatan pemilihan dan pelaporan uji statistik (nilai uji,
  df, p, effect size/N-gain bila relevan); konsistensi angka teks vs tabel;
  klaim signifikan/pengaruh tanpa nilai statistik; kesalahan membaca hasil;
  tabel disebut tapi tidak dijelaskan atau sebaliknya.
- Data kualitatif: kejelasan tema; bukti kutipan partisipan; pemisahan data vs
  interpretasi; kedalaman analisis (bukan sekadar ringkasan wawancara).
- Studi literatur/review: sintesis menghasilkan pola/tema/tren, bukan daftar
  ringkasan.
- Mixed methods: hasil tiap komponen DAN kualitas integrasinya.
JANGAN mengarang nilai statistik yang tidak tersedia.

ANALISIS PEMBAHASAN: tandai pembahasan yang tidak memiliki dasar pada hasil,
yang hanya mengulang angka, atau yang tidak berdialog dengan teori/penelitian
terdahulu; periksa apakah pembahasan menjawab tujuan penelitian.

{detail_blocks}

{finding_schema_text(mode)}

Hasil dan pembahasan (dengan penanda lokasi):
\"\"\"{section_struct}\"\"\"

Tabel yang terdeteksi dalam dokumen:
\"\"\"{tables_text or '(tidak ada tabel terdeteksi)'}\"\"\"

Konteks artikel (tujuan, metodologi ringkas):
{context}
""".strip()


# ---------------------------------------------------------------------------
# Kesimpulan
# ---------------------------------------------------------------------------

def build_conclusion_prompt(profile_summary, type_key, conclusion_struct, context, mode=MODE_MENDALAM):
    if mode == MODE_RINGKAS:
        detail_blocks = (
            "Uji setiap klaim kesimpulan terhadap bukti di bagian hasil; laporkan "
            "klaim yang tidak/sebagian didukung langsung sebagai objek masalah "
            "(JANGAN membuat matriks klaim).\n\n" + base_output_schema(mode=mode)
        )
    else:
        detail_blocks = (
            base_output_schema(
                '  "matriks_klaim": [{"klaim_kesimpulan": "...", "bukti_pendukung_dalam_hasil": ["kutipan hasil"], "status": "sebagian didukung/tidak didukung", "alasan": "...", "revisi_klaim": "..."}]',
                mode=mode,
            )
            + '\nCatatan: isi "matriks_klaim" HANYA untuk klaim yang sebagian '
            "didukung atau tidak didukung; klaim yang sudah didukung penuh tidak "
            "perlu dicantumkan."
        )
    return f"""
Tugas: analisis KESIMPULAN dan uji setiap klaimnya terhadap hasil.

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

FOKUS UTAMA TAHAP INI: klaim yang melebihi hasil; tujuan penelitian yang tidak
terjawab; generalisasi berlebihan; implikasi tanpa dasar.

Periksa sesuai jenis artikel:
- Umum: apakah kesimpulan menjawab tujuan; seluruh klaim berasal dari hasil;
  ada angka/klaim baru yang tidak muncul di hasil; implikasi terlalu luas.
- Kuantitatif: kesesuaian dengan hasil numerik; batas generalisasi; pembedaan
  signifikansi statistik vs makna praktis; ketepatan istilah "berpengaruh",
  "efektif", "meningkatkan" terhadap desain.
- Kualitatif: kesesuaian dengan tema; batas transferabilitas; tidak melakukan
  generalisasi statistik; tidak menambah tema baru.
- Studi literatur/review: sesuai sintesis; tidak menyimpulkan lebih luas dari
  literatur yang dikaji.
- Konseptual: sesuai argumen/proposisi; batas penerapan konsep.

{detail_blocks}

{finding_schema_text(mode)}

Kesimpulan (dengan penanda lokasi):
\"\"\"{conclusion_struct}\"\"\"

Konteks artikel (tujuan, ringkasan hasil):
{context}
""".strip()


# ---------------------------------------------------------------------------
# Konsistensi lintas bagian
# ---------------------------------------------------------------------------

CROSS_SECTION_ASPECTS = [
    "Judul ↔ Tujuan", "Tujuan ↔ Metode", "Metode ↔ Hasil", "Hasil ↔ Pembahasan",
    "Hasil ↔ Kesimpulan", "Abstrak ↔ Artikel lengkap", "Variabel ↔ Instrumen",
    "Indikator ↔ Butir instrumen", "Hipotesis ↔ Uji statistik",
]


def build_cross_section_prompt(profile_summary, type_key, section_texts, citation_summary,
                               mode=MODE_MENDALAM, incomplete=None):
    aspects = "\n".join(f"- {aspect}" for aspect in CROSS_SECTION_ASPECTS)
    # Pemotongan sudah dilakukan di app.py; jangan dipotong lagi di sini.
    context_blocks = "\n\n".join(
        _context_block(label, text, limit=None) for label, text in section_texts
    )
    incomplete_note = ""
    if incomplete:
        incomplete_note = (
            "PERINGATAN INPUT TIDAK LENGKAP: " + "; ".join(incomplete) + ".\n"
            "Aspek yang bergantung pada bagian tersebut JANGAN dianggap selaras. "
            "Jangan menulis 'tidak ditemukan masalah' untuk aspek itu; catat di "
            "\"catatan_data_yang_harus_dilengkapi\"."
        )
    if mode == MODE_RINGKAS:
        detail_blocks = (
            "Laporkan setiap ketidakselarasan langsung sebagai objek masalah "
            "(JANGAN membuat matriks keselarasan). Aspek yang sudah selaras tidak "
            "perlu dilaporkan.\n\n" + base_output_schema(mode=mode)
        )
    else:
        detail_blocks = (
            "Setiap inkonsistensi WAJIB menyertakan bukti kutipan dari KEDUA bagian:\n"
            '{"aspek": "...", "bagian_1": {"lokasi": "...", "kutipan": "..."},\n'
            '  "bagian_2": {"lokasi": "...", "kutipan": "..."},\n'
            '  "status": "tidak selaras/perlu verifikasi",\n'
            '  "masalah": "...", "dampak": "...", "saran": "..."}\n\n'
            + base_output_schema(
                '  "matriks_keselarasan": [ ...hanya aspek yang tidak selaras atau perlu verifikasi... ]',
                mode=mode,
            )
            + '\nCatatan: isi "matriks_keselarasan" HANYA untuk aspek yang tidak '
            "selaras atau perlu verifikasi; aspek yang selaras atau tidak relevan "
            "tidak perlu dicantumkan."
        )
    return f"""
Tugas: periksa KESELARASAN LINTAS BAGIAN artikel.

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{output_quality_rules(mode)}

{incomplete_note}

FOKUS UTAMA TAHAP INI: tujuan vs metode; metode vs hasil; hasil vs kesimpulan;
abstrak vs isi; judul vs isi.

Aspek yang diperiksa (lewati aspek yang tidak relevan dengan jenis artikel,
mis. "Hipotesis ↔ Uji statistik" untuk artikel kualitatif):
{aspects}

Hasil pencocokan sitasi-daftar pustaka dihitung otomatis oleh sistem (JANGAN
menghitung ulang). Ini hasil deteksi berbasis aturan yang dapat memuat salah
deteksi; jangan menjadikannya satu-satunya dasar temuan:
{json.dumps(citation_summary, ensure_ascii=False, indent=1)}

{detail_blocks}

{finding_schema_text(mode)}

Ringkasan setiap bagian artikel:
{context_blocks}
""".strip()


# ---------------------------------------------------------------------------
# Penjelasan sitasi (pencocokan sudah deterministik)
# ---------------------------------------------------------------------------

def build_citation_explanation_prompt(citation_result, reference_texts, mode=MODE_MENDALAM):
    matching = citation_result["pencocokan"]
    group_limit = 15 if mode == MODE_RINGKAS else 30
    payload = {
        "statistik": matching["statistik"],
        "sitasi_tanpa_referensi": matching["sitasi_tanpa_referensi"][:group_limit],
        "tahun_tidak_cocok": matching["tahun_tidak_cocok"][:group_limit],
        "kemungkinan_cocok": matching["kemungkinan_cocok"][:group_limit],
        "referensi_tidak_pernah_disitasi": matching["referensi_tidak_pernah_disitasi"][:group_limit],
        "referensi_duplikat": matching["referensi_duplikat"][:group_limit],
        "referensi_tidak_lengkap": matching["referensi_tidak_lengkap"][:group_limit],
        "sitasi_sekunder": matching["sitasi_sekunder"][:group_limit],
        "sitasi_tanpa_tahun": matching.get("sitasi_tanpa_tahun", [])[:group_limit],
    }
    if mode == MODE_RINGKAS:
        mode_rules = (
            "MODE RINGKAS:\n"
            "- \"penjelasan_masalah\" hanya untuk kelompok yang benar-benar bermasalah, "
            "masing-masing maksimal 2 kalimat, tanpa field \"dampak\".\n"
            "- \"evaluasi_kepatuhan_apa_7\" maksimal 5 entri dengan kesalahan APA MAYOR "
            "saja (bukan variasi format kecil).\n"
            "- \"daftar_perbaikan_yang_direkomendasikan\" maksimal 5 butir singkat."
        )
        reference_limit = 10000
    else:
        mode_rules = (
            "MODE MENDALAM:\n"
            "- Jelaskan hanya kelompok yang bermasalah (dampak dan cara memperbaiki).\n"
            "- \"evaluasi_kepatuhan_apa_7\" maksimal 10 entri dengan kesalahan APA "
            "mayor; jangan mencantumkan entri yang sudah benar."
        )
        reference_limit = 15000
    return f"""
Tugas: jelaskan temuan pencocokan sitasi-daftar pustaka dan periksa format APA 7.

PENTING: pasangan sitasi-referensi SUDAH ditentukan secara deterministik oleh
kode Python di bawah. JANGAN mengubah statistik atau pasangan. Namun, bila Anda
melihat indikasi kuat salah deteksi (mis. nama di "sitasi_tanpa_referensi"
ternyata penulis kedua/ketiga dari entri yang ada di daftar pustaka), JANGAN
diam: laporkan di "kemungkinan_salah_deteksi" beserta alasannya.
Tugas Anda:
1. Menjelaskan setiap kelompok masalah secara akademik.
2. Memeriksa kepatuhan format APA 7 pada entri daftar pustaka yang diberikan;
   tampilkan entri asli dan contoh perbaikan HANYA berdasar data bibliografi yang ada.
3. Jangan mengarang DOI, URL, penulis, judul, atau data bibliografi.

{mode_rules}

Hasil pencocokan deterministik:
{json.dumps(payload, ensure_ascii=False, indent=1)}

Format JSON wajib:
{{
  "ringkasan_kualitas_referensi": "...",
  "penjelasan_masalah": [{{"kelompok": "sitasi tanpa referensi/dll", "penjelasan": "...", "dampak": "...", "cara_memperbaiki": "..."}}],
  "evaluasi_kepatuhan_apa_7": [{{"referensi_asli": "...", "masalah_format": "...", "contoh_format_apa_7": "..."}}],
  "daftar_perbaikan_yang_direkomendasikan": ["..."],
  "kemungkinan_salah_deteksi": [{{"item": "...", "alasan": "..."}}],
  "skor_kualitas_referensi": 0,
  "tingkat_kesiapan_referensi_untuk_publikasi": "Kurang Layak/Cukup/Baik/Sangat Baik/Siap Publikasi"
}}

Daftar pustaka:
\"\"\"{reference_texts[:reference_limit]}\"\"\"
""".strip()
