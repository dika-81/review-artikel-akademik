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

FINDING_SCHEMA_TEXT = """
Setiap masalah dalam "masalah_teridentifikasi" WAJIB memakai skema universal berikut:
{
  "id": "KODE-NN (mis. ABS-01; kode bagian sesuai penanda kalimat)",
  "prioritas": "kritis/mayor/minor",
  "lokasi": {
    "bagian": "nama bagian",
    "paragraf": nomor paragraf (angka, sesuai penomoran yang diberikan),
    "kalimat": nomor kalimat bila dapat ditentukan (angka atau null),
    "penanda": "ID kalimat seperti INTRO-P03-S02, atau deskripsi penanda teks"
  },
  "kutipan_asli": "potongan teks yang BENAR-BENAR ada dalam artikel (salin persis)",
  "jenis_masalah": "kategori singkat masalah",
  "kriteria_yang_digunakan": "kriteria penilaian yang dipakai",
  "alasan_kriteria_relevan": "mengapa kriteria ini relevan untuk jenis artikel ini",
  "masalah": "penjelasan masalah",
  "alasan": "alasan akademik/metodologis",
  "dampak": "dampak terhadap kualitas artikel",
  "tindakan_revisi": "tindakan revisi yang disarankan",
  "contoh_revisi": "contoh kalimat/paragraf hasil revisi",
  "status_contoh": "dapat digunakan / template / memerlukan data penulis",
  "keterkaitan": [{"bagian": "bagian lain", "penjelasan": "hubungannya"}],
  "keyakinan": "tinggi/sedang/rendah"
}
""".strip()

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

OUTPUT_QUALITY_RULES = """
KUALITAS KELUARAN:
- "masalah_teridentifikasi" adalah array DINAMIS: laporkan SEMUA masalah penting yang benar-benar ditemukan (jangan dibatasi dua), tanpa pengulangan.
- Maksimal 15 masalah utama; masalah minor kebahasaan yang serupa boleh dikelompokkan menjadi satu temuan.
- Seluruh masalah kritis dan mayor wajib ditampilkan; urutkan dari kritis -> mayor -> minor.
- Isi "jumlah_masalah" (kritis/mayor/minor), "prioritas_revisi" (tiga prioritas pertama), "status_kesiapan" (mis. "siap", "perlu revisi minor", "perlu revisi mayor"), dan "skor" 0-100.
""".strip()


def _context_block(name, text, limit=6000):
    text = (text or "").strip()
    if not text:
        return f"{name}: (tidak tersedia)"
    if len(text) > limit:
        text = text[:limit] + "\n[...dipotong...]"
    return f"{name}:\n\"\"\"{text}\"\"\""


def _profile_block(profile_summary):
    return (
        "PROFIL ARTIKEL TERDETEKSI (gunakan sebagai dasar kriteria):\n"
        + json.dumps(profile_summary, ensure_ascii=False, indent=1)
    )


def base_output_schema(extra_fields=""):
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

def build_title_prompt(title_text, profile_summary, article_context):
    return f"""
Tugas: evaluasi JUDUL artikel dan beri rekomendasi judul baru.

{_profile_block(profile_summary)}

{EVIDENCE_RULES}

Periksa: kejelasan, kesesuaian dengan isi/konteks artikel, kecocokan dengan jenis
penelitian terdeteksi, panjang, ambiguitas, dan daya tarik akademik. Jangan
mengarang variabel, lokasi, atau metode yang tidak ada.

Format JSON wajib:
{{
  "judul_awal": "judul asli",
  "evaluasi_judul": "evaluasi rinci",
  "masalah_teridentifikasi": [ ...objek masalah universal (kode ID: JDL)... ],
  "alternatif_judul": ["judul 1", "judul 2", "judul 3"],
  "judul_rekomendasi": "judul terbaik",
  "skor": 0
}}

{FINDING_SCHEMA_TEXT}

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


def build_abstract_prompt(profile_summary, type_key, abstract_struct, context):
    elements = "\n".join(f"- {item}" for item in ABSTRACT_ELEMENTS)
    return f"""
