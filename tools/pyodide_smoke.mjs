// Uji mesin web di Pyodide asli (Node.js), lalu bandingkan dengan CPython.
//
//   npm install --prefix <folder> pyodide@0.29.4
//   node tools/pyodide_smoke.mjs <folder>/node_modules/pyodide web/py artikel.docx [hasil.json]
//
// Mencetak hasil tools/engine_smoke.py yang dijalankan di Pyodide, atau
// menyimpannya ke file bila argumen keempat diberikan.

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [pyodideDir, pyDir, docxPath, outPath] = process.argv.slice(2);
const { loadPyodide } = await import(pathToFileURL(join(resolve(pyodideDir), "pyodide.mjs")).href);

const pyodide = await loadPyodide();
await pyodide.loadPackage(["micropip", "lxml"]);
const micropip = pyodide.pyimport("micropip");
await micropip.install(["python-docx==1.1.2", "reportlab==4.4.1"]);

const target = "/home/pyodide/reviu";
pyodide.FS.mkdirTree(target);
for (const name of readdirSync(pyDir).filter((n) => n.endsWith(".py"))) {
  pyodide.FS.writeFile(`${target}/${name}`, readFileSync(join(pyDir, name), "utf8"));
}
pyodide.FS.writeFile(`${target}/engine_smoke.py`, readFileSync("tools/engine_smoke.py", "utf8"));
pyodide.FS.writeFile("/tmp/artikel.docx", readFileSync(docxPath));

const output = pyodide.runPython(`
import sys
sys.path.insert(0, "${target}")
import json, engine_smoke
with open("/tmp/artikel.docx", "rb") as handle:
    data = engine_smoke.run(handle.read())
json.dumps(data, ensure_ascii=False, sort_keys=True)
`);
if (outPath) writeFileSync(outPath, output);
else console.log(output);
