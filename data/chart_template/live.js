// Chế độ live cho Trade Explorer — live_server.py nhúng file này sau template.
(function(){
const cfg = window.LIVE_CONFIG;
const TC = window.TradeChart;
if (!cfg || !TC) return;
let version = cfg.version, lastMsg = 0, ws = null, retry = 1000, pollTimer = null, prevClose = null;

// Ô trạng thái đầu trang: chấm live + giá hiện tại + giờ cập nhật.
const style = document.createElement('style');
style.textContent = `.live{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-variant-numeric:tabular-nums}
.live .dot{width:8px;height:8px;border-radius:50%;background:var(--flat)}
.live[data-s="on"] .dot{background:var(--up);animation:lp 1.6s ease-in-out infinite}
.live[data-s="poll"] .dot{background:var(--accent)}
.live[data-s="off"] .dot{background:var(--down)}
.live b{font-size:17px;font-weight:500}.live .up{color:var(--up)}.live .dn{color:var(--down)}
.live small{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
@keyframes lp{50%{opacity:.35}}@media (prefers-reduced-motion:reduce){.live .dot{animation:none!important}}`;
document.head.appendChild(style);
const box = document.createElement('div');
box.className = 'kpi live'; box.dataset.s = 'off';
box.innerHTML = '<span class="dot" aria-hidden="true"></span><div><b id="lv-px">—</b> <span id="lv-ch"></span><br><small id="lv-st">Đang kết nối…</small></div>';
document.querySelector('header').appendChild(box);
const $ = id => document.getElementById(id);
const fmt = v => v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const clock = () => new Date().toLocaleTimeString('vi-VN',{hour12:false});

function setStatus(s, text){ box.dataset.s = s; $('lv-st').textContent = text; }

function onBar(b){
  TC.tick(b);
  const el = $('lv-px');
  el.textContent = fmt(b.close);
  el.className = prevClose == null || b.close === prevClose ? '' : b.close > prevClose ? 'up' : 'dn';
  prevClose = b.close;
  const ch = (b.close - b.open) / b.open * 100;
  $('lv-ch').innerHTML = `<span class="${ch>=0?'up':'dn'}">${ch>=0?'+':''}${ch.toFixed(2)}%</span>`;
  lastMsg = Date.now();
  const open = TC.openTrades();
  document.title = `${fmt(b.close)} · ${cfg.symbol}${open.length?` · ${open.length} lệnh mở`:''}`;
}

function connect(){
  try { ws = new WebSocket(cfg.ws); } catch(e){ startPolling(); return; }
  ws.onopen = () => { lastMsg = Date.now(); setStatus('on', 'Live · Binance WebSocket'); };
  ws.onmessage = ev => {
    const k = JSON.parse(ev.data).k; if (!k) return;
    retry = 1000; stopPolling();
    onBar({time:k.t/1000, open:+k.o, high:+k.h, low:+k.l, close:+k.c});
    setStatus('on', `Live · ${clock()}`);
    if (k.x) setTimeout(() => fetch('/api/refresh').catch(()=>{}), 1500); // nến vừa đóng
  };
  ws.onclose = () => { startPolling(); setTimeout(connect, retry); retry = Math.min(retry*2, 30000); };
  ws.onerror = () => { try { ws.close(); } catch(e){} };
}

// Dự phòng khi WebSocket bị chặn: hỏi server (server gọi REST Binance) mỗi 2 giây.
function startPolling(){
  if (pollTimer) return;
  const run = async () => {
    try { const r = await fetch('/api/tick'); if (!r.ok) throw 0; onBar(await r.json()); setStatus('poll', `REST 2s · ${clock()}`); }
    catch(e){ setStatus('off', 'Mất kết nối — đang thử lại'); }
  };
  run(); pollTimer = setInterval(run, 2000);
}
function stopPolling(){ clearInterval(pollTimer); pollTimer = null; }

// Nến mới đóng -> server chạy lại Bot2 -> nạp lệnh mới, giữ khung nhìn.
async function checkVersion(){
  try {
    const r = await fetch('/api/version'); const v = (await r.json()).version;
    if (v === version) return;
    const d = await (await fetch('/api/data')).json();
    version = d.version; TC.update(d.data);
  } catch(e){ setStatus('off', 'Server đã dừng — chạy lại live_server.py'); }
}
setInterval(checkVersion, 10000);
// WebSocket mở nhưng im lặng quá 10 giây: đóng để chuyển sang REST và kết nối lại.
setInterval(() => { if (ws && ws.readyState === 1 && !pollTimer && Date.now() - lastMsg > 10000) ws.close(); }, 5000);
connect();
})();
