#!/usr/bin/env python3
"""
Game Lead Finder — Local Server
Usage: py server.py [--mode small|standard] [--port 5000]

Opens output.html in your browser and handles CSV uploads + pipeline re-runs.
"""
import argparse, shutil, subprocess, sys, tempfile, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import cgi, os

PIPELINE = Path(__file__).parent / "pipeline.py"
OUTPUT   = Path(__file__).parent / "output.html"

MODE = "small"   # overridden by --mode flag


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default request logging

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/output.html"):
            self._serve_file(OUTPUT, "text/html; charset=utf-8")
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path != "/upload":
            self._respond(404, "text/plain", b"Not found")
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._respond(400, "text/plain", b"Expected multipart/form-data")
            return

        # Parse multipart body
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
            },
        )

        files = form.getlist("csvfiles")
        if not files:
            self._respond(400, "application/json",
                          b'{"ok":false,"error":"No files received"}')
            return

        # Save uploaded files to temp dir
        tmp_dir = Path(tempfile.mkdtemp())
        csv_paths = []
        try:
            for f in files:
                dest = tmp_dir / Path(f.filename).name
                dest.write_bytes(f.file.read())
                csv_paths.append(str(dest))

            # Run pipeline
            cmd = [sys.executable, str(PIPELINE), "--mode", MODE] + csv_paths
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(PIPELINE.parent))

            if result.returncode != 0:
                msg = (result.stderr or result.stdout or "Unknown error").strip()
                body = f'{{"ok":false,"error":{msg!r}}}'.encode()
                self._respond(500, "application/json", body)
                return

            summary = (result.stdout or "").strip()
            body = f'{{"ok":true,"summary":{summary!r}}}'.encode()
            self._respond(200, "application/json", body)

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _serve_file(self, path: Path, mime: str):
        if not path.exists():
            self._respond(404, "text/plain", b"output.html not found — run pipeline first")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _respond(self, code: int, mime: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global MODE
    parser = argparse.ArgumentParser(description="Game Lead Finder — Local Server")
    parser.add_argument("--mode", choices=["small", "standard"], default="small")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    MODE = args.mode

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Game Lead Finder running at {url}")
    print(f"Mode: {args.mode}  |  Ctrl+C to stop")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
