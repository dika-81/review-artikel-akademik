/*
 * Pengendali aplikasi versi web (GitHub Pages).
 *
 * Rute (hash): #/ beranda, #/reviu/<id> hasil reviu, #/pengaturan.
 * Halaman hasil dirender dari templates/result.html oleh mesin Python;
 * form dan tautan di dalamnya memakai action "#act/<endpoint>" (padanan
 * rute Flask) yang ditangkap di sini.
 */

import { ReviewEngine } from "./engine-client.js";
import * as store from "./storage.js";

const MAX_FILE_BYTES = 16 * 1024 * 1024;

// Padanan WORKFLOW_STEPS di app.py: endpoint -> kunci tahap.
const STAGE_ENDPOINTS = {
  analyze_profile: "profil_artikel",
  analyze_title: "judul",
  analyze_abstract: "abstrak",
  analyze_introduction: "pendahuluan",
  analyze_methodology: "metodologi",
  analyze_results_discussion: "hasil_pembahasan",
  analyze_conclusion: "kesimpulan",
  analyze_cross_section: "konsistensi",
  analyze_reference_citation: "sitasi_apa",
};
const STAGE_KEYS = [...Object.values(STAGE_ENDPOINTS), "referensi_tambahan"];
const STAGE_LABELS = {
  profil_artikel: "Profil Artikel",
  judul: "Judul",
  abstrak: "Abstrak",
  pendahuluan: "Pendahuluan",
  metodologi: "Metodologi",
  hasil_pembahasan: "Hasil dan Pembahasan",
  kesimpulan: "Kesimpulan",
  konsistensi: "Konsistensi Lintas Bagian",
  sitasi_apa: "Sitasi dan APA 7",
  referensi_tambahan: "Rekomendasi Referensi Tambahan",
};

const view = document.getElementById("view");
const statusBox = document.getElementById("engine-status");
const statusText = document.getElementById("engine-status-text");
const busy = document.getElementById("busy");
const busyText = document.getElementById("busy-text");

let engineState = "loading";
let engineError = "";
let isBusy = false;
let flash = [];

const engine = new ReviewEngine({
  onProgress: (text) => {
    if (isBusy) busyText.textContent = text;
    else if (engineState === "loading") statusText.textContent = text;
  },
});

function watchEngine() {
  engineState = "loading";
  setStatus("loading", "Memuat mesin…");
  engine.ready.then(
    () => {
      engineState = "ready";
      setStatus("ready", "Mesin siap");
      refreshAfterEngineChange();
    },
    (error) => {
      engineState = "error";
      engineError = error.message;
      setStatus("error", "Mesin gagal dimuat");
      refreshAfterEngineChange();
    },
  );
}

// Halaman hasil perlu dirender ulang; beranda/pengaturan cukup diperbarui
// di tempat agar file yang sudah dipilih pengguna tidak hilang.
function refreshAfterEngineChange() {
  if (isBusy) return;
  if (view.dataset.reviewId || /^#\/reviu\//.test(location.hash)) {
    route();
    return;
  }
  const notice = view.querySelector(".engine-notice");
  if (notice) notice.outerHTML = engineNotice();
  if (engineState === "ready") {
    view.querySelector("#upload-form button[type=submit]")?.removeAttribute("disabled");
    if (store.loadApiKey()) view.querySelector("[data-test-ai]")?.removeAttribute("disabled");
  }
}

function setStatus(state, text) {
  statusBox.dataset.state = state;
  statusText.textContent = text;
}

function engineSettings() {
  return { ...store.loadSettings(), api_key: store.loadApiKey() };
}

// ---------------------------------------------------------------------------
// Utilitas
// ---------------------------------------------------------------------------

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

function stem(filename) {
  return String(filename || "reviu").replace(/\.[^.]+$/, "") || "reviu";
}

function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function flashHtml(messages, success = false) {
  if (!messages.length) return "";
  return `<div class="alert${success ? " is-success" : ""}">${messages
    .map((message) => `<p>${esc(message).replace(/\n/g, "<br>")}</p>`)
    .join("")}</div>`;
}

function takeFlash() {
  const messages = flash;
  flash = [];
  return messages;
}

function completedStages(result) {
  return STAGE_KEYS.filter((key) => result && result[key]).length;
}

