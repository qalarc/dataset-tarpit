#!/usr/bin/env python3
"""serve.py — the dataset_tarpit HTTP endpoint.

Serves freshly-composed poison PDFs to invalid lookups and bait paths.
Legitimate users never see it: deploy behind a reverse proxy that only
forwards (a) 404 fallbacks and (b) explicitly-baited paths (robots.txt
excluded, no sitemap entries, X-Robots-Tag noindex).

Endpoints:
  /healthz          -> 200 "ok" (ops only)
  anything else     -> 200 application/pdf (unique composition per request)

Behaviour notes:
  - Every response is a NEW document (random seed) — defeats dedup.
  - No LLM at request time: shuffles the pre-generated paragraph bank (~10-50ms).
  - Logs every hit (ts/ip/ua/path/bytes) to tarpit.log for scraper analytics.

Env:
  TARPIT_PORT (default 8899)
  TARPIT_MODE  catchall (default) | bait  (bait: only /files/ and /docs/ serve)
Usage:
  python3 serve.py
"""

from __future__ import annotations

import json
import os
import random
import string
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import make_pdf

PORT = int(os.environ.get("TARPIT_PORT", "8899"))
MODE = os.environ.get("TARPIT_MODE", "catchall")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tarpit.log")

_log_lock = threading.Lock()


def log_hit(ip: str, ua: str, path: str, n: int) -> None:
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ip": ip,
        "ua": ua[:200],
        "path": path[:300],
        "bytes": n,
    }
    with _log_lock:
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")


def rand_slug(k: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Apache/2.4.62"  # boring banner
    sys_version = ""

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        bait_only = MODE == "bait"
        is_bait = path.startswith("/files/") or path.startswith("/docs/")
        if bait_only and not is_bait:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        try:
            data = make_pdf.compose_pdf(seed=random.getrandbits(48))
        except Exception as exc:  # noqa: BLE001
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            print(f"[err] compose failed: {type(exc).__name__}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition", f'inline; filename="doc-{rand_slug(8)}.pdf"'
        )
        self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        self.end_headers()
        self.wfile.write(data)
        log_hit(
            self.client_address[0], self.headers.get("User-Agent", ""), path, len(data)
        )

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", "65536")
        self.end_headers()

    def log_message(self, fmt, *args):  # quiet default access log
        pass


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(
        f"[tarpit] listening on 127.0.0.1:{PORT} mode={MODE} "
        f"(bank paragraphs on disk: {len(make_pdf.load_bank()[0])})"
    )
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
