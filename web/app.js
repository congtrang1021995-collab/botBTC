// Bot2 Live trên GitHub Pages: trình duyệt tự lấy nến Binance, chạy Bot2 (Python/Pyodide trong
// worker.js) rồi vẽ Trade Explorer; nến đang chạy nhảy theo WebSocket, nến đóng thì Bot2 tính thêm.
// - Đổi khung ngay trong trang, không tải lại.
// - Nến + kết quả Bot2 của từng khung lưu trong IndexedDB của trình duyệt: mở lại là hiện ngay,
//   chỉ tải/tính các nến mới. Code Bot2 đổi (BOT2_VERSION khác) thì giữ nến, chỉ tính lại Bot2.
// Tham số URL tùy chọn: ?symbol=ETHUSDT&interval=4h&market=spot&start=2025-06-01
(function(){
const q = new URLSearchParams(location.search);
// Mỗi khung chạy Bot2 trên chính nến của khung đó; lịch sử mặc định ~8–15 nghìn nến.
const TFS = {
  '5m':  {label:'5p',   name:'M5',  ms:3e5,   days:30},
  '15m': {label:'15p',  name:'M15', ms:9e5,   days:90},
  '1h':  {label:'1h',   name:'H1',  ms:36e5,  start:'2025-01-01'},
  '4h':  {label:'4h',   name:'H4',  ms:144e5, start:'2022-01-01'},
  '1d':  {label:'Ngày', name:'D1',  ms:864e5, start:'2019-01-01'},
};
const SYMBOL = (q.get('symbol') || 'BTCUSDT').toUpperCase();
const MARKET = q.get('market') === 'spot' ? 'spot' : 'futures';
const START_PARAM = q.get('start');
const VERSION = window.BOT2_VERSION || 'dev';
const REST = MARKET === 'futures' ? 'https://fapi.binance.com/fapi/v1/klines' : 'https://api.binance.com/api/v3/klines';
const PAGE = MARKET === 'futures' ? 1500 : 1000;
// Futures: kline nằm ở /market/ws (đường /ws cũ kết nối được nhưng không gửi kline).
const WS_BASE = MARKET === 'futures' ? 'wss://fstream.binance.com/market/ws/' : 'wss://stream.binance.com:9443/ws/';
const SOURCE = `Binance ${MARKET === 'futures' ? 'Futures' : 'Spot'} (live)`;
const SYM_LABEL = SYMBOL + (MARKET === 'futures' ? '.P' : '');

const $ = id => document.getElementById(id);
const fmt = v => v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const clock = () => new Date().toLocaleTimeString('vi-VN',{hour12:false});
const startOf = (tf, explicit) => explicit || TFS[tf].start ||
  new Date(Date.now() - TFS[tf].days * 864e5).toISOString().slice(0, 10);

// ---- lưu trữ trong trình duyệt (IndexedDB) — lỗi/không có thì chạy như bình thường ----
const store = (() => {
  let dbp = null;
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    const r = indexedDB.open('bot2-live', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('tf');
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  }));
  const tx = async (mode, fn) => { const db = await open(); return new Promise((res, rej) => {
    const t = db.transaction('tf', mode), req = fn(t.objectStore('tf'));
    t.oncomplete = () => res(req && req.result); t.onerror = () => rej(t.error); }); };
  return {
    get: key => tx('readonly', s => s.get(key)).catch(() => null),
    put: (key, val) => tx('readwrite', s => s.put(val, key)).catch(() => null),
  };
})();

// ---- trạng thái ----
let TC = null;              // API chart (window.TradeChart) sau khi dựng lần đầu
let cur = null;             // khung đang xem: {tf, key, start, rows}
let loadToken = 0;          // tăng mỗi lần đổi khung; tác vụ cũ thấy token khác thì tự dừng
let running = false, rerunQueued = false;

