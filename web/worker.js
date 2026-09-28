// Chạy Bot2 (Python) trong trình duyệt bằng Pyodide, tách khỏi luồng giao diện.
// Nhận nến [open_time_ms, o, h, l, c] -> trả payload Trade Explorer (JSON) như build_chart.py.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';
importScripts(PYODIDE + 'pyodide.js');

// Đường dẫn tương đối tính từ web/worker.js -> thư mục py/ ở gốc site.
const PY = new URL('../py/', self.location).href;
let ready = null;
async function boot(){
  const py = await loadPyodide({indexURL: PYODIDE});
  const files = await (await fetch(PY + 'manifest.json', {cache: 'no-store'})).json();
  await Promise.all(files.map(async path => {
    const text = await (await fetch(PY + path, {cache: 'no-store'})).text();
    const dir = '/bot2/' + path.split('/').slice(0, -1).join('/');
    py.FS.mkdirTree(dir);
    py.FS.writeFile('/bot2/' + path, text);
  }));
  py.runPython(`
import sys, json
sys.path.insert(0, "/bot2")
sys.path.insert(0, "/bot2/data/chart_template")
from datetime import datetime, timezone
from trading_bot.core.models import Bar
from build_chart import build_payload

def run_bot(rows_json, source):
    rows = json.loads(rows_json)
    bars = [Bar(index=i, open=r[1], high=r[2], low=r[3], close=r[4],
                timestamp=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc))
            for i, r in enumerate(rows)]
    payload = build_payload(bars)
    payload["src"] = source
    return json.dumps(payload, separators=(",", ":"))
`);
  return py.globals.get('run_bot');
}

self.onmessage = async ev => {
  const {id, rows, source} = ev.data;
  try {
    if (!ready) { self.postMessage({id, stage: 'Đang tải Python (Pyodide)…'}); ready = boot(); }
    const run = await ready;
    self.postMessage({id, stage: `Bot2 đang chạy trên ${rows.length.toLocaleString('vi-VN')} nến…`});
    const t0 = performance.now();
    const json = run(JSON.stringify(rows), source);
    self.postMessage({id, payload: json, ms: Math.round(performance.now() - t0)});
  } catch (e) {
    self.postMessage({id, error: String(e && e.message || e)});
  }
};
