/*
 * Penyimpanan di browser pengguna.
 *
 * - Hasil reviu dan file artikel: IndexedDB (kapasitas besar, per browser).
 * - Pengaturan: localStorage.
 * - API key: localStorage bila "ingat di browser ini" dipilih, selain itu
 *   sessionStorage (terhapus saat tab ditutup).
 *
 * Semua akses dibungkus try/catch: mode privat atau data situs yang diblokir
 * tidak boleh membuat aplikasi gagal dimuat.
 */

const DB_NAME = "reviu-artikel";
const DB_VERSION = 1;
const STORE = "reviews";
const SETTINGS_KEY = "reviu-artikel:pengaturan";
const API_KEY_KEY = "reviu-artikel:api-key";
export const EXPORT_FORMAT = "reviu-artikel/v1";

export const DEFAULT_SETTINGS = {
  model: "gpt-6-astra",
  max_output_tokens: 16000,
  timeout_seconds: 300,
  scholarly_email: "",
};

let dbPromise = null;

function openDb() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex("updated_at", "updated_at");
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  return dbPromise;
}

async function withStore(mode, action) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    const request = action(transaction.objectStore(STORE));
    transaction.oncomplete = () => resolve(request ? request.result : undefined);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error || new Error("Penyimpanan dibatalkan."));
  });
}

export function newReviewId() {
  const random = crypto.getRandomValues(new Uint32Array(2));
  return `rev-${Date.now().toString(36)}-${random[0].toString(36)}${random[1].toString(36)}`;
}

export async function saveReview(review) {
  const record = { ...review, updated_at: new Date().toISOString() };
  await withStore("readwrite", (store) => store.put(record));
  return record;
}

export function getReview(id) {
  return withStore("readonly", (store) => store.get(id));
}

export async function listReviews() {
  const records = await withStore("readonly", (store) => store.getAll());
  return (records || []).sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
}

export function deleteReview(id) {
  return withStore("readwrite", (store) => store.delete(id));
}

export function clearReviews() {
  return withStore("readwrite", (store) => store.clear());
}

export async function requestPersistentStorage() {
  try {
    if (navigator.storage && navigator.storage.persist) {
      return await navigator.storage.persist();
    }
  } catch {
    /* tidak didukung */
  }
  return false;
}

// ---------------------------------------------------------------------------
// Ekspor/impor
// ---------------------------------------------------------------------------

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function base64ToBytes(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

export function exportReviews(reviews) {
  return JSON.stringify(
    {
      format: EXPORT_FORMAT,
      exported_at: new Date().toISOString(),
      reviews: reviews.map((review) => ({
        id: review.id,
        filename: review.filename,
        created_at: review.created_at,
        updated_at: review.updated_at,
        result: review.result,
        docx_base64: review.docx ? bytesToBase64(new Uint8Array(review.docx)) : null,
      })),
    },
    null,
    1,
  );
}

export async function importReviews(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("File bukan JSON yang valid.");
  }
  if (!data || data.format !== EXPORT_FORMAT || !Array.isArray(data.reviews)) {
    throw new Error("File ini bukan hasil ekspor aplikasi Reviu Artikel.");
  }
  const existing = new Set((await listReviews()).map((review) => review.id));
  let imported = 0;
  for (const item of data.reviews) {
    if (!item || typeof item.result !== "object" || !item.filename) continue;
    const id = item.id && !existing.has(item.id) ? item.id : newReviewId();
    await withStore("readwrite", (store) =>
      store.put({
        id,
        filename: String(item.filename),
        created_at: item.created_at || new Date().toISOString(),
        updated_at: item.updated_at || new Date().toISOString(),
        result: item.result,
        docx: item.docx_base64 ? base64ToBytes(item.docx_base64).buffer : null,
      }),
    );
    imported += 1;
  }
  return imported;
}

// ---------------------------------------------------------------------------
// Pengaturan dan API key
// ---------------------------------------------------------------------------

function safeGet(storage, key) {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(storage, key, value) {
  try {
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function safeRemove(storage, key) {
  try {
    storage.removeItem(key);
  } catch {
    /* abaikan */
  }
}

export function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(safeGet(localStorage, SETTINGS_KEY) || "{}") };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings) {
  const clean = { ...DEFAULT_SETTINGS, ...settings };
  safeSet(localStorage, SETTINGS_KEY, JSON.stringify(clean));
  return clean;
}

export function loadApiKey() {
  return safeGet(sessionStorage, API_KEY_KEY) || safeGet(localStorage, API_KEY_KEY) || "";
}

export function apiKeyRemembered() {
  return Boolean(safeGet(localStorage, API_KEY_KEY));
}

export function saveApiKey(key, remember) {
  safeRemove(localStorage, API_KEY_KEY);
  safeRemove(sessionStorage, API_KEY_KEY);
  return safeSet(remember ? localStorage : sessionStorage, API_KEY_KEY, key);
}

export function deleteApiKey() {
  safeRemove(localStorage, API_KEY_KEY);
  safeRemove(sessionStorage, API_KEY_KEY);
}

export function clearSettings() {
  deleteApiKey();
  safeRemove(localStorage, SETTINGS_KEY);
}
