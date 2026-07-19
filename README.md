# Reviu Artikel Ilmiah AI

Aplikasi web Flask untuk menganalisis dan merevisi artikel ilmiah `.docx`
dengan OpenAI Responses API. Arsitekturnya BYOK murni: setiap pengguna memakai
API key OpenAI miliknya sendiri dan menanggung biaya pada akun masing-masing.
Key dienkripsi di backend, dikaitkan dengan `user_id`, dan tetap tersedia setelah
logout/login ulang sampai pengguna mengganti atau menghapusnya.

## Fitur utama

- Registrasi/login dengan akun PostgreSQL persisten di production, password
  ter-hash, proteksi CSRF, cookie aman, dan `Cache-Control: no-store`.
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
├── render.yaml
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

3. Salin `.env.example` menjadi `.env`, lalu ganti `FLASK_SECRET_KEY`. Untuk
   menguji data API key yang bertahan antar-restart lokal, buat juga
   `API_KEY_ENCRYPTION_KEY`.

```powershell
Copy-Item .env.example .env
```

File `.env` diabaikan Git. Jangan pernah menaruh nilai rahasia di file yang
di-commit atau menyalinnya ke issue/log.

Fernet key dapat dibuat secara lokal dengan:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Salin hasilnya hanya ke `.env` lokal yang tidak dilacak atau secret manager host.

4. Inisialisasi database lokal satu kali, lalu jalankan aplikasi.

```powershell
flask --app app init-db
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
| `FLASK_SECRET_KEY` | Ya di production | Rahasia. Kunci tetap untuk session dan CSRF; gunakan nilai acak panjang dan jangan diganti setiap deploy. `SECRET_KEY` didukung sebagai alias kompatibilitas. |
| `DATABASE_URL` | Ya di production | Rahasia karena berisi kredensial. Dapat menunjuk ke Render, Supabase, atau PostgreSQL eksternal lain. Awalan lama `postgres://` dinormalisasi otomatis. |
| `API_KEY_ENCRYPTION_KEY` | Ya di production | Rahasia Fernet untuk mengenkripsi/dekripsi key pengguna. Jangan ganti tanpa prosedur rotasi/re-enkripsi data. |
| `FLASK_ENV` | Ya di Render | Set `production`; jika tidak diatur, aplikasi menganggap development lokal. |
| `FLASK_DEBUG` | Tidak | Default `0`. Jangan aktifkan di production karena debugger interaktif dapat mengekspos data request. |
| `SESSION_TYPE` | Ya di production | Gunakan `sqlalchemy` agar session tersimpan di PostgreSQL; `cachelib` hanya untuk lokal. |
| `SESSION_LIFETIME_MINUTES` | Tidak | Umur session, default 120 menit. |
| `OPENAI_MODEL` | Tidak | Model OpenAI, default `gpt-5.6`. |
| `OPENAI_TIMEOUT_SECONDS` | Tidak | Timeout request OpenAI, default 300 detik. |
| `OPENAI_MAX_OUTPUT_TOKENS` | Tidak | Batas keluaran tiap request analisis, default 16000. |
| `SECTION_CHUNK_CHARS` | Tidak | Target maksimum karakter per batch paragraf, default 20000. |
| `SCHOLARLY_API_EMAIL` | Tidak | Email kontak untuk Crossref/OpenAlex. |
| `DATABASE_PATH` | Lokal saja | Lokasi SQLite development/test, default `instance/app.db`. Di production nilai ini tidak dipakai. |

Aplikasi sengaja tidak membaca atau membutuhkan `OPENAI_API_KEY` administrator.
Setiap panggilan OpenAI mendekripsi key milik `current_user.id` di backend tepat
sebelum membuat client OpenAI.

## Deployment

`render.yaml` dapat dipakai sebagai Blueprint Render. Konfigurasi pokok:

- build command: `pip install -r requirements.txt && flask --app app init-db`;
- start command: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 360 app:app`;
- health check: `/healthz`;
- branch: `main`;
- `DATABASE_URL` dan `API_KEY_ENCRYPTION_KEY` diisi manual sebagai secret;
- session production memakai tabel PostgreSQL (`SESSION_TYPE=sqlalchemy`);
- secret `FLASK_SECRET_KEY` dibuat sekali oleh Blueprint;
- tidak ada resource database yang diikat oleh Blueprint, sehingga
  `DATABASE_URL` dapat memakai PostgreSQL eksternal seperti Supabase;
- setiap build menjalankan `flask --app app init-db` setelah dependency terpasang;
  perintah ini aman dijalankan ulang dan hanya membuat tabel yang belum ada.

## Inisialisasi/migrasi database

Build Render otomatis menjalankan perintah berikut dengan kredensial database
yang disimpan di environment:

```powershell
pip install -r requirements.txt && flask --app app init-db
```

Untuk inisialisasi/migrasi manual, jalankan `flask --app app init-db` atau
[`migrations/001_auth_session_and_encrypted_api_keys.sql`](migrations/001_auth_session_and_encrypted_api_keys.sql)
melalui SQL editor/`psql` milik penyedia PostgreSQL.

Keduanya idempoten dan hanya memakai `CREATE ... IF NOT EXISTS`; tidak ada
`DROP`, `TRUNCATE`, reset, atau delete massal. Migrasi membuat tabel `users`,
`sessions`, dan `user_api_keys`. Build command tidak mencetak environment
variable atau nilai secret.

Filesystem Render bersifat ephemeral. Karena itu akun dan session berada di
PostgreSQL, bukan SQLite atau `flask_session/`. File unggahan, hasil JSON, dan
PDF saat ini masih berada di filesystem lokal sehingga tetap dapat hilang
ketika Free Web Service tidur, restart, atau redeploy; gunakan object storage
jika artefak tersebut juga harus permanen. Jangan mengandalkan Render Free
PostgreSQL untuk data permanen karena database tersebut kedaluwarsa; gunakan
PostgreSQL eksternal/berbayar dan backup terjadwal untuk penggunaan sungguhan.

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
