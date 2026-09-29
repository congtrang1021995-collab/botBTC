// Bot2 Live trên GitHub Pages: trình duyệt lấy nến Binance, chạy Bot2 (Python/Pyodide trong
// worker.js) rồi vẽ Trade Explorer; nến đang chạy nhảy theo WebSocket, nến đóng thì Bot2 tính thêm.
// Mở một khung theo thứ tự nhanh nhất có được:
//   1. bản lưu trong trình duyệt (IndexedDB: dữ liệu chart + trạng thái Bot2) — hiện ngay;
//   2. seed GitHub tính sẵn hằng ngày (web/build_seeds.py) — lịch sử dài, không phải chạy lại;
//   3. không có cả hai (vd. ?start= sớm hơn seed): tải nến song song rồi chạy Bot2 từ đầu.
// Sau đó chỉ tải nến mới đóng và Bot2 chỉ tính thêm các nến đó.
// Tham số URL tùy chọn: ?interval=15m&start=2023-01-01&symbol=XAUUSDT&market=spot&feed=binance
// Vàng (XAUUSDT) mặc định lấy nến MT5 trên máy qua cầu nối mt5_feed.py (http://127.0.0.1:8770);
// ?feed=binance để dùng lại XAUUSDT Futures của Binance.
(function(){
const q = new URLSearchParams(location.search);
// Lịch sử mặc định khi KHÔNG có seed (chạy hoàn toàn trong trình duyệt nên giữ ngắn).
const TFS = {
  '5m':  {label:'5p',   name:'M5',  ms:3e5,   days:30},
  '15m': {label:'15p',  name:'M15', ms:9e5,   days:90},
  '1h':  {label:'1h',   name:'H1',  ms:36e5,  start:'2025-01-01'},
  '4h':  {label:'4h',   name:'H4',  ms:144e5, start:'2022-01-01'},
  '1d':  {label:'Ngày', name:'D1',  ms:864e5, start:'2019-01-01'},
};
// Bot 2 (2026-09-29): khung giao dịch -> khung lớn dùng lọc lệnh theo trend (M15 <- H1, H1 <- H4).
const HIGHER = {'15m': '1h', '1h': '4h'};
const HIGHER_WARMUP_DAYS = 60;   // nến khung lớn lấy sớm hơn điểm bắt đầu để trend kịp hình thành
// Tài sản có nút chọn trên trang (mã khác vẫn mở được bằng ?symbol=, chỉ không có seed).
const ASSETS = {BTCUSDT: 'BTC', XAUUSDT: 'Vàng XAU'};
const SYMBOL = (q.get('symbol') || 'BTCUSDT').toUpperCase();
const MARKET = q.get('market') === 'spot' ? 'spot' : 'futures';
const MT5_SYMBOLS = {XAUUSDT: 'XAUUSD'};
const FEED = MT5_SYMBOLS[SYMBOL] && q.get('feed') !== 'binance' ? 'mt5' : 'binance';
// Trang do chính mt5_feed.py phục vụ thì gọi cùng địa chỉ (không bị trình duyệt chặn).
const MT5_URL = (q.get('mt5') || (location.port === '8770' ? location.origin : 'http://127.0.0.1:8770')).replace(/\/$/, '');
// Trang công khai (GitHub Pages) bị trình duyệt chặn gọi 127.0.0.1 -> chuyển hẳn sang trang do
// cầu nối phục vụ (điều hướng thì không bị chặn như fetch).
if (FEED === 'mt5' && !q.get('mt5') && location.port !== '8770' && !/^(localhost|127\.0\.0\.1)$/.test(location.hostname)) {
  location.replace('http://127.0.0.1:8770/' + location.search);
  return;
}
const START_PARAM = q.get('start');
const VERSION = window.BOT2_VERSION || 'dev';
const REST = FEED === 'mt5' ? MT5_URL + '/klines' : MARKET === 'futures' ? 'https://fapi.binance.com/fapi/v1/klines' : 'https://api.binance.com/api/v3/klines';
const PAGE = MARKET === 'futures' ? 1500 : 1000;
// Futures: kline nằm ở /market/ws (đường /ws cũ kết nối được nhưng không gửi kline).
const WS_BASE = MARKET === 'futures' ? 'wss://fstream.binance.com/market/ws/' : 'wss://stream.binance.com:9443/ws/';
let SOURCE = FEED === 'mt5' ? 'MT5 (live)' : `Binance ${MARKET === 'futures' ? 'Futures' : 'Spot'} (live)`;
const SYM_LABEL = FEED === 'mt5' ? MT5_SYMBOLS[SYMBOL] + ' (MT5)' : SYMBOL + (MARKET === 'futures' ? '.P' : '');
const FEED_NAME = FEED === 'mt5' ? 'MT5' : 'Binance';
// Cầu nối MT5: hỏi tài khoản/mã để ghi nguồn; không kết nối được thì báo lỗi khi mở khung.
const mt5Info = FEED === 'mt5'
  ? fetch(MT5_URL + '/info', {cache: 'no-store'}).then(r => r.json()).then(i => {
      SOURCE = `MT5 ${i.server} ${i.symbol} (live)`; return i; })
  : Promise.resolve(null);

const $ = id => document.getElementById(id);
const fmt = v => v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const clock = () => new Date().toLocaleTimeString('vi-VN',{hour12:false});
const fmtDate = s => s.split('-').reverse().join('/');
// Nến MT5 lấy từ máy nên nhanh: lịch sử dài hơn (MT5 demo có nến từ 01/2025, M5 từ 04/2025).
const MT5_START = {'5m': 180, '15m': '2025-01-01', '1h': '2025-01-01', '4h': '2020-01-01', '1d': '2020-01-01'};
const fallbackStart = tf => FEED === 'mt5'
  ? (typeof MT5_START[tf] === 'number' ? new Date(Date.now() - MT5_START[tf] * 864e5).toISOString().slice(0, 10) : MT5_START[tf])
  : TFS[tf].start || new Date(Date.now() - TFS[tf].days * 864e5).toISOString().slice(0, 10);

// ---- lưu trữ trong trình duyệt (IndexedDB) — lỗi/không có thì chạy như bình thường ----
// Đổi cấu trúc thì đổi TÊN cơ sở dữ liệu (không nâng version): nâng version bị chặn mãi nếu
// một tab/trang cũ còn giữ kết nối. Mở quá 2,5 giây thì bỏ qua bản lưu, trang vẫn chạy.
const store = (() => {
  let dbp = null;
  try { indexedDB.deleteDatabase('bot2-live'); } catch(e) {}   // bản lưu kiểu cũ (danh sách nến)
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    const r = indexedDB.open('bot2-live-ckpt', 1);
    const timer = setTimeout(() => rej(new Error('IndexedDB bận')), 2500);
    r.onupgradeneeded = () => r.result.createObjectStore('tf');
    r.onsuccess = () => { clearTimeout(timer); r.result.onversionchange = () => r.result.close(); res(r.result); };
    r.onerror = () => { clearTimeout(timer); rej(r.error); };
    r.onblocked = () => { clearTimeout(timer); rej(new Error('IndexedDB bị chặn')); };
  }));
  const tx = async (mode, fn) => { const db = await open(); return new Promise((res, rej) => {
    const t = db.transaction('tf', mode), req = fn(t.objectStore('tf'));
    t.oncomplete = () => res(req && req.result); t.onerror = () => rej(t.error); }); };
  return {
    get: key => tx('readonly', s => s.get(key)).catch(() => null),
    put: (key, val) => tx('readwrite', s => s.put(val, key)).catch(() => null),
  };
})();

