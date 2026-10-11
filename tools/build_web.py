"""Bangun paket Python untuk versi web (GitHub Pages + Pyodide).

Pemakaian (dari folder proyek):
    python tools/build_web.py

Hasil ditulis ke web/py/ (tidak di-commit; dibangun ulang oleh GitHub Actions):
- salinan modul inti (article_structure, citations, article_profile,
  analysis_schema, prompts) tanpa perubahan;
- app_core.py: fungsi dan konstanta analisis yang diambil otomatis dari app.py
  dengan AST, sehingga logika tahap analisis hanya ditulis sekali (di app.py);
- web_runtime.py dan engine.py dari web/python/;
- templates/result.html (dirender Jinja2 di browser, sama seperti Flask);
- wheels/: python-docx dan ReportLab (wheel Python murni) agar situs tidak
  bergantung pada PyPI saat dibuka;
- manifest.json berisi daftar file untuk dimuat worker Pyodide.

Selain itu static/styles.css disalin ke web/static/styles.css.
"""

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
OUT_DIR = WEB_DIR / "py"
WEB_PYTHON_DIR = WEB_DIR / "python"
WEB_STATIC_DIR = WEB_DIR / "static"

# Versi sama dengan requirements.txt. Dependensinya (lxml, Pillow,
# typing-extensions) tersedia di distribusi Pyodide.
WHEELS = ["python-docx==1.1.2", "reportlab==4.4.1"]
TEMPLATES = ["result.html"]

SHARED_MODULES = [
    "analysis_schema.py",
    "article_profile.py",
    "article_structure.py",
    "citations.py",
    "prompts.py",
]

# Nama tingkat atas di app.py yang dipakai versi web. Semuanya bebas Flask;
# pemanggilan OpenAI/HTTP diarahkan ke web_runtime melalui PRELUDE di bawah.
APP_CORE_NAMES = [
    # Konstanta alur kerja dan mode
    "ALLOWED_EXTENSIONS",
    "WORKFLOW_STEPS",
    "LEGACY_WORKFLOW_KEYS",
    "SECTION_STAGE_META",
    "SECTION_CHUNK_CHARS",
    "ANALYSIS_MODE_LABELS",
    "ANALYSIS_MODE_DESCRIPTIONS",
    "analysis_mode",
    "allowed_file",
    "detect_title",
    "build_short_article_context",
    # Pemanggilan model (JSON + satu kali koreksi)
    "JSON_REPAIR_SYSTEM",
    "openai_chat_json",
    # Profil dan finalisasi
    "profile_summary_for_prompts",
    "finalize_section_result",
    "split_section_batches",
    "merge_partial_results",
    "analyze_section_with_batches",
    "validate_classification_evidence",
    # Tahap analisis
    "stage_profile",
    "stage_title",
    "_abstract_context",
    "stage_abstract",
    "stage_introduction",
    "stage_methodology",
    "stage_results_discussion",
    "stage_conclusion",
    "CROSS_SECTION_SECTION_CHARS",
    "stage_cross_section",
    "stage_citations",
    "STAGE_HANDLERS",
    # Rekomendasi referensi
    "REVISION_SYSTEM_PROMPT",
    "_LEGACY_REVISION_FIELDS",
    "stage_revision_text",
    "stage_context_text",
    "extract_reference_search_terms",
    "normalize_doi",
    "format_authors_apa",
    "format_reference_apa_7",
    "crossref_reference_from_item",
    "openalex_reference_from_item",
    "reference_is_complete",
    "search_crossref",
    "search_openalex",
    "rank_reference_candidates",
    "find_verified_reference_recommendations",
    # Konteks tampilan dan urutan modul
    "article_type_context",
    "citation_groups_for_display",
    "get_workflow_steps",
    "module_is_unlocked",
    "is_review_complete",
    "result_template_context",
    # PDF
    "pdf_safe_text",
    "add_pdf_value",
    "FINDING_PDF_FIELDS",
    "FINDING_PDF_FIELDS_RINGKAS",
    "add_finding_to_pdf",
    "SECTION_STAGE_EXTRA_PDF_FIELDS",
    "PDF_ANALYSIS_STAGES",
    "add_stage_to_pdf",
    "draw_pdf_page",
    "build_review_pdf",
]

