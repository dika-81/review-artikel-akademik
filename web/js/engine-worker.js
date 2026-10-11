/*
 * Web Worker yang menjalankan mesin reviu Python (web/py/) di Pyodide.
 *
 * Permintaan HTTP dari Python (OpenAI, Crossref, OpenAlex) dijalankan dengan
 * XMLHttpRequest sinkron. Ini hanya diizinkan di dalam worker, sehingga
 * halaman utama tetap responsif selama analisis berjalan.
 *
 * Protokol pesan:
 *   masuk : {id, cmd, args}
 *   keluar: {id, ok, data} | {id, ok: false, error} | {type: "progress", text}
 */

const PYODIDE_VERSION = "0.29.4";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
// Paket dari distribusi Pyodide; python-docx dan ReportLab dipasang dari
// wheel yang disertakan di situs (web/py/wheels, lihat tools/build_web.py).
const PYODIDE_PACKAGES = ["micropip", "lxml", "jinja2", "pillow", "typing-extensions"];
const PY_DIR = "/home/pyodide/reviu";

importScripts(PYODIDE_BASE + "pyodide.js");

let pyodide = null;
let engine = null;
let openaiRequestCount = 0;

function progress(text) {
  self.postMessage({ type: "progress", text });
}

function syncRequest(method, url, headers, body, timeoutSeconds) {
  if (url.startsWith("https://api.openai.com/")) {
    openaiRequestCount += 1;
    progress(`Menunggu jawaban OpenAI (permintaan ke-${openaiRequestCount})…`);
  } else {
    progress("Mencari referensi di OpenAlex/Crossref…");
  }
  const xhr = new XMLHttpRequest();
  xhr.open(method, url, false);
  xhr.timeout = Math.round(timeoutSeconds * 1000);
  for (const [name, value] of Object.entries(headers)) {
    xhr.setRequestHeader(name, value);
  }
  try {
    xhr.send(body ?? null);
  } catch (error) {
    return [0, error && error.name === "TimeoutError" ? "timeout" : "network"];
  }
  return [xhr.status, xhr.responseText];
}

async function loadEngine(baseUrl) {
  progress("Memuat Python (Pyodide)… pertama kali bisa memakan waktu beberapa detik.");
  pyodide = await loadPyodide({ indexURL: PYODIDE_BASE });
  const manifest = await (await fetch(`${baseUrl}py/manifest.json`, { cache: "no-cache" })).json();
  await pyodide.loadPackage(PYODIDE_PACKAGES);

  progress("Memasang pustaka pembaca DOCX dan PDF…");
  const micropip = pyodide.pyimport("micropip");
  await micropip.install(manifest.wheels.map((name) => `${baseUrl}py/wheels/${name}`));
  micropip.destroy();

  progress("Memuat mesin reviu…");
  for (const name of manifest.files) {
    const response = await fetch(`${baseUrl}py/${name}?v=${manifest.version}`);
    if (!response.ok) throw new Error(`Gagal memuat ${name} (HTTP ${response.status}).`);
    const path = `${PY_DIR}/${name}`;
    pyodide.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    pyodide.FS.writeFile(path, await response.text());
  }

  pyodide.registerJsModule("reviu_bridge", { request: syncRequest });
  pyodide.runPython(`
import sys
sys.path.insert(0, "${PY_DIR}")

import js
import reviu_bridge
import web_runtime
from pyodide.ffi import to_js


def _transport(method, url, headers, body, timeout):
    reply = reviu_bridge.request(
        method, url, to_js(headers, dict_converter=js.Object.fromEntries), body, timeout
    )
    return int(reply[0]), str(reply[1])


web_runtime.set_transport(_transport)
`);
  engine = pyodide.pyimport("engine");
  return { version: manifest.version, pyodide: PYODIDE_VERSION };
}

function pythonErrorMessage(error) {
  // PythonError berisi traceback lengkap; tampilkan hanya baris terakhir.
  const lines = String(error && error.message ? error.message : error).trim().split("\n");
  const last = lines[lines.length - 1] || "Terjadi kesalahan.";
  return last.replace(/^[A-Za-z_.]*Error: /, "");
}

function callJson(name, ...args) {
  return JSON.parse(engine[name](...args));
}

const COMMANDS = {
  init: ({ baseUrl }) => loadEngine(baseUrl),
  configure: ({ settings }) => callJson("configure", JSON.stringify(settings)),
  testConnection: () => callJson("test_connection"),
  startReview: ({ docx, filename, mode }) => callJson("start_review", docx, filename, mode),
  runStage: ({ docx, result, stage }) => callJson("run_stage", docx, JSON.stringify(result), stage),
  runReferences: ({ docx, result }) =>
    callJson("run_reference_recommendations", docx, JSON.stringify(result)),
  addReference: ({ result, doi }) =>
    callJson("add_recommended_reference", JSON.stringify(result), doi),
  setArticleType: ({ result, choice }) =>
    callJson("set_article_type", JSON.stringify(result), choice),
  viewContext: ({ result }) => callJson("view_context", JSON.stringify(result)),
  renderResult: ({ result, reviewId, messages = [] }) =>
    callJson("render_result", JSON.stringify(result), reviewId, JSON.stringify(messages)),
  buildPdf: ({ result }) => {
    const pdf = engine.build_pdf(JSON.stringify(result));
    try {
      return pdf.toJs();
    } finally {
      pdf.destroy();
    }
  },
};

self.onmessage = async (event) => {
  const { id, cmd, args = {} } = event.data;
  openaiRequestCount = 0;
  try {
    if (cmd !== "init" && !engine) throw new Error("Mesin reviu belum dimuat.");
    const handler = COMMANDS[cmd];
    if (!handler) throw new Error(`Perintah tidak dikenal: ${cmd}`);
    const data = await handler(args);
    const transfer = data instanceof Uint8Array ? [data.buffer] : [];
    self.postMessage({ id, ok: true, data }, transfer);
  } catch (error) {
    self.postMessage({ id, ok: false, error: pythonErrorMessage(error) });
  }
};