// ---- seed GitHub (chỉ Futures, các mã trong web/build_seeds.py) ----
const seedIndex = MARKET === 'futures' && FEED === 'binance'
  ? fetch(`seed/index.json?v=${VERSION}`).then(r => r.ok ? r.json() : null)
      .then(ix => ix && ix.version === VERSION ? ix.seeds[SYMBOL] || null : null).catch(() => null)
  : Promise.resolve(null);

// ---- trạng thái ----
let TC = null;              // API chart (window.TradeChart) sau khi dựng lần đầu
let cur = null;             // khung đang xem: {tf, key, start, n, lastT, ckpt, loading}
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
// Đổi tài sản = tải lại trang với ?symbol= mới (giữ khung đang xem).
const assetGroup = document.createElement('div');
assetGroup.className = 'grp'; assetGroup.setAttribute('role', 'group'); assetGroup.setAttribute('aria-label', 'Tài sản');
assetGroup.innerHTML = '<span class="lab">Tài sản</span>' + Object.entries(ASSETS).map(([k, name]) =>
  `<button class="btn" data-sym="${k}" aria-pressed="${k === SYMBOL}">${name}</button>`).join('');
document.querySelector('.bar').prepend(assetGroup);
assetGroup.addEventListener('click', e => {
  const b = e.target.closest('[data-sym]');
  if (!b || b.dataset.sym === SYMBOL) return;
  const p = new URLSearchParams(location.search); p.set('symbol', b.dataset.sym); p.delete('start');
  location.search = p.toString();
});
const box = document.createElement('div');
box.className = 'kpi live'; box.dataset.s = 'off';
box.innerHTML = '<span class="dot" aria-hidden="true"></span><div><b id="lv-px">—</b> <span id="lv-ch"></span><br><small id="lv-st">Đang khởi động…</small></div>';
document.querySelector('header').appendChild(box);
const overlay = document.createElement('div');
overlay.className = 'boot';
overlay.innerHTML = '<div><b id="boot-hd">Đang dựng chart live</b><span id="boot-st">Đang tải nến…</span></div>';
document.querySelector('.chartbox').appendChild(overlay);
const setStatus = (s, text) => { box.dataset.s = s; $('lv-st').textContent = text; };
const setBoot = text => { const el = $('boot-st'); if (el) el.textContent = text; };
const showOverlay = on => { overlay.hidden = !on; };

