"""Pengujian mesin versi web (web/python + app_core hasil build) di CPython.

Transport HTTP diganti tiruan, sehingga yang diuji adalah prompt yang dikirim,
cara respons OpenAI/Crossref/OpenAlex dibaca, dan kesetaraan hasil dengan
versi Flask (app.py).
"""

import importlib
import json
import sys
from urllib.parse import parse_qs, urlparse

import pytest

import app as app_module
from article_structure import extract_article_structure
from docx_fixtures import QUANTITATIVE_EXPERIMENT, build_docx

sys.path.insert(0, str(app_module.BASE_DIR / "tools"))
import build_web  # noqa: E402


FAKE_ANALYSIS = {
    "ringkasan": "Ringkasan uji.",
    "skor": 78,
    "klasifikasi_artikel": {
        "jenis_artikel": "kuantitatif_eksperimen",
        "tingkat_keyakinan": "tinggi",
        "bukti_teks": [{"lokasi": "MET-P01-S01", "kutipan": "kuasi eksperimen"}],
    },
    "masalah_teridentifikasi": [
        {
            "id": "X-01",
            "prioritas": "mayor",
            "kutipan_asli": "Penelitian ini bertujuan menguji pengaruh media tangram",
            "masalah": "Contoh temuan.",
        }
    ],
    "versi_revisi": "Versi revisi uji.",
    "judul_rekomendasi": "Judul Rekomendasi Uji",
    "kata_kunci": ["tangram", "geometri"],
    "query_pencarian": ["media tangram geometri", "pemahaman konsep geometri"],
    "peringkat": [],
}


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("webpy")
    build_web.build(out_dir, wheels=False)
    sys.path.insert(0, str(out_dir))
    for name in ("web_runtime", "app_core", "engine"):
        sys.modules.pop(name, None)
    modules = {name: importlib.import_module(name) for name in ("web_runtime", "app_core", "engine")}
    yield modules
    sys.path.remove(str(out_dir))
    for name in ("web_runtime", "app_core", "engine"):
        sys.modules.pop(name, None)


def scholarly_items(source, count=12):
    if source == "crossref":
        return {"message": {"items": [
            {
                "title": [f"Artikel Crossref {i}"],
                "container-title": ["Jurnal Uji"],
                "author": [{"family": "Penulis", "given": f"Nama {i}"}],
                "issued": {"date-parts": [[2022]]},
                "DOI": f"10.1234/cr.{i}",
                "is-referenced-by-count": i,
            }
            for i in range(count)
        ]}}
    return {"results": [
        {
            "display_name": f"Artikel OpenAlex {i}",
            "authorships": [{"author": {"display_name": f"Nama {i} Peneliti"}}],
            "publication_year": 2023,
            "primary_location": {"source": {"display_name": "Jurnal Terbuka"}},
            "ids": {"doi": f"https://doi.org/10.5678/oa.{i}"},
            "cited_by_count": i,
        }
        for i in range(count)
    ]}


class FakeTransport:
    def __init__(self, openai_reply=None, status=200):
        self.calls = []
        self.openai_reply = openai_reply
        self.status = status

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        host = urlparse(url).netloc
        if host == "api.openai.com":
            if self.status != 200:
                return self.status, json.dumps({"error": {"code": "x"}})
            reply = self.openai_reply or {
                "status": "completed",
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(FAKE_ANALYSIS)}],
                }],
            }
            return 200, json.dumps(reply)
        if host == "api.crossref.org":
            return 200, json.dumps(scholarly_items("crossref"))
        if host == "api.openalex.org":
            return 200, json.dumps(scholarly_items("openalex"))
        return 0, "network"

    def openai_prompts(self):
        return [
            json.loads(call["body"])["input"]
            for call in self.calls
            if "api.openai.com" in call["url"]
        ]


@pytest.fixture()
def docx_bytes():
    return build_docx(QUANTITATIVE_EXPERIMENT).getvalue()