Tugas: analisis ABSTRAK secara rinci dan bandingkan dengan artikel lengkap
(khususnya metodologi, hasil utama, dan kesimpulan yang diberikan di bawah).

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{OUTPUT_QUALITY_RULES}

Pemeriksaan unsur abstrak (nilai HANYA unsur yang relevan dengan jenis artikel;
unsur yang tidak relevan diberi status "tidak relevan untuk jenis artikel ini"):
{elements}

Periksa juga: konsistensi abstrak Indonesia dan Inggris (bila keduanya ada),
panjang dan keterbacaan, klaim yang terlalu luas, klaim kausal yang tidak
didukung desain, dan istilah yang berubah-ubah.

Wajib bandingkan abstrak dengan konteks artikel: setiap ketidaksesuaian
(mis. jumlah/jenis instrumen berbeda antara abstrak dan metodologi, hasil
"signifikan" tanpa nilai statistik yang tersedia di bagian hasil) dimasukkan ke
"ketidaksesuaian_dengan_artikel" DAN sebagai objek masalah.

"versi_revisi" adalah abstrak perbaikan utuh: tidak boleh mengarang angka; angka
hanya boleh diambil dari bagian hasil artikel; informasi yang belum ada ditulis
sebagai placeholder [ ... ] dan dicatat pada "catatan_data_yang_harus_dilengkapi".

{base_output_schema(
    '  "pemeriksaan_unsur": [{"unsur": "...", "status": "ada/tidak ada/kurang rinci/tidak konsisten/tidak relevan untuk jenis artikel ini", "bukti": "kutipan atau -", "catatan": "..."}],\n'
    '  "ketidaksesuaian_dengan_artikel": [{"aspek": "...", "kutipan_abstrak": "...", "kutipan_artikel": "...", "lokasi_artikel": "...", "penjelasan": "..."}]'
)}

{FINDING_SCHEMA_TEXT}

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


def build_introduction_prompt(profile_summary, type_key, intro_struct, context, batch_note=""):
    return f"""
Tugas: analisis PENDAHULUAN per paragraf secara rinci.{batch_note}

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{OUTPUT_QUALITY_RULES}

Petakan fungsi SETIAP paragraf terhadap fungsi retorika pendahuluan
({INTRO_FUNCTIONS}) dalam "peta_fungsi_paragraf".

Periksa secara khusus: alur umum -> khusus; pengulangan ide; lompatan logika;
kutipan yang tidak mendukung klaim; klaim tanpa kutipan; data awal
(observasi/pretest) yang sumber dan prosedurnya tidak dijelaskan; gap penelitian
yang hanya berupa klaim "belum banyak penelitian"; novelty yang belum dibedakan
dari sekadar gabungan variabel; ketidaksesuaian tujuan dengan judul; istilah
tidak konsisten; kalimat terlalu panjang; kesalahan konsep; generalisasi tidak tepat.

"versi_revisi" harus mempertahankan seluruh sitasi yang valid dan TIDAK boleh
menambah sumber baru.

{base_output_schema(
    '  "peta_fungsi_paragraf": [{"paragraf": 1, "fungsi_yang_diharapkan": "...", "fungsi_aktual": "...", "status": "sesuai/perlu revisi/tidak sesuai", "alasan": "...", "saran": "..."}],\n'
    '  "evaluasi_gap_penelitian": "...",\n'
    '  "evaluasi_tujuan_dan_rumusan_masalah": "..."'
)}

{FINDING_SCHEMA_TEXT}

Pendahuluan (dengan penanda lokasi):
\"\"\"{intro_struct}\"\"\"

Konteks artikel (judul, abstrak, metodologi ringkas):
{context}
""".strip()


# ---------------------------------------------------------------------------
# Metodologi
# ---------------------------------------------------------------------------