// ---- nến đã đóng (REST), tải song song theo trang ----
async function fetchClosed(tf, startMs, token){
  const iv = TFS[tf].ms, now = Date.now(), starts = [];
  for (let s = startMs; s < now; s += PAGE * iv) starts.push(s);
  const pages = new Array(starts.length); let next = 0, done = 0;
  const one = async () => {
    while (next < starts.length) {
      const i = next++;
      const r = await fetch(`${REST}?symbol=${SYMBOL}&interval=${tf}&startTime=${starts[i]}&limit=${PAGE}`);
      if (!r.ok) throw new Error(`${FEED_NAME} ${r.status}: ${await r.text()}`);
      pages[i] = await r.json();
      if (starts.length > 2) setBoot(`Đang tải nến từ ${FEED_NAME}… ${Math.round(++done / starts.length * 100)}%`);
    }
  };
  await Promise.all(Array.from({length: Math.min(6, starts.length)}, one));
  if (token !== loadToken) return [];
  const out = [], seen = new Set(), t = Date.now();
  for (const page of pages) for (const k of page)
    if (k[6] < t && !seen.has(k[0])) { seen.add(k[0]); out.push([k[0], +k[1], +k[2], +k[3], +k[4]]); }
  return out.sort((a, b) => a[0] - b[0]);
}
const fetchAfter = async (c, token) =>
  (await fetchClosed(c.tf, c.lastT + TFS[c.tf].ms, token)).filter(r => r[0] > c.lastT);
