"""Dựng trang GitHub Pages cho Bot2 Live vào thư mục _site/.

    python web/build_site.py            # rồi mở _site/ bằng một web server tĩnh bất kỳ

Trang dùng chung data/chart_template/template.html. Code Python của Bot2 được chép nguyên
vào _site/py/ để trình duyệt chạy bằng Pyodide, nên sửa rule rồi push là trang dùng rule mới.
GitHub Actions (.github/workflows/pages.yml) chạy script này mỗi lần push lên main.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
TEMPLATE = ROOT / "data" / "chart_template" / "template.html"
PY_SOURCES = [ROOT / "trading_bot", ROOT / "data" / "chart_template" / "build_chart.py"]

LIVE_CSS = """<style>
.live{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-variant-numeric:tabular-nums}
.live .dot{width:8px;height:8px;border-radius:50%;background:var(--flat);flex:none}
.live[data-s="on"] .dot{background:var(--up);animation:lp 1.6s ease-in-out infinite}
.live[data-s="poll"] .dot{background:var(--accent)}
.live[data-s="off"] .dot{background:var(--down)}
.live b{font-size:17px;font-weight:500}.live .up{color:var(--up)}.live .dn{color:var(--down)}
.live small{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.boot{position:absolute;inset:0;z-index:5;display:grid;place-items:center;background:var(--panel);text-align:center;padding:16px}
.boot b{display:block;font-size:16px;font-weight:600;margin-bottom:6px}
.boot span{color:var(--muted);font-size:13px}
@keyframes lp{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.live .dot{animation:none!important}}
</style>
"""


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "web").mkdir(parents=True)

    html = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")  # git autocrlf trên Windows
    marker = "<script>\nconst D = __DATA_JSON__;"
    if marker not in html:
        raise SystemExit("template.html đã đổi cấu trúc: không tìm thấy khối 'const D = __DATA_JSON__'.")
    html = (html
            .replace("__TITLE__", "BTCUSDT.P Bot2 Live")
            .replace("__SYMBOL__", "BTCUSDT.P")
            # Mã và khung do app.js đặt theo tham số URL (?symbol=&interval=).
            .replace("</span>__TF__ ·", '</span><span id="tf-label">H1</span> ·')
            .replace("__TF__", "đang chọn")
            # Khối chart chỉ chạy khi app.js đã có dữ liệu từ Bot2.
            .replace(marker, '<script type="text/x-chart" id="chart-main">\nconst D = window.__D;'))
    html = html.replace("<div class=\"wrap\">", LIVE_CSS + "<div class=\"wrap\">", 1)
    html += '\n<script src="web/app.js"></script>\n'
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    for name in ("app.js", "worker.js"):
        shutil.copy2(WEB / name, out / "web" / name)

    manifest: list[str] = []
    for source in PY_SOURCES:
        files = sorted(source.rglob("*.py")) if source.is_dir() else [source]
        for path in files:
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            target = out / "py" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            manifest.append(rel)
    (out / "py" / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Đã dựng {out} ({len(manifest)} file Python).")


if __name__ == "__main__":
    build(ROOT / "_site")