// ---- đầu trang: nhãn, nút khung, ô live, màn chờ ----
document.querySelector('h1 .sym').textContent = SYM_LABEL;
const tfGroup = document.createElement('div');
tfGroup.className = 'grp'; tfGroup.setAttribute('role', 'group'); tfGroup.setAttribute('aria-label', 'Khung thời gian');
tfGroup.innerHTML = '<span class="lab">Khung</span>' + Object.entries(TFS).map(([k, tf]) =>
  `<button class="btn" data-tf="${k}" aria-pressed="false">${tf.label}</button>`).join('');
document.querySelector('.bar').prepend(tfGroup);
tfGroup.addEventListener('click', e => {
  const b = e.target.closest('[data-tf]');
  if (b && (!cur || b.dataset.tf !== cur.tf)) show(b.dataset.tf);
});
const box = document.createElement('div');
box.className = 'kpi live'; box.dataset.s = 'off';
box.innerHTML = '<span class="dot" aria-hidden="true"></span><div><b id="lv-px">—</b> <span id="lv-ch"></span><br><small id="lv-st">Đang khởi động…</small></div>';
document.querySelector('header').appendChild(box);
const overlay = document.createElement('div');
overlay.className = 'boot';
overlay.innerHTML = '<div><b id="boot-hd">Đang dựng chart live</b><span id="boot-st">Đang tải nến từ Binance…</span></div>';
document.querySelector('.chartbox').appendChild(overlay);
const setStatus = (s, text) => { box.dataset.s = s; $('lv-st').textContent = text; };
const setBoot = text => { const el = $('boot-st'); if (el) el.textContent = text; };
const showOverlay = on => { overlay.hidden = !on; };

// ---- nến đã đóng (REST) ----
async function fetchClosed(tf, startMs, token){
  const iv = TFS[tf].ms, out = [];
  for (let cursor = startMs; ; ) {
    const r = await fetch(`${REST}?symbol=${SYMBOL}&interval=${tf}&startTime=${cursor}&limit=${PAGE}`);
    if (!r.ok) throw new Error(`Binance ${r.status}: ${await r.text()}`);
    const page = await r.json(), now = Date.now();
    if (token !== loadToken) return out;
    for (const k of page) if (k[6] < now) out.push([k[0], +k[1], +k[2], +k[3], +k[4]]);
    if (page.length < PAGE) break;
    cursor = page[page.length - 1][0] + iv;
    setBoot(`Đang tải nến từ Binance… ${out.length.toLocaleString('vi-VN')}`);
  }
  return out;
}
async function fetchNew(c, token){
  const last = c.rows.length ? c.rows[c.rows.length - 1][0] : null;
  const fresh = await fetchClosed(c.tf, last == null ? Date.parse(c.start + 'T00:00:00Z') : last + TFS[c.tf].ms, token);
  return last == null ? fresh : fresh.filter(r => r[0] > last);
}

// ---- Bot2 trong worker ----
const worker = new Worker('web/worker.js?v=' + (window.BOT2_VERSION || Date.now()));
let seq = 0; const waiting = new Map();
worker.onmessage = ev => {
  const m = ev.data, p = waiting.get(m.id); if (!p) return;
  if (m.stage) { p.stage(m.stage); return; }
  waiting.delete(m.id);
  m.error ? p.reject(new Error(m.error)) : p.resolve(m);
};
const runBot = (c, stage = () => {}) => new Promise((resolve, reject) => {
  const id = ++seq; waiting.set(id, {resolve, reject, stage});
  worker.postMessage({id, key: c.key, rows: c.rows, source: SOURCE});
});

function render(payload, c, reset){
  payload.iv = TFS[c.tf].ms / 1000;
  if (!TC) {
    window.__D = payload;
    const s = document.createElement('script');
    s.textContent = $('chart-main').textContent;
    document.body.appendChild(s);
    TC = window.TradeChart;
    if (!TC) throw new Error('Không dựng được biểu đồ.');
  } else {
    TC.update(payload, {reset});
  }
  showOverlay(false);
}
const save = (c, payloadJson) => store.put(c.key, {version: VERSION, start: c.start, rows: c.rows, payload: payloadJson, savedAt: Date.now()});

