# Reviu Artikel Ilmiah AI

Aplikasi web sederhana untuk mereviu artikel ilmiah `.docx` dengan bantuan AI. Fokus utama aplikasi adalah mengevaluasi dan memperbaiki bagian pendahuluan secara akademik.

## Fitur

- Upload artikel ilmiah dalam format `.docx`.
- Ekstraksi teks dari dokumen Word.
- Analisis menggunakan OpenAI API dengan GPT-5.6, yang dikonfigurasi melalui `OPENAI_MODEL`.
- Revisi bertahap untuk judul, abstrak, pendahuluan, metodologi, hasil dan pembahasan, serta kesimpulan.
- Setiap tahap memakai hasil revisi tahap sebelumnya agar naskah tetap koheren.
- Deteksi bagian metodologi dengan heading `Metode`, `Metodologi`, `Metode Penelitian`, `Research Method`, atau `Methodology`.
- Analisis hasil dan pembahasan dengan AI melalui tombol terpisah di halaman hasil.
- Deteksi bagian hasil dan pembahasan dengan heading `Hasil`, `Hasil Penelitian`, `Results`, `Pembahasan`, `Discussion`, atau `Hasil dan Pembahasan`.
- Pemeriksaan sitasi, kecocokan daftar pustaka, dan format APA 7 sebagai tahap akhir.
- Rekomendasi 10-15 referensi aktual dari OpenAlex dan Crossref, lengkap dengan DOI dan format APA 7.
- Pemilihan referensi tambahan melalui tombol `Tambahkan ke Daftar Pustaka`.
- Unduh laporan akhir dalam format PDF setelah seluruh tahap analisis selesai.
- Hapus hasil reviu dan file terkait melalui halaman hasil.
- Penandaan kutipan yang tidak dapat dicocokkan dengan daftar pustaka sebagai `perlu verifikasi`.
- Penyimpanan hasil analisis ke folder `output`.

## Struktur Proyek

```text
.
├── app.py
├── requirements.txt
├── .env
├── .env.example
├── README.md
├── static/
│   └── styles.css
├── templates/
│   ├── index.html
│   └── result.html
├── uploads/
│   └── .gitkeep
└── output/
    └── .gitkeep
```

## Cara Menjalankan

1. Buat virtual environment.

```bash
python -m venv .venv
```

2. Aktifkan virtual environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Command Prompt:

```cmd
.\.venv\Scripts\activate.bat
```

3. Instal dependensi.

```bash
pip install -r requirements.txt
```

4. Atur konfigurasi OpenAI API di file `.env`.

```env
OPENAI_API_KEY=isi_api_key
OPENAI_MODEL=gpt-5.6
FLASK_SECRET_KEY=ubah-secret-key-ini
```

5. Jalankan aplikasi.

```bash
python app.py
```

6. Buka aplikasi di browser.

```text
http://127.0.0.1:5000
```

## Catatan Penting

- Aplikasi ini tidak melakukan analisis manual berbasis aturan Python. Python hanya membaca dokumen, mengirim teks ke AI, dan menampilkan hasil.
- Aplikasi ini menggunakan OpenAI API secara langsung. Pastikan `OPENAI_API_KEY` berisi API key yang valid.
- AI diinstruksikan untuk tidak mengarang data penelitian, angka, lokasi, metode, temuan, atau kutipan.
- AI diinstruksikan untuk tidak membuat kutipan palsu.
- Jika kutipan tidak dapat diverifikasi dari daftar pustaka di artikel, hasil harus menampilkan `perlu verifikasi`.
- Hasil difokuskan pada teks revisi final yang ringkas dan siap digunakan penulis.

## Bagian Hasil

1. Evaluasi Judul
2. Rekomendasi Judul Baru
3. Evaluasi Abstrak
4. Abstrak Versi Perbaikan
5. Evaluasi Pendahuluan
6. Gap Penelitian
7. Cek Kutipan dan Daftar Pustaka
8. Rumusan Masalah
9. Pendahuluan Versi Revisi

## Modul Metodologi

Setelah analisis awal selesai, halaman hasil menampilkan tombol `Analisis Metodologi dengan AI`. Modul ini akan:

- mendeteksi dan menampilkan teks metodologi dari artikel;
- mengirim teks metodologi dan artikel lengkap ke AI;
- mengevaluasi kelengkapan jenis penelitian, pendekatan, desain, subjek, lokasi, waktu, populasi, sampel, teknik pengumpulan data, instrumen, prosedur, analisis data, validitas, reliabilitas, etika penelitian, dan kesesuaian metode dengan tujuan atau rumusan masalah;
- menampilkan kelemahan, komponen yang belum ada, saran perbaikan, catatan yang perlu dilengkapi penulis, dan metodologi versi revisi.

AI diinstruksikan untuk tidak mengarang sampel, lokasi, instrumen, hasil uji validitas, hasil uji reliabilitas, atau teknik analisis yang tidak tersedia dalam artikel.

## Modul Hasil dan Pembahasan

Setelah analisis awal selesai, halaman hasil menampilkan tombol `Analisis Hasil dan Pembahasan dengan AI`. Modul ini memakai hasil analisis sebelumnya untuk memeriksa keselarasan:

- judul penelitian;
- tujuan penelitian;
- rumusan masalah;
- gap penelitian;
- metodologi;
- hasil penelitian;
- pembahasan.

