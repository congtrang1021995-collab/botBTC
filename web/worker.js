// Chạy Bot2 (Python) trong trình duyệt bằng Pyodide, tách khỏi luồng giao diện.
// Bot2 của mỗi khung là một IncrementalChart (data/chart_template/incremental.py):
//  - nạp từ trạng thái đã lưu (pickle: seed tính sẵn trên GitHub hoặc bản lưu IndexedDB),
//  - thêm nến mới [open_time_ms, o, h, l, c] rồi trả dữ liệu chart (JSON),
//  - khi được hỏi thì trả lại trạng thái (pickle) để trang lưu cho lần sau.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';
importScripts(PYODIDE + 'pyodide.js');

// Đường dẫn tương đối tính từ web/worker.js -> thư mục py/ ở gốc site.
const PY = new URL('../py/', self.location).href;
const KEEP = 3;             // số khung giữ Bot2 trong bộ nhớ
const sessions = new Map(); // key -> {n, lastT} của Bot2 đang giữ trong Python
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
import sys, json, pickle
sys.path.insert(0, "/bot2")
sys.path.insert(0, "/bot2/data/chart_template")
from datetime import datetime, timezone
from trading_bot.core.models import Bar
from incremental import IncrementalChart

CHARTS = {}

def load(key, blob):
    # blob: Uint8Array từ JS (JsProxy), hoặc null/undefined. Pyodide mới đổi JS null thành
    # JsNull (khác None), nên kiểm tra theo to_bytes thay vì "is not None".
    CHARTS[key] = pickle.loads(blob.to_bytes()) if hasattr(blob, "to_bytes") else IncrementalChart()
    return len(CHARTS[key])

def add(key, rows_json, source):
    chart = CHARTS[key]
    for r in json.loads(rows_json):
        chart.add(Bar(index=len(chart), open=r[1], high=r[2], low=r[3], close=r[4],
                      timestamp=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc)))
    payload = chart.payload()
    payload["src"] = source
    return json.dumps(payload, separators=(",", ":"))

def dump(key):
    return pickle.dumps(CHARTS[key], protocol=5)

def drop(key):
    CHARTS.pop(key, None)
`);
  const g = name => py.globals.get(name);
  return {py, load: g('load'), add: g('add'), dump: g('dump'), drop: g('drop')};
}

// {op:'run', key, rows (chỉ nến mới), base: {n, lastT, ckpt?}, source, wantCkpt}
//   base.n/lastT: Bot2 đang ở nến thứ n (nến cuối lastT); ckpt: pickle của trạng thái đó (nếu có).
//   base = null -> chạy từ đầu với rows.
self.onmessage = async ev => {
  const {id, key, rows, base, source, wantCkpt} = ev.data;
  try {
    if (!ready) { self.postMessage({id, stage: 'Đang tải Python (Pyodide)…'}); ready = boot(); }
    const bot = await ready;
    const s = sessions.get(key);
    const inMemory = base && s && s.n === base.n && s.lastT === base.lastT;
    if (!inMemory) {
      if (base && !base.ckpt) throw new Error('thiếu trạng thái Bot2 để tính tiếp');
      self.postMessage({id, stage: base ? 'Đang nạp trạng thái Bot2 đã lưu…' : `Bot2 đang chạy trên ${rows.length.toLocaleString('vi-VN')} nến…`});
      bot.load(key, base ? new Uint8Array(base.ckpt) : null);
    }
    if (base && rows.length) self.postMessage({id, stage: `Bot2 tính thêm ${rows.length.toLocaleString('vi-VN')} nến mới…`});
    const t0 = performance.now();
    const json = bot.add(key, JSON.stringify(rows), source);
    const n = (base ? base.n : 0) + rows.length;
    const lastT = rows.length ? rows[rows.length - 1][0] : base.lastT;
    sessions.delete(key); sessions.set(key, {n, lastT});
    while (sessions.size > KEEP) { const old = sessions.keys().next().value; sessions.delete(old); bot.drop(old); }
    let ckpt = null;
    if (wantCkpt) { const p = bot.dump(key); ckpt = p.toJs().slice().buffer; p.destroy(); }
    self.postMessage({id, payload: json, n, lastT, ckpt, ms: Math.round(performance.now() - t0), added: rows.length},
                     ckpt ? [ckpt] : []);
  } catch (e) {
    self.postMessage({id, error: String(e && e.message || e)});
  }
};