// Có nến mới đóng -> Bot2 chỉ tính thêm các nến đó (engine giữ trong worker), lưu lại.
async function syncClosed(){
  const c = cur, token = loadToken; if (!c || !TC || c.loading) return;
  try {
    const fresh = await fetchNew(c, token);
    if (!fresh.length || token !== loadToken) return;
    c.rows.push(...fresh);
    if (running) { rerunQueued = true; return; }
    running = true;
    try {
      setStatus(box.dataset.s, 'Nến vừa đóng — Bot2 đang tính thêm…');
      const m = await runBot(c);
      if (token === loadToken) { render(JSON.parse(m.payload), c, false); save(c, m.payload); }
      setStatus(box.dataset.s, `Bot2 cập nhật ${clock()} (+${m.bars} nến, ${(m.ms/1000).toFixed(1)}s)`);
    } finally {
      running = false;
      if (rerunQueued) { rerunQueued = false; syncClosed(); }
    }
  } catch(e) { /* thử lại ở lần sau */ }
}

// ---- mở một khung: bản đã lưu hiện ngay, rồi bổ sung nến mới ----
async function show(tf){
  const token = ++loadToken;
  disconnect();
  const first = !TC;
  const c = cur = {tf, key: `${SYMBOL}|${MARKET}|${tf}`, start: startOf(tf, START_PARAM), rows: [], loading: true};
  tfGroup.querySelectorAll('[data-tf]').forEach(b => b.setAttribute('aria-pressed', b.dataset.tf === tf));
  const tfEl = $('tf-label'); if (tfEl) tfEl.textContent = TFS[tf].name;
  document.title = `${SYM_LABEL} ${TFS[tf].name} Bot2 Live`;
  const p = new URLSearchParams(location.search); p.set('interval', tf);
  history.replaceState(null, '', '?' + p.toString());
  prevClose = null; $('lv-px').textContent = '—'; $('lv-ch').textContent = '';

  try {
    const saved = await store.get(c.key);
    if (token !== loadToken) return;
    let shown = false;
    // Bản lưu dùng được khi có đủ lịch sử từ ngày bắt đầu cần xem (khung 5p/15p lấy "30/90 ngày
    // gần nhất" nên ngày bắt đầu trượt dần — lịch sử cũ hơn vẫn giữ). Quá dài thì tải lại cho gọn.
    if (saved && saved.start <= c.start && Array.isArray(saved.rows) && saved.rows.length && saved.rows.length < 40000) {
      c.rows = saved.rows; c.start = saved.start;
      if (saved.version === VERSION && saved.payload) {
        render(JSON.parse(saved.payload), c, !first); shown = true;
        setStatus('poll', `Bản lưu ${new Date(saved.savedAt).toLocaleString('vi-VN',{hour12:false})} — đang lấy nến mới…`);
        connect(tf, token);   // giá chạy ngay trên bản lưu, không chờ Bot2
      }
    }
    if (!shown) {
      $('boot-hd').textContent = `Đang dựng chart live ${TFS[tf].name}`;
      setBoot(c.rows.length ? 'Code Bot2 đã đổi — đang tính lại trên nến đã lưu…' : 'Đang tải nến từ Binance…');
      showOverlay(true);
    }
    const fresh = await fetchNew(c, token);
    if (token !== loadToken) return;
    c.rows.push(...fresh);
    if (!c.rows.length) throw new Error('Binance không trả về nến nào.');
    if (!shown || fresh.length) {
      running = true;
      try {
        const m = await runBot(c, shown ? () => {} : setBoot);
        if (token !== loadToken) return;
        render(JSON.parse(m.payload), c, !first && !shown);
        save(c, m.payload);
        setStatus(box.dataset.s, `Bot2 xong (${m.bars.toLocaleString('vi-VN')} nến, ${(m.ms/1000).toFixed(1)}s)` + (shown ? '' : ' — đang nối WebSocket…'));
      } finally { running = false; }
    }
    c.loading = false;
    if (!shown) connect(tf, token); else syncClosed();
  } catch(e) {
    if (token !== loadToken) return;
    setBoot('Lỗi: ' + e.message + ' — tải lại trang để thử lại. (Binance chặn truy cập từ một số quốc gia, ví dụ Mỹ.)');
    showOverlay(true);
    setStatus('off', 'Không khởi động được');
  }
}