PRELUDE = '''"""BERKAS HASIL BUILD - jangan diedit langsung.

Dibuat oleh tools/build_web.py dari app.py. Ubah logika di app.py, lalu
jalankan ulang build.
"""

import json
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape

from analysis_schema import (
    ANALYSIS_MODES,
    DEFAULT_ANALYSIS_MODE,
    ModelJSONError,
    apply_mode_limits,
    normalize_finding,
    normalize_section_result,
    parse_model_json,
    resolve_analysis_mode,
    sort_findings,
)
from article_profile import (
    APPROACH_SIGNALS,
    ARTICLE_TYPE_CHOICES,
    ARTICLE_TYPE_LABELS,
    article_type_label,
    detect_article_profile,
    effective_article_type,
    filter_false_positive_findings,
)
from article_structure import (
    extract_article_structure,
    format_section_for_prompt,
    format_section_tail_for_prompt,
    get_section,
    locate_quote,
    validate_findings_quotes,
)
from citations import run_citation_check
import prompts as prompt_builders
from prompts import SYSTEM_ANALYST

# Pengganti OpenAI SDK, httpx, dan thread untuk lingkungan browser.
from web_runtime import (
    ThreadPoolExecutor,
    as_completed,
    call_openai_chat,
    httpx,
    safe_error_message,
)

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    PDF_AVAILABLE = True
except ImportError:  # PDF dimatikan bila ReportLab gagal dimuat.
    PDF_AVAILABLE = False
'''


def top_level_name(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    return None


def build_app_core():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    segments = {}
    for node in tree.body:
        name = top_level_name(node)
        if name in APP_CORE_NAMES:
            segments[name] = ast.get_source_segment(source, node)
    missing = [name for name in APP_CORE_NAMES if name not in segments]
    if missing:
        sys.exit("Nama berikut tidak ditemukan di app.py: " + ", ".join(missing))
    # Urutan mengikuti app.py agar konstanta terdefinisi sebelum dipakai.
    ordered = [
        segments[top_level_name(node)]
        for node in tree.body
        if top_level_name(node) in segments
    ]
    body = PRELUDE + "\n\n" + "\n\n\n".join(ordered) + "\n"
    ast.parse(body)  # Pastikan hasil build valid secara sintaks.
    return body


def download_wheels(target):
    target.mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "download", "--quiet", "--no-deps",
         "--only-binary", ":all:", "--dest", str(target), *WHEELS],
        check=True,
    )
    return sorted(path.name for path in target.glob("*.whl"))


def build(out_dir=OUT_DIR, wheels=True):
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    files = []
    for name in SHARED_MODULES:
        shutil.copyfile(ROOT / name, out_dir / name)
        files.append(name)
    for path in sorted(WEB_PYTHON_DIR.glob("*.py")):
        shutil.copyfile(path, out_dir / path.name)
        files.append(path.name)
    (out_dir / "app_core.py").write_text(build_app_core(), encoding="utf-8")
    files.append("app_core.py")
    (out_dir / "templates").mkdir()
    for name in TEMPLATES:
        shutil.copyfile(ROOT / "templates" / name, out_dir / "templates" / name)
        files.append(f"templates/{name}")

    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode())
        digest.update((out_dir / name).read_bytes())
    wheel_names = download_wheels(out_dir / "wheels") if wheels else []
    manifest = {
        "files": sorted(files),
        "wheels": wheel_names,
        "version": digest.hexdigest()[:12],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    WEB_STATIC_DIR.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "static" / "styles.css", WEB_STATIC_DIR / "styles.css")
    manifest = build()
    print(f"Paket web/py/ dibuat: {len(manifest['files'])} file, versi {manifest['version']}.")


if __name__ == "__main__":
    main()
