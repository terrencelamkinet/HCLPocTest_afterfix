#!/usr/bin/env python3
"""SPA static server for PenguinCRM Admin Console (adm.penguincrm.io).

問題（2026-09-10）: `python3 -m http.server` 對唔存在嘅路徑回 404，所以
adm.penguincrm.io/tenants 等前端 route 直接 404。SPA 應該任何 path 都
serve index.html（client 自己 render）。

用法: python3 serve_spa.py <dist_dir> [port] [bind]
"""
import http.server
import os
import sys

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "dist")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5175
BIND = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
INDEX = os.path.join(ROOT, "index.html")


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def translate_path(self, path):
        p = super().translate_path(path)
        if os.path.isfile(p):
            return p
        if os.path.isdir(p):
            idx = os.path.join(p, "index.html")
            if os.path.isfile(idx):
                return idx
        # 唔存在（包括 /tenants、/reports/123 等前端 route）→ index.html
        return INDEX

    def log_message(self, *args):  # 靜音（避免洗版）
        pass


if __name__ == "__main__":
    os.chdir(ROOT)
    httpd = http.server.ThreadingHTTPServer((BIND, PORT), SPAHandler)
    print(f"[serve_spa] {ROOT} on http://{BIND}:{PORT}", flush=True)
    httpd.serve_forever()
