import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from server import VERSION

TARGETS = ["synthv", "ace", "vocaloid5", "vocaloid6"]


class InfoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.calls.append(self.path)
        content = json.dumps(self.server.identity).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


@contextmanager
def service(identity):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), InfoHandler)
    httpd.identity = identity
    httpd.calls = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.environment = dict(os.environ, VVTALK_DATA_DIR=str(self.folder),
                                USERPROFILE=str(self.folder / "profile"),
                                PYTHONIOENCODING="utf-8")
        self.server = SimpleNamespace(DATA=self.folder, initialize=lambda: None)

    def tearDown(self):
        self.temporary.cleanup()

    def run_python(self, arguments):
        return subprocess.run([sys.executable, *arguments], cwd=ROOT,
                              env=self.environment, capture_output=True,
                              text=True, encoding="utf-8", timeout=20,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def launch(self, port, status):
        return self.run_python([str(ROOT / "app.py"), "--serve", "--port", str(port),
                                "--status-file", str(status)])

    def child_lock(self, port):
        code = """import json, sys
from pathlib import Path
from types import SimpleNamespace
import app
server = SimpleNamespace(DATA=Path(sys.argv[1]), initialize=lambda: None)
with app.instance_lock(server, int(sys.argv[2])) as owned:
    print(json.dumps({'owned': owned}))
"""
        completed = self.run_python(["-c", code, str(self.folder), str(port)])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)["owned"]

    def assert_guard_released(self, port):
        with app.instance_lock(self.server, port) as owned:
            self.assertTrue(owned, "The completed startup must release its instance guard.")

    def test_serve_reuses_existing_server_and_preserves_original_pid(self):
        identity = {"version": VERSION, "targets": TARGETS,
                    "pid": os.getpid(), "data_dir": str(self.folder)}
        status = self.folder / "reused.json"
        with service(identity) as original:
            completed = self.launch(original.server_port, status)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(status.read_text(encoding="utf-8"))
            self.assertTrue(result["reused"])
            self.assertEqual(result["pid"], os.getpid())
            self.assertEqual(result["url"], f"http://127.0.0.1:{original.server_port}")
            self.assertFalse((self.folder / "runtime.json").exists())
            with urllib.request.urlopen(result["url"] + "/api/info", timeout=3) as response:
                self.assertEqual(json.load(response), identity)
            self.assertEqual(original.calls, ["/api/info", "/api/info"])
            self.assert_guard_released(original.server_port)

    @unittest.skipUnless(os.name == "nt", "Windows msvcrt instance locking")
    def test_instance_lock_excludes_another_process_and_releases_after_exception(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        with app.instance_lock(self.server, port) as owned:
            self.assertTrue(owned)
            self.assertFalse(self.child_lock(port))
        self.assertTrue(self.child_lock(port))
        with self.assertRaisesRegex(RuntimeError, "startup interrupted"):
            with app.instance_lock(self.server, port) as owned:
                self.assertTrue(owned)
                self.assertFalse(self.child_lock(port))
                raise RuntimeError("startup interrupted")
        self.assertTrue(self.child_lock(port))
        self.assert_guard_released(port)

    def test_unknown_application_port_is_rejected_without_binding(self):
        with service({}) as original:
            for index, identity in enumerate([
                {"version": "another-application", "targets": TARGETS},
                {"version": VERSION, "targets": ["another-target"]},
            ]):
                with self.subTest(identity=identity):
                    original.identity = identity
                    status = self.folder / f"unknown-{index}.json"
                    completed = self.launch(original.server_port, status)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(f"端口 {original.server_port} 已占用", completed.stderr)
                    self.assertFalse(status.exists())
                    self.assertFalse((self.folder / "runtime.json").exists())
                    with urllib.request.urlopen(f"http://127.0.0.1:{original.server_port}/api/info",
                                                timeout=3) as response:
                        self.assertEqual(json.load(response), identity)
                    self.assert_guard_released(original.server_port)
            self.assertEqual(original.calls, ["/api/info"] * 4)


if __name__ == "__main__":
    unittest.main()
