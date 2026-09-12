from __future__ import annotations

import hashlib
import json
import os
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from deploy import napcat

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native NapCat matrix")


class _StatusHandler(BaseHTTPRequestHandler):
    state = "not_logged_in"

    def do_GET(self):
        body = json.dumps({"state": self.state}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def test_manual_qr_state_machine_never_exports_secret(tmp_path):
    archive = tmp_path / "napcat.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("napcat.exe", b"package")
    manifest = {
        "id": "napcat",
        "version": "1",
        "digest": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source": "pinned-source",
        "license": "notice",
        "sbom": "sbom",
        "platform": "windows-amd64",
    }
    napcat.install_archive(archive, manifest, tmp_path / "data")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert napcat.status(tmp_path / "data", observed="qr_waiting")["state"] == "qr_waiting"
        assert napcat.status(tmp_path / "data", observed="connected")["state"] == "connected"
        assert napcat.status(tmp_path / "data", observed="expired")["state"] == "expired"
        assert napcat.status(tmp_path / "data")["unattended"] is False
    finally:
        server.shutdown()
        thread.join(timeout=2)