// Nến khung lớn đã đóng chưa đưa vào Bot2 (khung không lọc thì rỗng). Gọi SAU khi đã có nến
// khung nhỏ để nến khung lớn đóng cùng lúc cũng có mặt.
async function fetchHigher(c, token){
  const htf = HIGHER[c.tf]; if (!htf) return [];
  const from = c.hLastT != null ? c.hLastT + TFS[htf].ms
                                : Date.parse(c.start + 'T00:00:00Z') - HIGHER_WARMUP_DAYS * 864e5;
  return (await fetchClosed(htf, from, token)).filter(r => c.hLastT == null || r[0] > c.hLastT);
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
// rows: nến mới cần thêm; c.n > 0 -> tính tiếp từ trạng thái c (trong worker hoặc c.ckpt).
const runBot = (c, rows, higher, stage = () => {}) => new Promise((resolve, reject) => {
  const id = ++seq; waiting.set(id, {resolve, reject, stage});
  const base = c.n > 0 ? {n: c.n, lastT: c.lastT, ckpt: c.ckpt} : null;
  worker.postMessage({id, key: c.key, rows, higher, base, source: SOURCE, wantCkpt: true});
});
const adopt = (c, m) => { c.n = m.n; c.lastT = m.lastT; c.ckpt = m.ckpt; c.hLastT = JSON.parse(m.payload).hLast ?? null; };

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
const save = (c, payloadJson) => store.put(c.key, {version: VERSION, start: c.start, n: c.n, lastT: c.lastT, hLastT: c.hLastT,
                                                   ckpt: c.ckpt, payload: payloadJson, savedAt: Date.now()});

// Có nến mới đóng -> Bot2 chỉ tính thêm các nến đó, lưu lại.
async function syncClosed(){
  const c = cur, token = loadToken; if (!c || !TC || c.loading || !c.n) return;
  if (running) { rerunQueued = true; return; }
  running = true;
  try {
    const fresh = await fetchAfter(c, token);
    if (!fresh.length || token !== loadToken) return;
    const higher = await fetchHigher(c, token);
    if (token !== loadToken) return;
    setStatus(box.dataset.s, 'Nến vừa đóng — Bot2 đang tính thêm…');
    const m = await runBot(c, fresh, higher);
    if (token !== loadToken) return;
    adopt(c, m); render(JSON.parse(m.payload), c, false); save(c, m.payload);
    setStatus(box.dataset.s, `Bot2 cập nhật ${clock()} (+${m.added} nến, ${(m.ms/1000).toFixed(1)}s)`);
  } catch(e) { /* thử lại ở lần sau */ }
  finally {
    running = false;
    if (rerunQueued) { rerunQueued = false; syncClosed(); }
  }
}

// ---- mở một khung ----
async function show(tf){
  const token = ++loadToken;
  disconnect();
  const first = !TC;
  const key = FEED === 'mt5' ? `${SYMBOL}|mt5|${tf}` : `${SYMBOL}|${MARKET}|${tf}`;
  tfGroup.querySelectorAll('[data-tf]').forEach(b => b.setAttribute('aria-pressed', b.dataset.tf === tf));
  const tfEl = $('tf-label'); if (tfEl) tfEl.textContent = TFS[tf].name;
  document.title = `${SYM_LABEL} ${TFS[tf].name} Bot2 Live`;
  const p = new URLSearchParams(location.search); p.set('interval', tf);
  history.replaceState(null, '', '?' + p.toString());
  prevClose = null; $('lv-px').textContent = '—'; $('lv-ch').textContent = '';
  $('boot-hd').textContent = `Đang dựng chart live ${TFS[tf].name}`;

  try {
    if (FEED === 'mt5') await mt5Info.catch(() => { throw new Error(
      'không kết nối được MT5 trên máy (' + MT5_URL + '). Mở MT5, chạy bot2/mt5_feed.bat rồi ' +
      'mở chart tại http://127.0.0.1:8770/?symbol=XAUUSDT&interval=15m'); });
    const [saved, seeds] = await Promise.all([store.get(key), seedIndex]);
    if (token !== loadToken) return;
    const seed = seeds && seeds[tf];
    const want = START_PARAM || (seed ? seed.start : fallbackStart(tf));
    const c = cur = {tf, key, start: want, n: 0, lastT: null, hLastT: null, ckpt: null, loading: true};
    let shown = false, pending = null;   // pending: dữ liệu chart chưa lưu vào IndexedDB

    if (saved && saved.version === VERSION && saved.start <= want && saved.ckpt && saved.payload) {
      Object.assign(c, {start: saved.start, n: saved.n, lastT: saved.lastT, hLastT: saved.hLastT ?? null, ckpt: saved.ckpt});
      render(JSON.parse(saved.payload), c, !first); shown = true;
      setStatus('poll', `Bản lưu ${new Date(saved.savedAt).toLocaleString('vi-VN',{hour12:false})} — đang lấy nến mới…`);
    } else if (seed && seed.start <= want) {
      showOverlay(true);
      setBoot(`Đang tải dữ liệu Bot2 tính sẵn (${seed.bars.toLocaleString('vi-VN')} nến từ ${fmtDate(seed.start)})…`);
      const [text, ckpt] = await Promise.all([
        fetch(`${seed.json}?v=${VERSION}`).then(r => { if (!r.ok) throw new Error('seed ' + r.status); return r.text(); }),
        fetch(`${seed.pkl}?v=${VERSION}`).then(r => { if (!r.ok) throw new Error('seed ' + r.status); return r.arrayBuffer(); }),
      ]);
      if (token !== loadToken) return;
      Object.assign(c, {start: seed.start, n: seed.bars, lastT: seed.last, hLastT: seed.hLast ?? null, ckpt});
      render(JSON.parse(text), c, !first); shown = true; pending = text;
      setStatus('poll', 'Dữ liệu tính sẵn — đang lấy nến mới…');
    }
    if (shown) connect(tf, token);   // giá chạy ngay, Bot2 bổ sung nến mới ở nền

    if (!shown) {   // không có bản lưu/seed phù hợp: chạy Bot2 từ đầu trong trình duyệt
      showOverlay(true); setBoot(`Đang tải nến từ ${FEED_NAME}…`);
      const rows = await fetchClosed(tf, Date.parse(want + 'T00:00:00Z'), token);
      if (token !== loadToken) return;
      if (!rows.length) throw new Error(`${FEED_NAME} không trả về nến nào.`);
      if (HIGHER[tf]) setBoot(`Đang tải nến ${TFS[HIGHER[tf]].name} để lọc theo trend khung lớn…`);
      const higher = await fetchHigher(c, token);
      if (token !== loadToken) return;
      running = true;
      try {
        const m = await runBot(c, rows, higher, setBoot);
        if (token !== loadToken) return;
        adopt(c, m); render(JSON.parse(m.payload), c, !first); save(c, m.payload);
        setStatus('poll', `Bot2 xong (${m.added.toLocaleString('vi-VN')} nến, ${(m.ms/1000).toFixed(1)}s) — đang nối WebSocket…`);
      } finally { running = false; }
      connect(tf, token);
    } else {        // bù các nến đóng sau bản lưu/seed
      const fresh = await fetchAfter(c, token);
      if (token !== loadToken) return;
      if (fresh.length) {
        const higher = await fetchHigher(c, token);
        if (token !== loadToken) return;
        running = true;
        try {
          const m = await runBot(c, fresh, higher);
          if (token !== loadToken) return;
          adopt(c, m); render(JSON.parse(m.payload), c, false); pending = m.payload;
          setStatus(box.dataset.s, `Bot2 tính thêm ${m.added.toLocaleString('vi-VN')} nến (${(m.ms/1000).toFixed(1)}s)`);
        } finally { running = false; }
      }
      if (pending) save(c, pending);
    }
    c.loading = false;
  } catch(e) {
    if (token !== loadToken) return;
    setBoot('Lỗi: ' + e.message + ' — tải lại trang để thử lại.' +
            (FEED === 'mt5' ? ' (Dùng giá Binance: thêm &feed=binance vào địa chỉ.)' : ' (Binance chặn truy cập từ một số quốc gia, ví dụ Mỹ.)'));
    showOverlay(true);
    setStatus('off', 'Không khởi động được');
  }
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
  document.title = `${fmt(b.close)} · ${FEED === 'mt5' ? MT5_SYMBOLS[SYMBOL] : SYMBOL} ${TFS[cur.tf].name}${open ? ` · ${open} lệnh mở` : ''}`;
}
function connect(tf, token){
  if (token !== loadToken) return;
  if (FEED === 'mt5') { startPolling(tf, token); return; }
  try { ws = new WebSocket(`${WS_BASE}${SYMBOL.toLowerCase()}@kline_${tf}`); } catch(e) { startPolling(tf, token); return; }
  const sock = ws;
  sock.onopen = () => { lastMsg = Date.now(); syncClosed(); };
  sock.onmessage = ev => {
    if (token !== loadToken) return;
    const k = JSON.parse(ev.data).k; if (!k) return;
    retry = 1000; stopPolling();
    onBar({time: k.t/1000, open: +k.o, high: +k.h, low: +k.l, close: +k.c});
    if (!running && !cur.loading) setStatus('on', `Live · ${clock()}`);
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
  let barT = null;
  const run = async () => {
    try {
      const k = (await (await fetch(`${REST}?symbol=${SYMBOL}&interval=${tf}&limit=1`, {cache: 'no-store'})).json())[0];
      if (token !== loadToken) return;
      onBar({time: k[0]/1000, open: +k[1], high: +k[2], low: +k[3], close: +k[4]});
      if (barT !== null && k[0] !== barT) setTimeout(syncClosed, 500);
      barT = k[0];
      if (!running && !cur.loading) setStatus(FEED === 'mt5' ? 'on' : 'poll', `${FEED === 'mt5' ? 'MT5 1s' : 'REST 2s'} · ${clock()}`);
    } catch(e) { setStatus('off', `Mất kết nối ${FEED_NAME} — đang thử lại`); }
  };
  run(); pollTimer = setInterval(run, FEED === 'mt5' ? 1000 : 2000);
}
function stopPolling(){ clearInterval(pollTimer); pollTimer = null; }

setInterval(syncClosed, 60000);
// WebSocket mở nhưng im lặng quá 10 giây: chuyển sang REST và kết nối lại.
setInterval(() => { if (ws && ws.readyState === 1 && !pollTimer && Date.now() - lastMsg > 10000) ws.close(); }, 5000);
show(TFS[q.get('interval')] ? q.get('interval') : '1h');
})();