def build_methodology_prompt(profile_summary, type_key, method_struct, context):
    components = methodology_components_for(type_key)
    component_list = "\n".join(f"- {item}" for item in components)
    return f"""
Tugas: analisis METODOLOGI per komponen sesuai jenis artikel.

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{OUTPUT_QUALITY_RULES}

Nilai komponen berikut dalam "pemeriksaan_komponen" (hanya yang relevan dengan
jenis artikel; komponen yang tidak relevan cukup ditandai
"tidak relevan untuk jenis artikel ini" tanpa dijadikan masalah):
{component_list}

Setiap komponen memakai format:
{{"komponen": "...", "status": "lengkap/sebagian/tidak ada/tidak konsisten/tidak relevan untuk jenis artikel ini",
  "bukti": ["kutipan asli"], "masalah": "...", "alasan": "...", "dampak": "...",
  "saran": "...", "contoh_revisi": "...", "memerlukan_data_penulis": true/false}}

Periksa pula ketidakkonsistenan internal (istilah berganti-ganti, jumlah
instrumen/butir tidak konsisten, urutan prosedur tidak sistematis, pengulangan,
klaim kausal melebihi kekuatan desain).

"versi_revisi": JANGAN menulis ulang metodologi menjadi paragraf yang tampak
lengkap dengan mengisi informasi yang tidak ada. Gunakan placeholder eksplisit,
misalnya "[Tuliskan dasar pemilihan kelas III A dan III B sebagai sampel.]".

{base_output_schema(
    '  "pemeriksaan_komponen": [ ...format komponen di atas... ],\n'
    '  "kesesuaian_metode_dengan_tujuan": "..."'
)}

{FINDING_SCHEMA_TEXT}

Metodologi (dengan penanda lokasi):
\"\"\"{method_struct}\"\"\"

Konteks artikel (judul, abstrak, tujuan pada pendahuluan):
{context}
""".strip()


# ---------------------------------------------------------------------------
# Hasil dan Pembahasan
# ---------------------------------------------------------------------------

def build_results_discussion_prompt(profile_summary, type_key, section_struct, tables_text, context, batch_note=""):
    return f"""
Tugas: analisis HASIL dan PEMBAHASAN secara terpisah walaupun berada dalam satu
heading, sesuai bentuk data artikel.{batch_note}

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{OUTPUT_QUALITY_RULES}

ANALISIS HASIL — sesuaikan dengan bentuk data:
- Data kuantitatif: urutan penyajian; kesesuaian dengan tujuan/hipotesis;
  kelengkapan statistik deskriptif, uji prasyarat, ketepatan pemilihan uji,
  pelaporan nilai statistik (nilai uji, df, p, CI bila tersedia), effect size /
  N-gain bila relevan; konsistensi angka teks vs tabel; klaim signifikan/
  pengaruh; kesalahan membaca hasil; tabel disebut tapi tidak dijelaskan; data
  dijelaskan tapi tidak ada di tabel. Setiap temuan statistik dibandingkan
  dengan tabel terkait dalam "interpretasi_tabel".
- Data kualitatif: kejelasan tema; hubungan kategori-tema; bukti kutipan
  partisipan dan keberagamannya; negative cases; pemisahan data vs interpretasi;
  kedalaman analisis (bukan sekadar ringkasan wawancara); keterlacakan tema ke
  sumber data — laporkan dalam "analisis_tema".
- Studi literatur/review: apakah sintesis menghasilkan pola/tema/tipologi/tren/
  kesenjangan, bukan daftar ringkasan.
- Mixed methods: hasil tiap komponen DAN kualitas integrasinya.
JANGAN mengarang nilai statistik yang tidak tersedia.

ANALISIS PEMBAHASAN — untuk setiap paragraf pembahasan isi
"analisis_pembahasan_per_paragraf": hasil yang dibahas; bukti (statistik/tema)
yang menjadi dasar; interpretasi penulis; teori/penelitian terdahulu yang
dipakai; kualitas hubungan logis; masalah; saran penguatan; contoh revisi.
Tandai eksplisit pembahasan yang tidak memiliki dasar pada hasil. Periksa juga:
menjawab tujuan; menjelaskan mekanisme (mis. pedagogis); membandingkan dengan
penelitian sebelumnya; tidak hanya mengulang angka; membahas effect size (bila
kuantitatif); temuan yang tidak sesuai harapan; keterbatasan; implikasi.

{base_output_schema(
    '  "analisis_hasil": {"ringkasan": "...", "masalah_utama": ["..."]},\n'
    '  "interpretasi_tabel": [{"tabel": "Tabel N", "variabel": "...", "angka_yang_dilaporkan": ["..."], "interpretasi_penulis": "...", "status_interpretasi": "tepat/tidak tepat/perlu verifikasi", "alasan": "...", "revisi_interpretasi": "..."}],\n'
    '  "analisis_tema": [{"tema": "...", "status": "kuat/perlu penguatan", "bukti_yang_digunakan": ["..."], "masalah": "...", "saran": "..."}],\n'
    '  "analisis_pembahasan_per_paragraf": [{"paragraf": 1, "hasil_yang_dibahas": "...", "bukti_dasar": "...", "interpretasi_penulis": "...", "rujukan_teori": "...", "kualitas_hubungan_logis": "...", "masalah": "...", "saran": "...", "contoh_revisi": "..."}],\n'
    '  "versi_revisi_hasil": "...",\n'
    '  "versi_revisi_pembahasan": "..."'
)}
Catatan: "analisis_tema" hanya diisi bila artikel memuat data kualitatif;
"interpretasi_tabel" hanya bila ada tabel/angka. "versi_revisi" boleh berisi
gabungan ringkas hasil+pembahasan revisi.

{FINDING_SCHEMA_TEXT}

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

def build_conclusion_prompt(profile_summary, type_key, conclusion_struct, context):
    return f"""
