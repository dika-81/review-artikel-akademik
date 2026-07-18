# Reviu Artikel Ilmiah AI

Aplikasi web Flask untuk menganalisis dan merevisi artikel ilmiah `.docx`
dengan OpenAI Responses API. Setiap pengguna memakai API key OpenAI miliknya
sendiri; key disimpan sementara di server-side session dan dihapus saat logout
atau sesi berakhir.

## Fitur utama

- Registrasi/login, password ter-hash, proteksi CSRF, cookie aman, dan
  `Cache-Control: no-store`.
- Isolasi file unggahan, hasil JSON, PDF, session, dan API key per pengguna.
- Ekstraksi DOCX terstruktur menjadi bagian, paragraf, kalimat, dan tabel dengan
  ID lokasi stabil seperti `MET-P02-S01`.
- Deteksi jenis artikel berbasis beberapa dimensi bukti, dapat dikoreksi oleh
  pengguna:
  - kuantitatif eksperimen/survei;
  - kualitatif (studi kasus/tematik, fenomenologi, etnografi, grounded theory,
    analisis isi);
  - mixed methods;
  - PTK;
  - R&D/DBR;
  - studi literatur naratif;
  - systematic/scoping review dan meta-analisis;
  - artikel konseptual/teoretis;
  - penelitian evaluatif.
- Kriteria analisis dan prompt menyesuaikan jenis artikel. Contohnya, artikel
  kualitatif tidak dituntut memiliki uji normalitas dan systematic review tidak
  dituntut memiliki partisipan lapangan.
- Prompt evaluasi rinci berbasis bukti: lokasi, kutipan asli, prioritas,
  alasan, dampak, tindakan revisi, contoh revisi, status data, dan keyakinan.
- Validasi kutipan temuan terhadap teks DOCX. Kutipan fiktif/tidak ditemukan
  ditandai untuk verifikasi, bukan ditampilkan sebagai bukti benar.
- Pencocokan sitasi-daftar pustaka deterministik di Python; AI hanya
  menjelaskan masalah dan mengevaluasi format APA 7.
- Bagian panjang diproses per kelompok paragraf tanpa mengubah nomor lokasi.
- Keluaran model yang terpotong atau JSON yang tetap rusak setelah satu kali
  koreksi ditolak dengan pesan eksplisit.
- Rekomendasi 10–15 referensi aktual dari OpenAlex dan Crossref, lengkap dengan
  DOI dan format APA 7.
- Laporan PDF setelah workflow selesai. Hasil lengkap dari versi lama tetap
  dapat ditampilkan dan diunduh.

## Workflow analisis

1. Profil Artikel
2. Judul
3. Abstrak
4. Pendahuluan
5. Metodologi
6. Hasil dan Pembahasan
7. Kesimpulan
8. Konsistensi Lintas Bagian
9. Sitasi dan APA 7
10. Rekomendasi Referensi Tambahan

Tahap abstrak membandingkan abstrak dengan metodologi, hasil, dan kesimpulan.
Tahap kesimpulan menguji klaim terhadap hasil. Tahap konsistensi memeriksa
keselarasan antarbagiannya dengan bukti ber-ID dari kedua sisi.

## Struktur proyek

```text
.
├── app.py
├── analysis_schema.py
├── article_profile.py
├── article_structure.py
├── citations.py
├── prompts.py
├── requirements.txt
├── render.yaml
├── .env.example
├── static/
│   └── styles.css
├── templates/
│   ├── login.html
│   ├── register.html
│   ├── api_key.html
│   ├── index.html
│   └── result.html
└── tests/
    ├── conftest.py
    ├── docx_fixtures.py
    ├── test_app.py
    ├── test_structure.py
    ├── test_citations.py
    ├── test_adaptive.py
    └── test_analysis_flow.py
```

Direktori `instance/`, `flask_session/`, `uploads/`, dan `output/` dibuat saat
aplikasi berjalan dan tidak boleh di-commit.

## Menjalankan secara lokal

1. Buat dan aktifkan virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Instal dependensi.

```powershell
pip install -r requirements.txt
```

3. Salin `.env.example` menjadi `.env`, lalu ganti `SECRET_KEY`.

```powershell
Copy-Item .env.example .env
```

Jangan menaruh `OPENAI_API_KEY` dalam `.env`; pengguna memasukkan key miliknya
sendiri setelah login.

4. Jalankan aplikasi.

```powershell
python app.py
```

Buka `http://127.0.0.1:5000`, buat akun, login, lalu masukkan API key OpenAI.

## Menjalankan test

```powershell
python -m pytest tests\ -q
```

Pemanggilan OpenAI dalam test di-mock sehingga tidak memakai saldo API.

## Environment variable

| Variabel | Wajib | Keterangan |
| --- | --- | --- |
| `SECRET_KEY` | Ya di production | Kunci penandatangan session cookie; gunakan nilai acak panjang. |
| `FLASK_ENV` | Tidak | `development` untuk lokal; `production` adalah default. |
| `SESSION_TYPE` | Tidak | `filesystem` (default) atau `redis`. |
| `REDIS_URL` | Jika Redis | URL Redis untuk session server-side. |
| `SESSION_LIFETIME_MINUTES` | Tidak | Umur session, default 120 menit. |
| `OPENAI_MODEL` | Tidak | Model OpenAI, default `gpt-5.6`. |
| `OPENAI_TIMEOUT_SECONDS` | Tidak | Timeout request OpenAI, default 300 detik. |
| `OPENAI_MAX_OUTPUT_TOKENS` | Tidak | Batas keluaran tiap request analisis, default 16000. |
| `SECTION_CHUNK_CHARS` | Tidak | Target maksimum karakter per batch paragraf, default 20000. |
| `SCHOLARLY_API_EMAIL` | Tidak | Email kontak untuk Crossref/OpenAlex. |
| `DATABASE_PATH` | Tidak | Lokasi SQLite akun, default `instance/app.db`. |

`OPENAI_API_KEY` milik pemilik aplikasi tidak diperlukan.

## Deployment

`render.yaml` dapat dipakai sebagai Blueprint Render. Konfigurasi pokok:

- build command: `pip install -r requirements.txt`;
- start command: `gunicorn app:app`;
- health check: `/healthz`;
- environment minimum: `SECRET_KEY`, `FLASK_ENV=production`, dan
  `OPENAI_MODEL`.

Untuk production, gunakan `SESSION_TYPE=redis` dan `REDIS_URL`. Filesystem
Render bersifat ephemeral; gunakan disk/database persisten bila akun, unggahan,
dan hasil analisis harus bertahan setelah redeploy.

## Catatan kualitas dan keamanan

- Python melakukan ekstraksi, klasifikasi awal, aturan adaptif, validasi bukti,
  serta pencocokan sitasi secara deterministik. AI melakukan evaluasi akademik
  dan penyusunan saran/revisi.
- Contoh revisi tidak boleh mengarang data. Informasi yang belum tersedia harus
  memakai placeholder dan ditandai memerlukan data penulis.
- Kualitas evaluasi tetap dipengaruhi model yang dipilih dan kualitas struktur
  artikel. Validasi kutipan adalah pengaman, bukan pengganti verifikasi penulis.
- API key tidak ditulis ke database, file, log, HTML, atau cookie browser.