function engineNotice() {
  if (engineState === "ready") return `<div class="engine-notice" hidden></div>`;
  if (engineState === "error") {
    return `<div class="alert engine-notice"><p>Mesin analisis gagal dimuat: ${esc(engineError)}</p>
      <p>Periksa koneksi internet, lalu <a href="" data-reload>muat ulang halaman</a>.</p></div>`;
  }
  return `<div class="info-box engine-notice"><p>Mesin analisis sedang dimuat (sekitar 10–30 detik pada
    kunjungan pertama). Anda sudah bisa memilih file.</p></div>`;
}

function setBusy(on, text = "Menyiapkan permintaan…") {
  isBusy = on;
  busy.hidden = !on;
  busyText.textContent = text;
  if (on) document.getElementById("busy-cancel").focus();
}

async function runBusy(text, action) {
  if (isBusy) return null;
  setBusy(true, text);
  try {
    return await action();
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------------------
// Beranda
// ---------------------------------------------------------------------------

async function renderHome() {
  const messages = takeFlash();
  let reviews = [];
  let storageError = "";
  try {
    reviews = await store.listReviews();
  } catch (error) {
    storageError = "Penyimpanan browser tidak tersedia (mode privat atau data situs diblokir). "
      + "Hasil reviu tidak dapat disimpan.";
  }
  const hasKey = Boolean(store.loadApiKey());

  view.innerHTML = `
    <main class="shell">
      <section class="panel upload-panel">
        <div>
          <p class="eyebrow">Reviewer Artikel Ilmiah</p>
          <h1>AI Academic Review Assistant</h1>
          <h4>Property of PGSD UPI Serang</h4>
          <p class="lead">
            Evaluasi kualitas artikel ilmiah Anda secara komprehensif melalui analisis struktur,
            metodologi, konsistensi, referensi, kontribusi ilmiah, dan kesiapan publikasi. Sistem
            dirancang untuk membantu penulis meningkatkan mutu naskah sesuai standar akademik dan
            etika publikasi, bukan untuk menghasilkan atau memfabrikasi karya ilmiah secara otomatis.
          </p>
          <p class="lead note">
            AI berperan sebagai asisten reviewer dan editor akademik yang memberikan masukan,
            identifikasi kelemahan, serta rekomendasi perbaikan. Seluruh isi, data penelitian,
            interpretasi hasil, dan tanggung jawab ilmiah tetap berada pada penulis.
          </p>
        </div>

        <div class="info-box">
          <p><strong>Data Anda tetap di browser ini.</strong> Artikel dan hasil reviu disimpan di
            browser perangkat ini saja, tidak di server. Gunakan <em>Ekspor</em> untuk cadangan atau
            memindahkan ke perangkat lain.</p>
          <p>Analisis memakai API key OpenAI milik Anda; biaya ditanggung akun OpenAI Anda.
            Artikel dikirim langsung dari browser ke OpenAI.</p>
        </div>

        ${hasKey ? "" : `<div class="alert"><p>API key OpenAI belum diisi.
          <a href="#/pengaturan">Isi API key di halaman Pengaturan</a> sebelum menjalankan analisis.</p></div>`}
        ${storageError ? `<div class="alert"><p>${esc(storageError)}</p></div>` : ""}
        ${engineNotice()}
        ${flashHtml(messages)}

        <form class="upload-form" id="upload-form">
          <label for="article">File artikel ilmiah (.docx)</label>
          <input id="article" name="article" type="file" accept=".docx" required>

          <fieldset class="mode-choice">
            <legend>Mode Analisis</legend>
            <label class="mode-option">
              <input type="radio" name="mode_analisis" value="ringkas" checked>
              <span>
                <strong>Analisis Ringkas</strong>
                <small>Menampilkan komentar singkat hanya pada bagian yang paling perlu direvisi.</small>
              </span>
            </label>
            <label class="mode-option">
              <input type="radio" name="mode_analisis" value="mendalam">
              <span>
                <strong>Analisis Mendalam</strong>
                <small>Menampilkan alasan akademik, dampak, dan contoh revisi untuk masalah penting.</small>
              </span>
            </label>
          </fieldset>

          <button type="submit" ${engineState === "ready" ? "" : "disabled"}>
            <span class="button-status" aria-hidden="true">▶</span>
            Upload Artikel
          </button>
        </form>

        <section class="workflow">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Tersimpan di browser ini</p>
              <h2>Reviu Saya</h2>
            </div>
            <div class="review-actions">
              <button type="button" class="secondary-button small-button" data-import>Impor JSON</button>
              ${reviews.length ? `<button type="button" class="secondary-button small-button" data-export-all>Ekspor semua</button>` : ""}
            </div>
          </div>
          <input type="file" accept=".json,application/json" id="import-file" hidden>
          ${reviews.length ? `<ul class="review-list">${reviews.map(reviewItemHtml).join("")}</ul>`
            : `<p class="note">Belum ada reviu tersimpan. Unggah artikel untuk memulai.</p>`}
        </section>
      </section>
    </main>`;
}

function reviewItemHtml(review) {
  const done = completedStages(review.result);
  const percent = Math.round((done / STAGE_KEYS.length) * 100);
  return `
    <li class="review-item">
      <h3>${esc(review.filename)}</h3>
      <p class="note">Dibuat ${esc(formatDate(review.created_at))} · diperbarui
        ${esc(formatDate(review.updated_at))} · ${done}/${STAGE_KEYS.length} tahap selesai</p>
      <div class="progress-bar" aria-hidden="true"><span style="width:${percent}%"></span></div>
      <div class="review-actions">
        <a class="secondary-button small-button download-button" href="#/reviu/${encodeURIComponent(review.id)}">Buka</a>
        <button type="button" class="secondary-button small-button" data-export="${esc(review.id)}">Ekspor</button>
        <button type="button" class="danger-button small-button" data-delete="${esc(review.id)}">Hapus</button>
      </div>
    </li>`;
}

async function handleUpload(form) {
  const file = form.article.files[0];
  if (!file) {
    flash.push("Silakan pilih file artikel .docx terlebih dahulu.");
    return renderHome();
  }
  if (!file.name.toLowerCase().endsWith(".docx")) {
    flash.push("Format file harus .docx.");
    return renderHome();
  }
  if (file.size > MAX_FILE_BYTES) {
    flash.push("Ukuran file melebihi 16 MB.");
    return renderHome();
  }
  const mode = form.mode_analisis.value;
  const buffer = await file.arrayBuffer();
  const reply = await runBusy("Membaca struktur artikel…", () =>
    engine.call("startReview", { docx: new Uint8Array(buffer), filename: file.name, mode }),
  ).catch((error) => ({ ok: false, error: error.message }));
  if (!reply) return;
  if (!reply.ok) {
    flash.push(reply.error);
    return renderHome();
  }
  const review = {
    id: store.newReviewId(),
    filename: reply.result._filename || file.name,
    created_at: new Date().toISOString(),
    result: reply.result,
    docx: buffer,
  };
  try {
    await store.saveReview(review);
    store.requestPersistentStorage();
  } catch (error) {
    flash.push("Hasil tidak dapat disimpan di browser ini: " + error.message);
    return renderHome();
  }
  flash.push(reply.message);
  location.hash = `#/reviu/${encodeURIComponent(review.id)}`;
}

async function exportReview(id) {
  const reviews = id ? [await store.getReview(id)].filter(Boolean) : await store.listReviews();
  if (!reviews.length) return;
  const name = id
    ? `${stem(reviews[0].filename)}-reviu.json`
    : `reviu-artikel-${new Date().toISOString().slice(0, 10)}.json`;
  download(name, store.exportReviews(reviews), "application/json");
}

async function importFile(file) {
  try {
    const count = await store.importReviews(await file.text());
    flash.push(count ? `${count} reviu berhasil diimpor.` : "Tidak ada reviu yang dapat diimpor.");
  } catch (error) {
    flash.push(error.message);
  }
  renderHome();
}

async function removeReview(id, back = false) {
  const review = await store.getReview(id);
  if (!review) return;
  if (!confirm(`Hapus hasil reviu "${review.filename}" dan file artikelnya dari browser ini?`)) return;
  await store.deleteReview(id);
  flash.push("Hasil reviu dan file terkait berhasil dihapus.");
  if (back) location.hash = "#/";
  else renderHome();
}

// ---------------------------------------------------------------------------
// Halaman hasil
// ---------------------------------------------------------------------------

async function renderReview(id) {
  const review = await store.getReview(id).catch(() => null);
  if (!review) {
    flash.push("Hasil reviu tidak ditemukan di browser ini.");
    location.hash = "#/";
    return;
  }
  if (engineState !== "ready") {
    view.innerHTML = `<main class="shell"><section class="panel upload-panel">
      <h1>${esc(review.filename)}</h1>${engineNotice()}</section></main>`;
    return;
  }
  const messages = takeFlash();
  let reply;
  try {
    reply = await engine.call("renderResult", { result: review.result, reviewId: id, messages });
  } catch (error) {
    view.innerHTML = `<main class="shell"><section class="panel upload-panel">
      <div class="alert"><p>Hasil tidak dapat ditampilkan: ${esc(error.message)}</p></div>
      <a class="secondary-button" href="#/">Kembali ke Beranda</a></section></main>`;
    return;
  }
  const page = new DOMParser().parseFromString(reply.html, "text/html");
  // Konfirmasi hapus ditangani di sini, bukan lewat atribut onsubmit template.
  page.querySelectorAll("[onsubmit],[onclick]").forEach((node) => {
    node.removeAttribute("onsubmit");
    node.removeAttribute("onclick");
  });
  page.querySelectorAll("script, link").forEach((node) => node.remove());
  if (!review.docx) {
    const notice = page.createElement("div");
    notice.className = "alert result-alert";
    notice.innerHTML = "<p>File artikel tidak ikut tersimpan. Tahap yang belum selesai tidak dapat dijalankan.</p>";
    page.body.querySelector("main")?.prepend(notice);
  }
  view.replaceChildren(...page.body.childNodes);
  view.dataset.reviewId = id;
  // Versi Flask memuat ulang halaman setelah aksi; di sini pesan digulir ke layar.
  if (messages.length) view.querySelector(".result-alert")?.scrollIntoView({ block: "center" });
}

async function handleResultAction(endpoint, formData) {
  const id = view.dataset.reviewId;
  const review = await store.getReview(id);
  if (!review) return;
  const docx = review.docx ? new Uint8Array(review.docx) : null;

  if (endpoint === "index") {
    location.hash = "#/";
    return;
  }
  if (endpoint === "delete_review") {
    await removeReview(id, true);
    return;
  }
  if (endpoint === "download_review") {
    const pdf = await runBusy("Menyusun laporan PDF…", () =>
      engine.call("buildPdf", { result: review.result }),
    ).catch((error) => {
      flash.push(error.message);
      return null;
    });
    if (pdf) download(`${stem(review.filename)}.pdf`, pdf, "application/pdf");
    else if (flash.length) renderReview(id);
    return;
  }

  let call;
  let busyLabel;
  if (STAGE_ENDPOINTS[endpoint] || endpoint === "analyze_reference_recommendations") {
    if (!store.loadApiKey()) {
      flash.push("API key OpenAI belum diisi. Silakan isi API key di halaman Pengaturan.");
      return renderReview(id);
    }
    if (!docx) {
      flash.push("File artikel tidak tersedia. Silakan unggah artikel kembali.");
      return renderReview(id);
    }
    if (endpoint === "analyze_reference_recommendations") {
      busyLabel = "Mencari referensi tambahan…";
      call = () => engine.call("runReferences", { docx, result: review.result });
    } else {
      const stage = STAGE_ENDPOINTS[endpoint];
      busyLabel = `Menganalisis tahap ${STAGE_LABELS[stage]}…`;
      call = () => engine.call("runStage", { docx, result: review.result, stage });
    }
  } else if (endpoint === "set_article_type") {
    call = () => engine.call("setArticleType", {
      result: review.result,
      choice: formData.get("jenis_artikel"),
    });
  } else if (endpoint === "add_recommended_reference") {
    call = () => engine.call("addReference", { result: review.result, doi: formData.get("doi") });
  } else {
    return;
  }

  const reply = busyLabel
    ? await runBusy(busyLabel, call).catch((error) => ({ ok: false, error: error.message }))
    : await call().catch((error) => ({ ok: false, error: error.message }));
  if (!reply) return;
  if (reply.result) {
    review.result = reply.result;
    await store.saveReview(review);
  }
  if (!reply.ok) flash.push(reply.error);
  else if (reply.message) flash.push(reply.message);
  await renderReview(id);
}

// ---------------------------------------------------------------------------
// Pengaturan
// ---------------------------------------------------------------------------

function renderSettings() {
  const settings = store.loadSettings();
  const apiKey = store.loadApiKey();
  const remembered = store.apiKeyRemembered();
  const messages = takeFlash();
  view.innerHTML = `
    <main class="shell">
      <section class="panel upload-panel">
        <div>
          <p class="eyebrow">Pengaturan</p>
          <h1>OpenAI API Key dan Model</h1>
          <p class="lead">Masukkan OpenAI API key milik Anda sendiri. Biaya penggunaan ditanggung
            oleh akun OpenAI Anda.</p>
        </div>
        ${flashHtml(messages, messages.length && !/gagal|tidak/i.test(messages.join(" ")))}

        <div class="alert">
          <p><strong>Penting tentang keamanan key:</strong> key disimpan apa adanya (tidak
            terenkripsi) di browser perangkat ini dan dikirim hanya ke api.openai.com. Jangan
            menyimpan key di komputer umum atau bersama. Batasi pemakaian key di dasbor OpenAI.</p>
        </div>

        <form class="upload-form" id="settings-form" autocomplete="off">
          <div class="field-grid">
            <label for="api_key">OpenAI API Key</label>
            <input id="api_key" name="api_key" type="password" autocomplete="off" autocapitalize="off"
              autocorrect="off" spellcheck="false" data-lpignore="true" data-1p-ignore="true"
              placeholder="${apiKey ? "•••• tersimpan, isi untuk mengganti" : "sk-..."}">
            <p class="field-help">${apiKey
              ? `Key tersimpan (empat karakter terakhir: ••••${esc(apiKey.slice(-4))}). Kosongkan untuk tetap memakai key ini.`
              : "Belum ada key tersimpan."}</p>
            <label class="checkbox-label"><input type="checkbox" id="toggle-key"> Tampilkan key</label>
            <label class="checkbox-label"><input type="checkbox" name="remember" ${!apiKey || remembered ? "checked" : ""}>
              Ingat key di browser ini (bila tidak dicentang, key terhapus saat tab ditutup)</label>
          </div>

          <div class="field-grid">
            <label for="model">Model OpenAI</label>
            <input id="model" name="model" type="text" list="model-options" required value="${esc(settings.model)}">
            <datalist id="model-options">
              <option value="gpt-6-astra"></option>
              <option value="gpt-5.6"></option>
            </datalist>
            <p class="field-help">Default <code>gpt-6-astra</code>. Bila akun Anda belum punya akses,
              ganti ke model lain yang tersedia, misalnya <code>gpt-5.6</code>. Model ini mahal:
              satu reviu lengkap bisa menghabiskan biaya yang berarti.</p>
          </div>

          <div class="field-grid">
            <label for="max_output_tokens">Batas token keluaran per permintaan</label>
            <input id="max_output_tokens" name="max_output_tokens" type="number" min="1000" max="128000"
              step="1000" required value="${esc(settings.max_output_tokens)}">
          </div>

          <div class="field-grid">
            <label for="timeout_seconds">Batas waktu permintaan (detik)</label>
            <input id="timeout_seconds" name="timeout_seconds" type="number" min="30" max="1800"
              step="30" required value="${esc(settings.timeout_seconds)}">
          </div>

          <div class="field-grid">
            <label for="scholarly_email">Email kontak Crossref/OpenAlex (opsional)</label>
            <input id="scholarly_email" name="scholarly_email" type="email" value="${esc(settings.scholarly_email)}"
              placeholder="nama@contoh.ac.id">
            <p class="field-help">Dikirim ke Crossref/OpenAlex saat mencari referensi agar mendapat layanan yang lebih stabil.</p>
          </div>

          <button type="submit">Simpan Pengaturan</button>
        </form>

        <div class="review-actions">
          <button type="button" class="secondary-action" data-test-ai ${apiKey && engineState === "ready" ? "" : "disabled"}>
            Tes Koneksi AI</button>
          ${apiKey ? `<button type="button" class="danger-button" data-delete-key>Hapus API Key</button>` : ""}
        </div>

        <div class="info-box">
          <p><strong>Hapus semua data</strong> menghapus seluruh reviu, file artikel, pengaturan, dan
            API key dari browser ini. Ekspor dulu bila ingin menyimpan cadangan.</p>
          <button type="button" class="danger-button small-button" data-wipe>Hapus semua data di browser ini</button>
        </div>
      </section>
    </main>`;
}

async function handleSettings(form) {
  const data = new FormData(form);
  const newKey = String(data.get("api_key") || "").trim();
  const key = newKey || store.loadApiKey();
  if (newKey && !newKey.startsWith("sk-")) {
    flash.push("API key OpenAI biasanya diawali \"sk-\". Periksa kembali key Anda.");
    return renderSettings();
  }
  const settings = store.saveSettings({
    model: String(data.get("model") || "").trim() || store.DEFAULT_SETTINGS.model,
    max_output_tokens: Number(data.get("max_output_tokens")) || store.DEFAULT_SETTINGS.max_output_tokens,
    timeout_seconds: Number(data.get("timeout_seconds")) || store.DEFAULT_SETTINGS.timeout_seconds,
    scholarly_email: String(data.get("scholarly_email") || "").trim(),
  });
  if (key && !store.saveApiKey(key, data.get("remember") === "on")) {
    flash.push("API key tidak dapat disimpan: penyimpanan browser diblokir.");
    return renderSettings();
  }
  await engine.configure({ ...settings, api_key: key }).catch(() => {});
  flash.push("Pengaturan tersimpan.");
  renderSettings();
}

async function testConnection() {
  const reply = await runBusy("Menguji koneksi ke OpenAI…", () => engine.call("testConnection"))
    .catch((error) => ({ ok: false, error: error.message }));
  if (!reply) return;
  flash.push(reply.ok ? reply.message : reply.error);
  renderSettings();
}

async function wipeAll() {
  if (!confirm("Hapus SEMUA reviu, file artikel, pengaturan, dan API key dari browser ini?")) return;
  try {
    await store.clearReviews();
  } catch {
    /* penyimpanan mungkin tidak tersedia */
  }
  store.clearSettings();
  await engine.configure(engineSettings()).catch(() => {});
  flash.push("Semua data di browser ini telah dihapus.");
  renderSettings();
}

// ---------------------------------------------------------------------------
// Routing dan event
// ---------------------------------------------------------------------------

async function route() {
  const hash = location.hash || "#/";
  const reviewMatch = hash.match(/^#\/reviu\/(.+)$/);
  document.querySelectorAll("[data-nav]").forEach((link) => {
    const active = (link.dataset.nav === "settings") === hash.startsWith("#/pengaturan")
      && !reviewMatch;
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  delete view.dataset.reviewId;
  window.scrollTo(0, 0);
  if (reviewMatch) {
    await renderReview(decodeURIComponent(reviewMatch[1]));
  } else if (hash.startsWith("#/pengaturan")) {
    renderSettings();
  } else {
    await renderHome();
  }
}

view.addEventListener("submit", (event) => {
  const form = event.target;
  event.preventDefault();
  if (isBusy) return;
  if (form.id === "upload-form") return handleUpload(form);
  if (form.id === "settings-form") return handleSettings(form);
  const action = form.getAttribute("action") || "";
  if (action.startsWith("#act/") && view.dataset.reviewId) {
    handleResultAction(action.slice(5), new FormData(form));
  }
});

view.addEventListener("click", (event) => {
  const target = event.target.closest("a, button, input");
  if (!target || isBusy) return;
  const href = target.getAttribute("href") || "";
  if (target.tagName === "A" && href.startsWith("#act/")) {
    event.preventDefault();
    if (view.dataset.reviewId) handleResultAction(href.slice(5), new FormData());
  } else if (target.hasAttribute("data-reload")) {
    event.preventDefault();
    location.reload();
  } else if (target.hasAttribute("data-import")) {
    document.getElementById("import-file").click();
  } else if (target.hasAttribute("data-export-all")) {
    exportReview(null);
  } else if (target.dataset.export) {
    exportReview(target.dataset.export);
  } else if (target.dataset.delete) {
    removeReview(target.dataset.delete);
  } else if (target.hasAttribute("data-test-ai")) {
    testConnection();
  } else if (target.hasAttribute("data-delete-key")) {
    store.deleteApiKey();
    engine.configure(engineSettings()).catch(() => {});
    flash.push("API key dihapus dari browser ini.");
    renderSettings();
  } else if (target.hasAttribute("data-wipe")) {
    wipeAll();
  } else if (target.id === "toggle-key") {
    document.getElementById("api_key").type = target.checked ? "text" : "password";
  }
});

view.addEventListener("change", (event) => {
  if (event.target.id === "import-file" && event.target.files[0]) {
    importFile(event.target.files[0]);
  }
});

document.getElementById("busy-cancel").addEventListener("click", () => {
  if (!confirm("Batalkan analisis yang sedang berjalan? Biaya permintaan yang sudah terkirim tetap dihitung OpenAI.")) {
    return;
  }
  engine.cancel();
  setBusy(false);
  watchEngine();
});

window.addEventListener("beforeunload", (event) => {
  if (isBusy) {
    event.preventDefault();
    event.returnValue = "";
  }
});

window.addEventListener("hashchange", () => {
  if (!isBusy) route();
});

engine.configure(engineSettings()).catch(() => {});
watchEngine();
route();