def configure(web, transport, **settings):
    web["web_runtime"].set_transport(transport)
    web["engine"].configure(json.dumps({"api_key": "sk-uji", **settings}))


def test_build_contains_all_core_names(web):
    for name in build_web.APP_CORE_NAMES:
        assert hasattr(web["app_core"], name), name


def test_start_review_extracts_profile(web, docx_bytes):
    reply = json.loads(web["engine"].start_review(docx_bytes, "artikel.docx", "mendalam"))
    assert reply["ok"]
    assert reply["result"]["_uploaded"] is True
    assert reply["result"]["_mode_analisis"] == "mendalam"
    assert reply["result"]["_profil_heuristik"]["jenis_artikel"]
    assert "Jenis artikel terdeteksi" in reply["message"]


def test_start_review_rejects_non_docx(web, docx_bytes):
    reply = json.loads(web["engine"].start_review(docx_bytes, "artikel.pdf"))
    assert not reply["ok"]
    assert "docx" in reply["error"]


def test_stage_order_is_enforced(web, docx_bytes):
    configure(web, FakeTransport())
    result = json.loads(web["engine"].start_review(docx_bytes, "artikel.docx"))["result"]
    reply = json.loads(web["engine"].run_stage(docx_bytes, json.dumps(result), "abstrak"))
    assert not reply["ok"]
    assert "terkunci" in reply["error"]


def test_all_stages_match_flask_version(web, docx_bytes, monkeypatch, tmp_path):
    """Prompt dan hasil tiap tahap versi web identik dengan versi Flask."""
    transport = FakeTransport()
    configure(web, transport, model="gpt-6-astra", max_output_tokens=12000)
    engine = web["engine"]
    result = json.loads(engine.start_review(docx_bytes, "artikel.docx", "mendalam"))["result"]

    flask_prompts = []

    def fake_flask_json(system_prompt, user_prompt):
        flask_prompts.append(user_prompt)
        return json.loads(json.dumps(FAKE_ANALYSIS))

    monkeypatch.setattr(app_module, "openai_chat_json", fake_flask_json)
    structure = extract_article_structure(build_docx(QUANTITATIVE_EXPERIMENT, path=tmp_path / "a.docx"))
    flask_result = dict(result)

    for step in app_module.WORKFLOW_STEPS[:-1]:
        key = step["key"]
        reply = json.loads(engine.run_stage(docx_bytes, json.dumps(result), key))
        assert reply["ok"], (key, reply["error"])
        result = reply["result"]
        flask_result[key] = app_module.STAGE_HANDLERS[key](structure, flask_result)
        assert result[key] == json.loads(json.dumps(flask_result[key])), key

    assert transport.openai_prompts() == flask_prompts
    first_body = json.loads(transport.calls[0]["body"])
    assert first_body["model"] == "gpt-6-astra"
    assert first_body["max_output_tokens"] == 12000
    assert first_body["text"] == {"format": {"type": "json_object"}}
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-uji"

    reply = json.loads(engine.run_reference_recommendations(docx_bytes, json.dumps(result)))
    assert reply["ok"], reply["error"]
    recommendations = reply["result"]["referensi_tambahan"]["rekomendasi"]
    assert 10 <= len(recommendations) <= 15
    assert all(item["doi"] and item["apa_7"] for item in recommendations)
    scholarly_calls = [c for c in transport.calls if "openai" not in c["url"]]
    assert all("user-agent" not in {k.lower() for k in c["headers"]} for c in scholarly_calls)

    result = reply["result"]
    doi = recommendations[0]["doi"]
    reply = json.loads(engine.add_recommended_reference(json.dumps(result), doi))
    assert reply["ok"] and reply["result"]["referensi_tambahan"]["referensi_dipilih"][0]["doi"] == doi
    result = reply["result"]

    context = json.loads(engine.view_context(json.dumps(result)))["context"]
    assert context["review_complete"] is True

    pdf = engine.build_pdf(json.dumps(result))
    assert bytes(pdf[:5]) == b"%PDF-"