Tugas: analisis KESIMPULAN dan uji setiap klaimnya terhadap hasil.

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{OUTPUT_QUALITY_RULES}

Periksa sesuai jenis artikel:
- Umum: apakah kesimpulan menjawab tujuan; seluruh klaim berasal dari hasil;
  ada angka/klaim baru yang tidak muncul di hasil; terlalu umum; implikasi
  terlalu luas; saran muncul tanpa dasar.
- Kuantitatif: kesesuaian dengan hasil numerik; batas generalisasi; pembedaan
  signifikansi statistik vs makna praktis; ketepatan istilah "berpengaruh",
  "efektif", "meningkatkan" terhadap desain; pertimbangan effect size.
- Kualitatif: kesesuaian dengan tema; batas transferabilitas; tidak melakukan
  generalisasi statistik; tidak menghapus variasi pengalaman; tidak menambah tema baru.
- Studi literatur/review: sesuai sintesis; batas basis data/cakupan; tidak
  menyimpulkan lebih luas dari literatur yang dikaji.
- Konseptual: sesuai argumen/proposisi; kejelasan kontribusi teoretis; batas
  penerapan konsep.

Buat "matriks_klaim": setiap klaim kesimpulan diuji terhadap bukti di bagian hasil.

{base_output_schema(
    '  "matriks_klaim": [{"klaim_kesimpulan": "...", "bukti_pendukung_dalam_hasil": ["kutipan hasil"], "status": "didukung/sebagian didukung/tidak didukung", "alasan": "...", "revisi_klaim": "..."}]'
)}

{FINDING_SCHEMA_TEXT}

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


