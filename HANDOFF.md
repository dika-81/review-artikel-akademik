# HANDOFF — Perombakan Sistem Analisis Artikel (18 Juli 2026)

Status: **pengembangan dihentikan di tengah jalan atas permintaan pengguna (kuota menipis).**
Seluruh test lulus (77 passed). Belum di-commit, belum di-push.

## Akar masalah hasil analisis yang dangkal (temuan audit)

1. Rute analisis lama memakai fungsi `analyze_*_with_ai` dengan prompt "revisi singkat"
   (hanya meminta versi revisi), bukan prompt evaluasi. Prompt evaluasi kaya
   (`build_abstract_prompt` dll. di app.py lama) ternyata **tidak pernah dipanggil** (dead code).
2. Ekstraksi DOCX membuang struktur: teks digabung jadi string polos sehingga model
   tidak bisa merujuk paragraf/kalimat, dan kutipan tidak bisa divalidasi.
3. Pencocokan sitasi–daftar pustaka diserahkan penuh ke model (tidak deterministik).
4. Prompt memaksa kriteria kuantitatif (populasi, sampel, validitas, uji statistik)
   untuk semua artikel — sumber false positive pada artikel kualitatif/review/konseptual.
5. Skema output `"kelemahan 1", "kelemahan 2"` membatasi jumlah temuan.

## Perubahan yang SELESAI

### File baru
- `article_structure.py` — ekstraksi DOCX terstruktur: bagian → paragraf bernomor →
  kalimat bernomor dengan ID stabil (`INTRO-P03-S02`), tabel sebagai blok terpisah
  (nomor, baris, sel, bagian), fallback aman untuk artikel tanpa heading,
  `locate_quote()` (eksak/fuzzy ≥0.75 dengan koreksi otomatis/tidak ditemukan) dan
  `validate_findings_quotes()` (temuan tanpa kutipan atau kutipan fiktif ditandai
  tidak valid + keyakinan diturunkan, bukan ditampilkan sebagai bukti benar).
- `article_profile.py` — klasifikasi 15 jenis artikel berbasis multi-dimensi sinyal
  (desain, pengumpulan, analisis, tujuan) dengan bukti teks + lokasi; pilihan pengguna >
  klasifikasi AI > heuristik (`effective_article_type`); mesin aturan adaptif
  (`build_adaptive_rules_text`, `methodology_components_for`) dan filter false positive
  (`filter_false_positive_findings`) yang memindahkan tuntutan tidak relevan
  (mis. "uji normalitas" pada fenomenologi) ke `masalah_dikecualikan`.
- `citations.py` — parser sitasi–referensi **deterministik**: parenthetical, naratif,
  `dkk./et al.`, multi-sitasi dalam satu kurung, organisasi, tahun `2024a/b`, sitasi
  sekunder ("dalam"); hasil: cocok pasti, kemungkinan cocok, sitasi tanpa referensi,
  tahun tidak cocok, referensi tak disitasi, duplikat, tidak lengkap + lokasi
  "Bagian paragraf N kalimat M". Model AI hanya menjelaskan, tidak menentukan pasangan.
- `analysis_schema.py` — skema objek masalah universal (id, prioritas, lokasi, kutipan_asli,
  jenis, kriteria, alasan, dampak, tindakan, contoh + status, keterkaitan, keyakinan);
  `parse_model_json` (perbaikan deterministik: fence, ekstraksi blok `{}`, trailing comma);
  `normalize_section_result` (array dinamis, urut prioritas, cap 15 + ringkasan overflow);
  `merge_section_results` untuk batch.
- `prompts.py` — prompt modular per tahap: aturan bukti universal (4 status informasi,
  larangan mengarang, placeholder eksplisit) + aturan adaptif per jenis + instruksi bagian +
  skema JSON + teks berpenanda `[ID]`. Termasuk prompt klasifikasi, abstrak (banding dengan
  metodologi/hasil/kesimpulan), pendahuluan (peta fungsi paragraf), metodologi (per komponen),
  hasil-pembahasan (interpretasi tabel, analisis tema kualitatif, analisis pembahasan
  per paragraf), kesimpulan (matriks klaim), konsistensi lintas bagian (matriks 9 aspek
  dengan bukti dua sisi), penjelasan sitasi.

### File diubah
- `app.py` — dirombak: workflow 10 tahap (baru: **1. Profil Artikel**, **8. Konsistensi
  Lintas Bagian**); rute generik `run_stage_route`; `call_openai_chat` kini memakai
  `max_output_tokens` (env `OPENAI_MAX_OUTPUT_TOKENS`, default 16000), format JSON
  (`text.format json_object` dengan fallback), dan **deteksi keluaran terpotong**
  (`status == "incomplete"` → error eksplisit, tidak ditampilkan diam-diam);
  `openai_chat_json` dengan satu kali koreksi JSON terkontrol; chunking bagian panjang
  per kelompok paragraf (`SECTION_CHUNK_CHARS`, merge tanpa kehilangan nomor);
  `finalize_section_result` (normalisasi → validasi kutipan → filter adaptif);
  rute baru `/analyze-profile`, `/analyze-cross-section`, `/set-article-type`
  (koreksi jenis artikel per hasil analisis pengguna, bukti deteksi tetap disimpan);
  upload menampilkan "Jenis artikel terdeteksi (heuristik)"; PDF dirombak untuk memuat
  lokasi, kutipan asli, alasan, dampak, saran, contoh revisi, prioritas, catatan data,
  matriks konsistensi, dan hasil pencocokan sitasi. **Keamanan tidak diubah**: login,
  register, session server-side, API key per pengguna, CSRF, isolasi direktori per user,
  logout, guard akses — semua persis seperti sebelumnya (test keamanan lama tetap lulus).
