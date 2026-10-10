# Reviu Artikel Ilmiah AI

Aplikasi web Flask untuk menganalisis dan merevisi artikel ilmiah `.docx`
dengan OpenAI Responses API. Aplikasi ini ditujukan untuk dijalankan secara
lokal di Windows dan, bila perlu diakses orang lain, dipublikasikan sementara
melalui tunnel ngrok. Arsitekturnya BYOK murni: setiap pengguna memakai
API key OpenAI miliknya sendiri dan menanggung biaya pada akun masing-masing.
Key dienkripsi di backend, dikaitkan dengan `user_id`, dan tetap tersedia setelah
logout/login ulang sampai pengguna mengganti atau menghapusnya.

## Fitur utama

- Registrasi/login dengan akun persisten, password ter-hash, proteksi CSRF,
  cookie aman, dan `Cache-Control: no-store`.
- Isolasi file unggahan, hasil JSON, PDF, session, dan ciphertext API key per
  pengguna. Tidak ada API key administrator atau fallback key bersama.
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
├── jalankan.bat
├── .env.example
├── migrations/
│   └── 001_auth_session_and_encrypted_api_keys.sql
├── static/
│   └── styles.css
├── templates/
│   ├── login.html
│   ├── register.html
│   ├── api_key.html
│   ├── csrf_error.html
│   ├── index.html
│   └── result.html
└── tests/
    ├── conftest.py
    ├── docx_fixtures.py
    ├── test_app.py
    ├── test_structure.py
    ├── test_citations.py
    ├── test_adaptive.py
    ├── test_modes.py
    └── test_analysis_flow.py
```

Direktori `instance/`, `flask_session/`, `uploads/`, dan `output/` dibuat saat
aplikasi berjalan dan tidak boleh di-commit.

## Versi Python

Gunakan **Python 3.12** melalui virtual environment. Jangan memakai Python 3.14
apabila ada dependensi yang belum kompatibel dengannya; versi paket pada
`requirements.txt` saat ini sudah teruji berjalan, tetapi 3.12 tetap menjadi
versi yang direkomendasikan dan paling aman. Unduh Python 3.12 dari
python.org bila belum terpasang.

## Menjalankan secara lokal (Windows)

Semua perintah di bawah dijalankan di Command Prompt (CMD) dari folder proyek.

1. Buat virtual environment `.venv` (sekali saja):

```bat
py -3.12 -m venv .venv
```

Jika launcher `py` tidak mengenali 3.12, pakai `python -m venv .venv`
(pastikan `python --version` bukan versi yang bermasalah dengan dependensi).

2. Aktifkan `.venv`:

```bat
.venv\Scripts\activate
```

(Di PowerShell gunakan `.\.venv\Scripts\Activate.ps1`.)

3. Instal seluruh dependensi:

```bat
pip install -r requirements.txt
```

4. Salin `.env.example` menjadi `.env`, lalu ganti `FLASK_SECRET_KEY` dengan
   nilai acak. Untuk menjaga API key pengguna tetap terbaca antar-restart,
   buat juga `API_KEY_ENCRYPTION_KEY`:

```bat
copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

File `.env` diabaikan Git. Jangan menaruh nilai rahasia di file yang di-commit.

5. Jalankan aplikasi:

```bat
python app.py
```

Aplikasi otomatis membuat tabel database SQLite yang belum ada, lalu melayani
di `http://127.0.0.1:5000` (host `127.0.0.1`, port `5000`, debug nonaktif).
Buka alamat tersebut, buat akun, login, lalu masukkan API key OpenAI.

## Publikasi sementara dengan ngrok

1. Biarkan `python app.py` tetap berjalan di CMD pertama.
2. Buka **CMD kedua**, lalu jalankan:

```bat
ngrok http 5000
```

3. Bagikan URL `https://....ngrok-free.app` yang ditampilkan ngrok. URL ini
   berubah setiap ngrok dimulai ulang (kecuali memakai domain ngrok berbayar).
4. Tutup jendela ngrok untuk menghentikan publikasi.

