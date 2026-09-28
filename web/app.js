// Bot2 Live trên GitHub Pages: trình duyệt tự lấy nến Binance, chạy Bot2 (Python/Pyodide trong
// worker.js) rồi vẽ Trade Explorer; nến đang chạy nhảy theo WebSocket, nến đóng thì chạy lại Bot2.
// Tham số URL tùy chọn: ?symbol=ETHUSDT&interval=4h&market=spot&start=2025-06-01
(function(){
const q = new URLSearchParams(location.search);
const CFG = {
  symbol: (q.get('symbol') || 'BTCUSDT').toUpperCase(),
  interval: q.get('interval') || '1h',
  market: q.get('market') === 'spot' ? 'spot' : 'futures',
  start: q.get('start') || '2025-01-01',
};
const IV = {'15m':9e5,'30m':18e5,'1h':36e5,'2h':72e5,'4h':144e5,'1d':864e5}[CFG.interval];
const REST = CFG.market === 'futures' ? 'https://fapi.binance.com/fapi/v1/klines' : 'https://api.binance.com/api/v3/klines';
const PAGE = CFG.market === 'futures' ? 1500 : 1000;
// Futures: kline nằm ở /market/ws (đường /ws cũ kết nối được nhưng không gửi kline).
const WS = (CFG.market === 'futures' ? 'wss://fstream.binance.com/market/ws/' : 'wss://stream.binance.com:9443/ws/')
  + `${CFG.symbol.toLowerCase()}@kline_${CFG.interval}`;
const SOURCE = `Binance ${CFG.market === 'futures' ? 'Futures' : 'Spot'} (live)`;

const $ = id => document.getElementById(id);
const fmt = v => v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const clock = () => new Date().toLocaleTimeString('vi-VN',{hour12:false});
const rows = [];          // nến đã đóng: [open_ms, o, h, l, c]
let TC = null, running = false, rerunQueued = false;

// ---- trạng thái trên đầu trang + màn chờ ----
const box = document.createElement('div');
box.className = 'kpi live'; box.dataset.s = 'off';
box.innerHTML = '<span class="dot" aria-hidden="true"></span><div><b id="lv-px">—</b> <span id="lv-ch"></span><br><small id="lv-st">Đang khởi động…</small></div>';
document.querySelector('header').appendChild(box);
const overlay = document.createElement('div');
overlay.className = 'boot';
overlay.innerHTML = '<div><b>Đang dựng chart live</b><span id="boot-st">Đang tải nến từ Binance…</span></div>';
document.querySelector('.chartbox').appendChild(overlay);
const setStatus = (s, text) => { box.dataset.s = s; $('lv-st').textContent = text; };
const setBoot = text => { const el = $('boot-st'); if (el) el.textContent = text; };

// ---- dữ liệu nến đã đóng (REST) ----
async function fetchClosed(startMs){
  const out = [];
  for (let cursor = startMs; ; ) {
    const url = `${REST}?symbol=${CFG.symbol}&interval=${CFG.interval}&startTime=${cursor}&limit=${PAGE}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`Binance ${r.status}: ${await r.text()}`);
    const page = await r.json();
    const now = Date.now();
    for (const k of page) if (k[6] < now) out.push([k[0], +k[1], +k[2], +k[3], +k[4]]);
    if (page.length < PAGE) break;
    cursor = page[page.length - 1][0] + IV;
    setBoot(`Đang tải nến từ Binance… ${out.length.toLocaleString('vi-VN')}`);
  }
  return out;
}
async function syncClosed(){
  if (!rows.length) return;
  try {
    const fresh = (await fetchClosed(rows[rows.length - 1][0] + IV)).filter(r => r[0] > rows[rows.length - 1][0]);
    if (fresh.length) { rows.push(...fresh); rerun(); }
  } catch(e) { /* thử lại ở lần sau */ }
}

// ---- Bot2 chạy trong worker ----
const worker = new Worker('web/worker.js');
let seq = 0; const waiting = new Map();
worker.onmessage = ev => {
  const m = ev.data, p = waiting.get(m.id); if (!p) return;
  if (m.stage) { p.stage(m.stage); return; }
  waiting.delete(m.id);
  m.error ? p.reject(new Error(m.error)) : p.resolve(m);
};
const runBot = (stage = () => {}) => new Promise((resolve, reject) => {
  const id = ++seq; waiting.set(id, {resolve, reject, stage});
  worker.postMessage({id, rows, source: SOURCE});
});
async function rerun(){
  if (running) { rerunQueued = true; return; }
  running = true;
  try {
    setStatus(box.dataset.s, `Nến vừa đóng — Bot2 đang tính lại…`);
    const m = await runBot();
    TC.update(JSON.parse(m.payload));
    setStatus(box.dataset.s, `Bot2 cập nhật ${clock()} (${(m.ms/1000).toFixed(1)}s)`);
  } catch(e) { setStatus('off', 'Lỗi Bot2: ' + e.message); }
  running = false;
  if (rerunQueued) { rerunQueued = false; rerun(); }
}

// ---- giá realtime ----
let ws = null, lastMsg = 0, retry = 1000, pollTimer = null, prevClose = null;
function onBar(b){
  TC.tick(b);
  const el = $('lv-px'); el.textContent = fmt(b.close);
  el.className = prevClose == null || b.close === prevClose ? '' : b.close > prevClose ? 'up' : 'dn';
  prevClose = b.close;
  const ch = (b.close - b.open) / b.open * 100;
  $('lv-ch').innerHTML = `<span class="${ch>=0?'up':'dn'}">${ch>=0?'+':''}${ch.toFixed(2)}%</span>`;
  lastMsg = Date.now();
  const open = TC.openTrades().length;
  document.title = `${fmt(b.close)} · ${CFG.symbol}${open ? ` · ${open} lệnh mở` : ''}`;
}
function connect(){
  try { ws = new WebSocket(WS); } catch(e) { startPolling(); return; }
  ws.onopen = () => { lastMsg = Date.now(); syncClosed(); };
  ws.onmessage = ev => {
    const k = JSON.parse(ev.data).k; if (!k) return;
    retry = 1000; stopPolling();
    onBar({time: k.t/1000, open: +k.o, high: +k.h, low: +k.l, close: +k.c});
    if (!running) setStatus('on', `Live · ${clock()}`);
    if (k.x) setTimeout(syncClosed, 1500);
  };
  ws.onclose = () => { startPolling(); setTimeout(connect, retry); retry = Math.min(retry * 2, 30000); };
  ws.onerror = () => { try { ws.close(); } catch(e) {} };
}
function startPolling(){
  if (pollTimer) return;
  const run = async () => {
    try {
      const k = (await (await fetch(`${REST}?symbol=${CFG.symbol}&interval=${CFG.interval}&limit=1`)).json())[0];
      onBar({time: k[0]/1000, open: +k[1], high: +k[2], low: +k[3], close: +k[4]});
      if (!running) setStatus('poll', `REST 2s · ${clock()}`);
    } catch(e) { setStatus('off', 'Mất kết nối Binance — đang thử lại'); }
  };
  run(); pollTimer = setInterval(run, 2000);
}
function stopPolling(){ clearInterval(pollTimer); pollTimer = null; }

// ---- khởi động ----
async function main(){
  try {
    rows.push(...await fetchClosed(Date.parse(CFG.start + 'T00:00:00Z')));
    if (!rows.length) throw new Error('Binance không trả về nến nào.');
    const m = await runBot(setBoot);
    window.__D = JSON.parse(m.payload);
    const s = document.createElement('script');
    s.textContent = $('chart-main').textContent;
    document.body.appendChild(s);
    TC = window.TradeChart;
    if (!TC) throw new Error('Không dựng được biểu đồ.');
    overlay.remove();
    setStatus('poll', `Bot2 xong trong ${(m.ms/1000).toFixed(1)}s — đang nối WebSocket…`);
    connect();
    setInterval(syncClosed, 60000);
    // WebSocket mở nhưng im lặng quá 10 giây: chuyển sang REST và kết nối lại.
    setInterval(() => { if (ws && ws.readyState === 1 && !pollTimer && Date.now() - lastMsg > 10000) ws.close(); }, 5000);
  } catch(e) {
    setBoot('Lỗi: ' + e.message + ' — tải lại trang để thử lại. (Binance chặn truy cập từ một số quốc gia, ví dụ Mỹ.)');
    setStatus('off', 'Không khởi động được');
  }
}
main();
})();