def build_cross_section_prompt(profile_summary, type_key, section_texts, citation_summary):
    aspects = "\n".join(f"- {aspect}" for aspect in CROSS_SECTION_ASPECTS)
    context_blocks = "\n\n".join(
        _context_block(label, text, limit=7000) for label, text in section_texts
    )
    return f"""
Tugas: periksa KESELARASAN LINTAS BAGIAN artikel dan buat matriks keselarasan.

{_profile_block(profile_summary)}

{build_adaptive_rules_text(type_key)}

{EVIDENCE_RULES}

{OUTPUT_QUALITY_RULES}

Aspek yang wajib diperiksa (lewati aspek yang tidak relevan dengan jenis
artikel, mis. "Hipotesis ↔ Uji statistik" untuk artikel kualitatif — tulis
statusnya "tidak relevan untuk jenis artikel ini"):
{aspects}

Setiap inkonsistensi WAJIB menyertakan bukti kutipan dari KEDUA bagian:
{{"aspek": "...", "bagian_1": {{"lokasi": "...", "kutipan": "..."}},
  "bagian_2": {{"lokasi": "...", "kutipan": "..."}},
  "status": "selaras/tidak selaras/perlu verifikasi/tidak relevan untuk jenis artikel ini",
  "masalah": "...", "dampak": "...", "saran": "..."}}

Hasil pencocokan sitasi-daftar pustaka sudah dihitung secara deterministik oleh
sistem (JANGAN menghitung ulang; gunakan sebagai fakta):
{json.dumps(citation_summary, ensure_ascii=False, indent=1)}

{base_output_schema(
    '  "matriks_keselarasan": [ ...format aspek di atas... ]'
)}

{FINDING_SCHEMA_TEXT}

Ringkasan setiap bagian artikel:
{context_blocks}
""".strip()


# ---------------------------------------------------------------------------
# Penjelasan sitasi (pencocokan sudah deterministik)
# ---------------------------------------------------------------------------

def build_citation_explanation_prompt(citation_result, reference_texts):
    matching = citation_result["pencocokan"]
    payload = {
        "statistik": matching["statistik"],
        "sitasi_tanpa_referensi": matching["sitasi_tanpa_referensi"][:30],
        "tahun_tidak_cocok": matching["tahun_tidak_cocok"][:30],
        "kemungkinan_cocok": matching["kemungkinan_cocok"][:30],
        "referensi_tidak_pernah_disitasi": matching["referensi_tidak_pernah_disitasi"][:30],
        "referensi_duplikat": matching["referensi_duplikat"][:30],
        "referensi_tidak_lengkap": matching["referensi_tidak_lengkap"][:30],
        "sitasi_sekunder": matching["sitasi_sekunder"][:30],
    }
    return f"""
Tugas: jelaskan temuan pencocokan sitasi-daftar pustaka dan periksa format APA 7.

PENTING: pasangan sitasi-referensi SUDAH ditentukan secara deterministik oleh
kode Python di bawah. JANGAN mengubah, menambah, atau menghapus pasangan.
Tugas Anda hanya:
1. Menjelaskan setiap kelompok masalah secara akademik (dampak dan cara memperbaiki).
2. Memeriksa kepatuhan format APA 7 pada entri daftar pustaka yang diberikan;
   tampilkan entri asli dan contoh perbaikan HANYA berdasar data bibliografi yang ada.
3. Jangan mengarang DOI, URL, penulis, judul, atau data bibliografi.

Hasil pencocokan deterministik:
{json.dumps(payload, ensure_ascii=False, indent=1)}

Format JSON wajib:
{{
  "ringkasan_kualitas_referensi": "...",
  "penjelasan_masalah": [{{"kelompok": "sitasi tanpa referensi/dll", "penjelasan": "...", "dampak": "...", "cara_memperbaiki": "..."}}],
  "evaluasi_kepatuhan_apa_7": [{{"referensi_asli": "...", "masalah_format": "...", "contoh_format_apa_7": "..."}}],
  "daftar_perbaikan_yang_direkomendasikan": ["..."],
  "skor_kualitas_referensi": 0,
  "tingkat_kesiapan_referensi_untuk_publikasi": "Kurang Layak/Cukup/Baik/Sangat Baik/Siap Publikasi"
}}

Daftar pustaka:
\"\"\"{reference_texts[:15000]}\"\"\"
""".strip()