Alternatif: jalankan `jalankan.bat` untuk membuka kedua jendela (Flask dan
ngrok) sekaligus. Skrip ini memakai Python dari `.venv` sehingga tidak
bergantung pada Python sistem.

## Menjalankan test

```bat
python -m pytest tests -q
```

Pemanggilan OpenAI dalam test di-mock sehingga tidak memakai saldo API.

## Environment variable

| Variabel | Wajib | Keterangan |
| --- | --- | --- |
| `FLASK_SECRET_KEY` | Disarankan | Kunci tetap untuk session dan CSRF; gunakan nilai acak panjang. `SECRET_KEY` didukung sebagai alias kompatibilitas. |
| `API_KEY_ENCRYPTION_KEY` | Disarankan | Kunci Fernet untuk mengenkripsi/dekripsi API key pengguna. Tanpa nilai ini, kunci dev diturunkan dari `FLASK_SECRET_KEY`. Jangan ganti tanpa re-enkripsi data. |
| `FLASK_ENV` | Tidak | Biarkan `development` untuk lokal/ngrok. |
| `SESSION_TYPE` | Tidak | Default lokal `cachelib` (file di `flask_session/`). |
| `SESSION_LIFETIME_MINUTES` | Tidak | Umur session, default 120 menit. |
| `OPENAI_MODEL` | Tidak | Model OpenAI, default `gpt-5.6`. |
| `OPENAI_TIMEOUT_SECONDS` | Tidak | Timeout request OpenAI, default 300 detik. |
| `OPENAI_MAX_OUTPUT_TOKENS` | Tidak | Batas keluaran tiap request analisis, default 16000. |
| `SECTION_CHUNK_CHARS` | Tidak | Target maksimum karakter per batch paragraf, default 20000. |
| `SCHOLARLY_API_EMAIL` | Tidak | Email kontak untuk Crossref/OpenAlex. |
| `DATABASE_PATH` | Tidak | Lokasi SQLite, default `instance/app.db`. |
| `HOST` / `PORT` | Tidak | Alamat bind `python app.py`, default `127.0.0.1:5000`. |

Aplikasi sengaja tidak membaca atau membutuhkan `OPENAI_API_KEY` administrator.
Setiap panggilan OpenAI mendekripsi key milik `current_user.id` di backend tepat
sebelum membuat client OpenAI.

## Inisialisasi/migrasi database

`python app.py` sudah otomatis membuat tabel yang belum ada di SQLite lokal
(`instance/app.db`). Inisialisasi manual tetap tersedia bila diperlukan:

```bat
flask --app app init-db
```

Perintah ini idempoten dan hanya memakai `CREATE ... IF NOT EXISTS`; tidak ada
`DROP`, `TRUNCATE`, reset, atau delete massal. Skema yang sama juga
terdokumentasi di
[`migrations/001_auth_session_and_encrypted_api_keys.sql`](migrations/001_auth_session_and_encrypted_api_keys.sql).

## Catatan kualitas dan keamanan

- Python melakukan ekstraksi, klasifikasi awal, aturan adaptif, validasi bukti,
  serta pencocokan sitasi secara deterministik. AI melakukan evaluasi akademik
  dan penyusunan saran/revisi.
- Contoh revisi tidak boleh mengarang data. Informasi yang belum tersedia harus
  memakai placeholder dan ditandai memerlukan data penulis.
- Kualitas evaluasi tetap dipengaruhi model yang dipilih dan kualitas struktur
  artikel. Validasi kutipan adalah pengaman, bukan pengganti verifikasi penulis.
- API key pengguna hanya disimpan sebagai ciphertext Fernet di tabel
  `user_api_keys`; plaintext tidak masuk session, cookie, HTML, JavaScript, URL,
  log, atau repository.
- Halaman akun hanya menampilkan status tersimpan dan empat karakter terakhir.
- Kehilangan atau mengganti `API_KEY_ENCRYPTION_KEY` tanpa re-enkripsi membuat
  ciphertext lama tidak dapat dipakai.
- URL ngrok bersifat publik selama tunnel aktif: siapa pun yang mengetahui URL
  dapat membuka halaman login. Bagikan URL hanya kepada pengguna yang dituju
  dan matikan tunnel setelah selesai.