// ---- giá realtime ----
let ws = null, wsToken = 0, lastMsg = 0, retry = 1000, pollTimer = null, prevClose = null;
function onBar(b){
  TC.tick(b);
  const el = $('lv-px'); el.textContent = fmt(b.close);
  el.className = prevClose == null || b.close === prevClose ? '' : b.close > prevClose ? 'up' : 'dn';
  prevClose = b.close;
  const ch = (b.close - b.open) / b.open * 100;
  $('lv-ch').innerHTML = `<span class="${ch>=0?'up':'dn'}">${ch>=0?'+':''}${ch.toFixed(2)}%</span>`;
  lastMsg = Date.now();
  const open = TC.openTrades().length;
  document.title = `${fmt(b.close)} · ${SYMBOL} ${TFS[cur.tf].name}${open ? ` · ${open} lệnh mở` : ''}`;
}
function connect(tf, token){
  if (token !== loadToken) return;
  wsToken = token;
  try { ws = new WebSocket(`${WS_BASE}${SYMBOL.toLowerCase()}@kline_${tf}`); } catch(e) { startPolling(tf, token); return; }
  const sock = ws;
  sock.onopen = () => { lastMsg = Date.now(); syncClosed(); };
  sock.onmessage = ev => {
    if (token !== loadToken) return;
    const k = JSON.parse(ev.data).k; if (!k) return;
    retry = 1000; stopPolling();
    onBar({time: k.t/1000, open: +k.o, high: +k.h, low: +k.l, close: +k.c});
    if (!running) setStatus('on', `Live · ${clock()}`);
    if (k.x) setTimeout(syncClosed, 1500);
  };
  sock.onclose = () => {
    if (token !== loadToken) return;   // đóng do đổi khung
    startPolling(tf, token); setTimeout(() => connect(tf, token), retry); retry = Math.min(retry * 2, 30000);
  };
  sock.onerror = () => { try { sock.close(); } catch(e) {} };
}
function disconnect(){ stopPolling(); if (ws) { const s = ws; ws = null; try { s.close(); } catch(e) {} } }
function startPolling(tf, token){
  if (pollTimer) return;
  const run = async () => {
    try {
      const k = (await (await fetch(`${REST}?symbol=${SYMBOL}&interval=${tf}&limit=1`)).json())[0];
      if (token !== loadToken) return;
      onBar({time: k[0]/1000, open: +k[1], high: +k[2], low: +k[3], close: +k[4]});
      if (!running) setStatus('poll', `REST 2s · ${clock()}`);
    } catch(e) { setStatus('off', 'Mất kết nối Binance — đang thử lại'); }
  };
  run(); pollTimer = setInterval(run, 2000);
}
function stopPolling(){ clearInterval(pollTimer); pollTimer = null; }

setInterval(syncClosed, 60000);
// WebSocket mở nhưng im lặng quá 10 giây: chuyển sang REST và kết nối lại.
setInterval(() => { if (ws && ws.readyState === 1 && !pollTimer && Date.now() - lastMsg > 10000) ws.close(); }, 5000);
show(TFS[q.get('interval')] ? q.get('interval') : '1h');
})();