Output modul ini meliputi evaluasi hasil penelitian, evaluasi pembahasan, kesesuaian dengan rumusan masalah, metodologi, tujuan penelitian, inkonsistensi, saran perbaikan, hasil versi revisi, pembahasan versi revisi, dan catatan untuk penulis.

AI diinstruksikan untuk tidak mengarang data penelitian, angka statistik, hasil observasi, hasil wawancara, tabel, atau grafik. Jika data tidak tersedia, AI harus menulis `Bagian ini memerlukan data tambahan dari penulis dan tidak dapat direvisi secara penuh tanpa data asli.`

## Modul Konsistensi Artikel Menyeluruh

Setelah analisis awal selesai, halaman hasil menampilkan tombol `Cek Konsistensi Artikel Secara Menyeluruh`. Modul ini memakai isi artikel lengkap dan hasil analisis dari modul sebelumnya untuk membandingkan:

- judul;
- abstrak;
- pendahuluan;
- gap penelitian;
- tujuan penelitian;
- rumusan masalah;
- metodologi;
- hasil;
- pembahasan;
- kesimpulan jika tersedia;
- daftar pustaka.

Output modul ini meliputi ringkasan kualitas konsistensi, skor 1-100, peta keselarasan artikel, daftar inkonsistensi, dampak akademik, prioritas perbaikan, rekomendasi revisi menyeluruh, dan checklist kesiapan artikel untuk submit jurnal.

AI diinstruksikan untuk tidak mengarang data, tidak menambah hasil penelitian baru, dan tidak membuat kutipan palsu. Jika bagian tertentu tidak tersedia, AI harus menulis `Bagian ini belum tersedia dalam artikel sehingga konsistensinya belum dapat dinilai secara penuh.`

## Modul Reviewer Jurnal Simulator

Halaman hasil juga menyediakan tombol `Reviewer Jurnal Simulator`. Modul ini meminta AI bertindak sebagai reviewer jurnal bereputasi dan menilai judul, abstrak, pendahuluan, metodologi, hasil dan pembahasan, kesimpulan, serta daftar pustaka.

Output modul ini meliputi kelebihan artikel, kelemahan artikel, novelty, signifikansi penelitian, kekuatan dan kelemahan metodologi, kualitas pembahasan, kualitas referensi, kualitas bahasa akademik, potensi publikasi, keputusan reviewer, dan alasan keputusan secara rinci.

## Modul Referensi dan Sitasi

Halaman hasil menyediakan tombol `Analisis Referensi dan Sitasi`. Modul ini memeriksa semua sitasi dalam naskah, kecocokannya dengan daftar pustaka, referensi yang tidak pernah disitasi, referensi duplikat, kelengkapan referensi, usia referensi, kualitas sumber, dan kepatuhan terhadap APA 7th Edition.

Output modul ini meliputi ringkasan kualitas referensi, statistik jenis referensi, statistik usia referensi, sitasi bermasalah, referensi bermasalah, referensi tidak pernah disitasi, sitasi tanpa referensi, referensi duplikat, evaluasi kualitas referensi, evaluasi APA 7, daftar perbaikan, skor kualitas referensi, dan tingkat kesiapan referensi untuk publikasi.

AI diinstruksikan untuk tidak mengarang DOI, URL, atau data bibliografi. Jika keberadaan atau kredibilitas referensi tidak dapat dipastikan dari artikel, AI harus menulis `Referensi perlu diverifikasi pada sumber asli.`

## Modul Novelty dan Kontribusi Ilmiah

Halaman hasil menyediakan tombol `Analisis Novelty dan Kontribusi`. Modul ini mengevaluasi kebaruan penelitian, kekuatan gap, kontribusi teoretis, kontribusi praktis, kontribusi metodologis, risiko akademik, serta kelayakan kontribusi untuk publikasi.

Output modul ini meliputi ringkasan novelty, ringkasan kontribusi ilmiah, evaluasi gap, novelty yang teridentifikasi, kontribusi teoretis, praktis, dan metodologis, risiko akademik, saran penguatan novelty dan kontribusi, skor novelty, skor kontribusi ilmiah, tingkat kebaruan Level 1-7, dan kategori kelayakan kontribusi.

AI diinstruksikan untuk tidak mengarang penelitian terdahulu, teori, hasil penelitian, atau data baru. Jika informasi belum cukup untuk menilai novelty secara penuh, AI harus menulis `Novelty memerlukan verifikasi lebih lanjut melalui penelusuran literatur yang lebih luas.`

## Modul Kesiapan Submit Artikel

Tombol `Cek Kesiapan Submit Artikel` menjalankan pemeriksaan akhir seperti editor jurnal. Modul ini menggabungkan seluruh hasil analisis sebelumnya untuk menilai struktur artikel, kualitas ilmiah, konsistensi, referensi, novelty, kontribusi ilmiah, dan risiko saat review.

Output modul ini meliputi ringkasan evaluasi artikel, checklist kesiapan submit, skor kesiapan submit, kategori kelayakan, kelebihan artikel, kelemahan artikel, risiko penolakan, prioritas revisi, dan rekomendasi akhir editor.

Kategori kelayakan yang digunakan: `Belum Layak Submit`, `Perlu Revisi Besar`, `Perlu Revisi Minor`, `Siap Submit Nasional`, `Siap Submit SINTA`, `Siap Submit Internasional`, atau `Sangat Siap Submit`.
