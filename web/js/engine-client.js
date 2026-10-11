/*
 * Pembungkus berbasis Promise untuk engine-worker.js.
 *
 *   const engine = new ReviewEngine({ onProgress: (text) => ... });
 *   await engine.ready;
 *   const reply = await engine.call("startReview", { docx, filename, mode });
 *
 * Analisis yang sedang berjalan dapat dibatalkan dengan engine.cancel():
 * worker dihentikan lalu dimuat ulang.
 */

export class ReviewEngine {
  constructor({ onProgress = () => {}, baseUrl = new URL("../", import.meta.url).href } = {}) {
    this.onProgress = onProgress;
    this.baseUrl = baseUrl;
    this.settings = null;
    this._start();
  }

  _start() {
    this.pending = new Map();
    this.nextId = 1;
    this.worker = new Worker(new URL("./engine-worker.js", import.meta.url));
    this.worker.onmessage = (event) => this._handle(event.data);
    this.worker.onerror = (event) => {
      const error = new Error(event.message || "Worker mesin reviu gagal.");
      for (const { reject } of this.pending.values()) reject(error);
      this.pending.clear();
    };
    this.ready = this._send("init", { baseUrl: this.baseUrl }).then(async (info) => {
      if (this.settings) await this._send("configure", { settings: this.settings });
      return info;
    });
  }

  _handle(message) {
    if (message.type === "progress") {
      this.onProgress(message.text);
      return;
    }
    const entry = this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id);
    if (message.ok) entry.resolve(message.data);
    else entry.reject(new Error(message.error));
  }

  _send(cmd, args) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, cmd, args });
    });
  }

  async configure(settings) {
    this.settings = settings;
    await this.ready;
    return this._send("configure", { settings });
  }

  async call(cmd, args = {}) {
    await this.ready;
    return this._send(cmd, args);
  }

  cancel() {
    this.worker.terminate();
    for (const { reject } of this.pending.values()) {
      reject(new Error("Analisis dibatalkan."));
    }
    this._start();
  }
}