def test_set_article_type(web):
    result = {"_uploaded": True}
    reply = json.loads(web["engine"].set_article_type(json.dumps(result), "kualitatif_studi_kasus"))
    assert reply["ok"], reply["error"]
    assert reply["result"]["_jenis_artikel_pilihan"] == "kualitatif_studi_kasus"
    reply = json.loads(web["engine"].set_article_type(json.dumps(result), "tidak-ada"))
    assert not reply["ok"]


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "tidak valid"),
        (404, "gpt-6-astra"),
        (429, "rate limit"),
        (500, "kesalahan pada layanan OpenAI"),
    ],
)
def test_http_errors_are_translated(web, status, expected):
    configure(web, FakeTransport(status=status), model="gpt-6-astra")
    reply = json.loads(web["engine"].test_connection())
    assert not reply["ok"]
    assert expected in reply["error"]
    assert "sk-uji" not in reply["error"]


def test_truncated_output_is_rejected(web):
    transport = FakeTransport(openai_reply={
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [],
    })
    configure(web, transport)
    reply = json.loads(web["engine"].test_connection())
    assert not reply["ok"]
    assert "terpotong" in reply["error"]


def test_json_format_fallback_on_bad_request(web):
    class Transport(FakeTransport):
        def __call__(self, method, url, headers, body, timeout):
            if "text" in json.loads(body):
                self.calls.append({"url": url, "body": body, "headers": headers})
                return 400, "{}"
            return super().__call__(method, url, headers, body, timeout)

    transport = Transport()
    configure(web, transport)
    data = web["app_core"].openai_chat_json("sys", "user")
    assert data["ringkasan"] == "Ringkasan uji."
    assert len(transport.calls) == 2


def test_missing_api_key_message(web):
    web["web_runtime"].set_transport(FakeTransport())
    web["engine"].configure(json.dumps({"api_key": ""}))
    reply = json.loads(web["engine"].test_connection())
    assert "API key belum diisi" in reply["error"]


@pytest.mark.parametrize(
    "models_status, expected",
    [
        (401, "tidak valid"),
        (404, "tidak tersedia"),
        (200, "saldo/kuota habis"),
        (0, "Koneksi ke OpenAI gagal"),
    ],
)
def test_opaque_browser_error_is_diagnosed(web, models_status, expected):
    """Di browser, error /v1/responses tidak terbaca (status 0); /v1/models dipakai untuk diagnosis."""

    class Transport(FakeTransport):
        def __call__(self, method, url, headers, body, timeout):
            self.calls.append({"method": method, "url": url})
            if url.endswith("/v1/responses"):
                return 0, "network"
            return models_status, "{}" if models_status else "network"

    transport = Transport()
    configure(web, transport, model="gpt-6-astra")
    reply = json.loads(web["engine"].test_connection())
    assert not reply["ok"]
    assert expected in reply["error"]
    assert transport.calls[-1]["url"].endswith("/v1/models/gpt-6-astra")


def test_render_result_uses_flask_template(web, docx_bytes):
    configure(web, FakeTransport())
    engine = web["engine"]
    result = json.loads(engine.start_review(docx_bytes, "artikel.docx", "mendalam"))["result"]
    result = json.loads(engine.run_stage(docx_bytes, json.dumps(result), "profil_artikel"))["result"]
    reply = json.loads(engine.render_result(json.dumps(result), "rev-1", json.dumps(["Pesan <b>uji</b>"])))
    html = reply["html"]
    assert reply["ok"]
    assert 'action="#act/analyze_title"' in html
    assert 'action="#act/set_article_type"' in html
    assert "Pesan &lt;b&gt;uji&lt;/b&gt;" in html  # pesan di-escape
    assert reply["context"]["workflow_steps"][0]["complete"] is True
