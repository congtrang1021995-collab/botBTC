// Chạy Bot2 (Python) trong trình duyệt bằng Pyodide, tách khỏi luồng giao diện.
// Nhận nến [open_time_ms, o, h, l, c] -> trả payload Trade Explorer (JSON) như build_chart.py.
// Mỗi khung giữ engine đang chạy trong bộ nhớ: lần sau chỉ xử lý nến mới, không chạy lại từ đầu.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';
importScripts(PYODIDE + 'pyodide.js');

// Đường dẫn tương đối tính từ web/worker.js -> thư mục py/ ở gốc site.
const PY = new URL('../py/', self.location).href;
const KEEP = 3;             // số khung giữ engine trong bộ nhớ (mỗi khung vài chục MB)
const sessions = new Map(); // key -> {n, lastT}: số nến engine đã xử lý và thời gian nến cuối
let ready = null;

async function boot(){
  const py = await loadPyodide({indexURL: PYODIDE});
  const files = await (await fetch(PY + 'manifest.json', {cache: 'no-store'})).json();
  await Promise.all(files.map(async path => {
    const text = await (await fetch(PY + path, {cache: 'no-store'})).text();
    py.FS.mkdirTree('/bot2/' + path.split('/').slice(0, -1).join('/'));
    py.FS.writeFile('/bot2/' + path, text);
  }));
  py.runPython(`
import sys, json
sys.path.insert(0, "/bot2")
sys.path.insert(0, "/bot2/data/chart_template")
from datetime import datetime, timezone
from trading_bot.core.engine import TradingEngine
from trading_bot.core.models import Bar
from build_chart import build_payload

SESSIONS = {}

def run_bot(key, rows_json, fresh, source):
    if fresh or key not in SESSIONS:
        SESSIONS[key] = {"engine": TradingEngine(), "bars": [], "results": []}
    s = SESSIONS[key]
    for r in json.loads(rows_json):
        bar = Bar(index=len(s["bars"]), open=r[1], high=r[2], low=r[3], close=r[4],
                  timestamp=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc))
        s["bars"].append(bar)
        s["results"].append(s["engine"].process_bar(bar))
    payload = build_payload(s["bars"], s["results"])
    payload["src"] = source
    return json.dumps(payload, separators=(",", ":"))

def drop(key):
    SESSIONS.pop(key, None)
`);
  return {run: py.globals.get('run_bot'), drop: py.globals.get('drop')};
}

self.onmessage = async ev => {
  const {id, key, rows, source} = ev.data;
  try {
    if (!ready) { self.postMessage({id, stage: 'Đang tải Python (Pyodide)…'}); ready = boot(); }
    const bot = await ready;
    // Nối tiếp được khi nến engine đã xử lý vẫn là phần đầu của danh sách mới.
    const s = sessions.get(key);
    const resume = s && s.n <= rows.length && s.n > 0 && rows[s.n - 1][0] === s.lastT;
    const todo = resume ? rows.slice(s.n) : rows;
    self.postMessage({id, stage: resume
      ? `Bot2 tính thêm ${todo.length} nến mới…`
      : `Bot2 đang chạy trên ${rows.length.toLocaleString('vi-VN')} nến…`});
    const t0 = performance.now();
    const json = bot.run(key, JSON.stringify(todo), !resume, source);
    sessions.delete(key);
    sessions.set(key, {n: rows.length, lastT: rows[rows.length - 1][0]});
    while (sessions.size > KEEP) { const old = sessions.keys().next().value; sessions.delete(old); bot.drop(old); }
    self.postMessage({id, payload: json, ms: Math.round(performance.now() - t0), bars: todo.length});
  } catch (e) {
    self.postMessage({id, error: String(e && e.message || e)});
  }
};
