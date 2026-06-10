#!/usr/bin/env python3
"""
Game Lead Finder — Local Server
Usage: py server.py [--mode small|standard] [--port 5000]

Opens output.html in your browser and handles CSV uploads + pipeline re-runs.
"""
import argparse, email.parser, json, re, shutil, subprocess, sys, tempfile, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

PIPELINE    = Path(__file__).parent / "pipeline.py"
OUTPUT      = Path(__file__).parent / "output.html"
STATE_FILE  = Path(__file__).parent / "games_state.json"

MODE = "small"   # overridden by --mode flag


def parse_multipart(content_type: str, body: bytes):
    """
    Parse a multipart/form-data body.
    Returns (files, fields) where:
      files  = list of (filename, bytes)
      fields = dict of field_name -> value
    """
    # Build a minimal email message so email.parser can handle the multipart
    msg = email.parser.BytesParser().parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )

    files  = []
    fields = {}

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        cd = part.get("Content-Disposition", "")
        # extract name and filename from Content-Disposition header
        name_m     = re.search(r'name="([^"]*)"',     cd)
        filename_m = re.search(r'filename="([^"]*)"', cd)
        if not name_m:
            continue
        name     = name_m.group(1)
        filename = filename_m.group(1) if filename_m else None
        payload  = part.get_payload(decode=True) or b""

        if filename:
            files.append((filename, payload))
        else:
            fields[name] = payload.decode("utf-8", errors="replace")

    return files, fields


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        import sys
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/output.html"):
            self._serve_file(OUTPUT, "text/html; charset=utf-8")
        elif parsed.path == "/output_preview.html":
            self._serve_file(OUTPUT.parent / "output_preview.html", "text/html; charset=utf-8")
        elif parsed.path == "/games_state.json":
            self._serve_file(STATE_FILE, "application/json; charset=utf-8")
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path == "/save-state":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                data = json.loads(body)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                self._respond(200, "application/json", b'{"ok":true}')
            except Exception as e:
                self._respond(500, "application/json",
                              json.dumps({"ok": False, "error": str(e)}).encode())
            return

        if self.path != "/upload":
            self._respond(404, "text/plain", b"Not found")
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._respond(400, "text/plain", b"Expected multipart/form-data")
            return

        # Read full body then parse
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            print(f"[upload] content-type={content_type[:80]}  length={length}  body_read={len(body)}")
            files, fields = parse_multipart(content_type, body)
            print(f"[upload] files={[f for f,_ in files]}  fields={fields}")
        except Exception as e:
            import traceback; traceback.print_exc()
            body = f'{{"ok":false,"error":"Parse error: {e}"}}'.encode()
            self._respond(500, "application/json", body)
            return

        if not files:
            self._respond(400, "application/json",
                          b'{"ok":false,"error":"No files received"}')
            return

        preview = fields.get("preview", "false") == "true"

        # Save uploaded files to temp dir
        tmp_dir = Path(tempfile.mkdtemp())
        csv_paths = []
        try:
            for filename, data in files:
                dest = tmp_dir / Path(filename).name
                dest.write_bytes(data)
                csv_paths.append(str(dest))

            # Run pipeline
            cmd = [sys.executable, str(PIPELINE), "--mode", MODE] + csv_paths
            if preview:
                cmd.append("--preview")
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(PIPELINE.parent))

            if result.returncode != 0:
                msg = (result.stderr or result.stdout or "Unknown error").strip()
                self._respond(500, "application/json",
                              json.dumps({"ok": False, "error": msg}).encode())
                return

            summary  = (result.stdout or "").strip()
            redirect = "/output_preview.html" if preview else "/"
            self._respond(200, "application/json",
                          json.dumps({"ok": True, "summary": summary, "redirect": redirect}).encode())

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _serve_file(self, path: Path, mime: str):
        if not path.exists():
            self._respond(404, "text/plain", b"output.html not found - run pipeline first")
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
    parser = argparse.ArgumentParser(description="Game Lead Finder - Local Server")
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