- `templates/result.html` — tampilan baru: panel jenis artikel + dropdown "Ubah Jenis
  Artikel"; ringkasan per tahap (skor, status, jumlah kritis/mayor/minor, 3 prioritas);
  kartu masalah dengan badge (Kritis/Mayor/Minor, Kutipan terverifikasi/dikoreksi/
  Perlu verifikasi, Memerlukan data penulis/Dapat langsung diperbaiki/Template,
  keyakinan), kutipan blockquote, lokasi ber-ID; tabel untuk pemeriksaan unsur, peta
  fungsi paragraf, komponen metodologi, interpretasi tabel, matriks klaim, matriks
  keselarasan; versi revisi collapsible; daftar kriteria dikecualikan; fallback field
  legacy (`abstrak_revisi` dll.) untuk hasil lama.
- `static/styles.css` — ditambah gaya badge, kartu temuan, tabel scrollable, responsif.
- `tests/docx_fixtures.py` (baru) — fixture DOCX sintetis 12 jenis artikel.
- `tests/test_structure.py`, `tests/test_citations.py`, `tests/test_adaptive.py`,
  `tests/test_analysis_flow.py` (baru) — 54 test baru.
- `citations.py` (edit terakhir) — dukungan bentuk "(1970, dalam Santrock, 2011)"
  (penulis di luar kurung, sumber sekunder diambil setelah penanda "dalam").

## Hasil pengujian
`.venv/Scripts/python.exe -m pytest tests/ -q` → **77 passed** (24 s).
Mencakup: 23 test lama (keamanan/isolasi/API key/CSRF/upload) tetap lulus; baru:
penomoran paragraf-kalimat, tabel terlacak, fallback tanpa heading, artikel EN/ID,
temuan tanpa kutipan ditolak, kutipan fiktif ditandai, kutipan fuzzy dikoreksi,
sitasi tanpa referensi / referensi tak disitasi / tahun beda / duplikat / sekunder
terdeteksi, klasifikasi 10 jenis artikel, kualitatif tidak dikritik soal statistik,
kuantitatif tidak dikritik soal saturasi, SLR tanpa partisipan, konseptual tanpa
instrumen, mixed methods dicek integrasinya, klasifikasi tak pasti ditandai,
override jenis artikel oleh pengguna, JSON rusak diperbaiki/ditolak dengan pesan jelas,
keluaran terpotong memunculkan error eksplisit, alur tahap abstrak end-to-end dengan
mock OpenAI (validasi kutipan + badge di HTML).

## Pekerjaan yang BELUM selesai

1. **Uji manual dengan artikel contoh nyata** (`uploads/*.docx`) belum dijalankan —
   baik jalur deterministik (ekstraksi + sitasi) maupun end-to-end dengan API OpenAI
   sungguhan. Daftar validasi kualitas dari pemilik (abstrak vs instrumen, Cohen's d
   tanpa angka, dst.) belum diverifikasi pada artikel contoh.
2. **Menjalankan aplikasi lokal** (`flask run`/`python app.py`) belum dicoba pada sesi ini;
   hanya diuji lewat test client Flask (yang lulus).
3. **Estimasi penggunaan token per artikel** belum diukur (perkiraan kasar: 10 tahap ×
   ~6–15k token input + ~2–8k output ≈ 100–200k token/artikel; perlu diverifikasi).
4. PDF belum diuji visual dengan hasil skema baru (fungsi build lulus impor, belum
   di-generate dari hasil lengkap nyata).
5. `README.md` dan `.env.example` belum diperbarui (variabel baru:
   `OPENAI_MAX_OUTPUT_TOKENS`, `SECTION_CHUNK_CHARS`).
6. Hasil analisis lama (JSON di `output/`) tampil lewat fallback legacy, tetapi tahap
   baru (profil, konsistensi) akan berstatus belum selesai — PDF lama tidak bisa diunduh
   sampai tahap baru dijalankan; perlu keputusan apakah ini perilaku yang diinginkan.
7. Pembersihan kecil: fungsi `pdf_safe_text`/`add_pdf_value` masih generik; beberapa
   import di `app.py` (mis. `MAX_ARTICLE_CHARS`, `login_required`) tidak terpakai.

## Catatan risiko
- Kualitas kedalaman analisis akhirnya bergantung pada model (`OPENAI_MODEL`); prompt
  sudah menuntut bukti, tetapi validasi kutipanlah yang menjadi jaring pengaman.
- Filter false positive berbasis pola teks; kasus di luar pola bisa lolos — daftar pola
  ada di `article_profile.IRRELEVANT_DEMANDS` dan mudah ditambah.
- Jangan commit dokumen pengguna di `uploads/` dan hasil di `output/` ke repository.
