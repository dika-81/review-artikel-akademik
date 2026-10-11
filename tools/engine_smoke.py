"""Jalankan seluruh alur mesin web dengan OpenAI/Crossref/OpenAlex tiruan.

Dipakai untuk membandingkan hasil CPython dengan Pyodide (lihat
tools/pyodide_smoke.mjs). Mencetak satu objek JSON berisi hasil tiap tahap.

    python tools/engine_smoke.py web/py path/artikel.docx
"""

import json
import sys
from urllib.parse import urlparse

FAKE_ANALYSIS = {
    "ringkasan": "Ringkasan uji.",
    "skor": 78,
    "klasifikasi_artikel": {"jenis_artikel": "kuantitatif_eksperimen", "tingkat_keyakinan": "tinggi"},
    "masalah_teridentifikasi": [{"prioritas": "mayor", "masalah": "Contoh temuan."}],
    "versi_revisi": "Versi revisi uji.",
    "judul_rekomendasi": "Judul Rekomendasi Uji",
    "kata_kunci": ["uji"],
    "query_pencarian": ["kueri uji"],
}


def fake_transport(method, url, headers, body, timeout):
    host = urlparse(url).netloc
    if host == "api.openai.com":
        text = json.dumps(FAKE_ANALYSIS)
        return 200, json.dumps({"status": "completed", "output": [
            {"content": [{"type": "output_text", "text": text}]}
        ]})
    items = [
        {
            "title": [f"Artikel {i}"], "container-title": ["Jurnal"],
            "author": [{"family": "Penulis", "given": "Uji"}],
            "issued": {"date-parts": [[2022]]}, "DOI": f"10.1234/{host}.{i}",
        }
        for i in range(12)
    ]
    if host == "api.crossref.org":
        return 200, json.dumps({"message": {"items": items}})
    return 200, json.dumps({"results": []})


def run(docx_bytes, filename="artikel.docx"):
    import app_core
    import engine
    import web_runtime

    web_runtime.set_transport(fake_transport)
    engine.configure(json.dumps({"api_key": "sk-uji"}))
    reply = json.loads(engine.start_review(docx_bytes, filename, "mendalam"))
    assert reply["ok"], reply["error"]
    result = reply["result"]
    for step in app_core.WORKFLOW_STEPS[:-1]:
        reply = json.loads(engine.run_stage(docx_bytes, json.dumps(result), step["key"]))
        assert reply["ok"], (step["key"], reply["error"])
        result = reply["result"]
    reply = json.loads(engine.run_reference_recommendations(docx_bytes, json.dumps(result)))
    assert reply["ok"], reply["error"]
    result = reply["result"]
    pdf = engine.build_pdf(json.dumps(result))
    result.pop("_created_at", None)
    return {"result": result, "pdf_ok": bytes(pdf[:5]) == b"%PDF-", "pdf_size": len(pdf)}


if __name__ == "__main__":
    sys.path.insert(0, sys.argv[1])
    with open(sys.argv[2], "rb") as handle:
        output = run(handle.read())
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
