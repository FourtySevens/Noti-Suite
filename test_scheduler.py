import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib import error, request

from scheduler import Config, Store, make_handler, parse_time, worker


class Receiver(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        Receiver.received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        Receiver.received = []
        self.ntfy = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        self.ntfy_thread = threading.Thread(target=self.ntfy.serve_forever, daemon=True)
        self.ntfy_thread.start()
        env = {
            "SCHEDULER_API_KEY": "x" * 40,
            "NTFY_BASE_URL": f"http://127.0.0.1:{self.ntfy.server_port}",
            "DATABASE_PATH": str(Path(self.temp.name) / "jobs.db"),
            "EVENTS_PATH": str(Path(__file__).with_name("events.json")),
        }
        with patch.dict(os.environ, env):
            self.config = Config()
        self.store = Store(self.config.database)
        self.stop = threading.Event()
        self.dispatcher = threading.Thread(target=worker, args=(self.config, self.store, self.stop), daemon=True)
        self.dispatcher.start()
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.config, self.store))
        self.api_thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.api_thread.start()

    def tearDown(self):
        self.stop.set()
        self.dispatcher.join(timeout=3)
        self.api.shutdown()
        self.api_thread.join(timeout=3)
        self.api.server_close()
        self.ntfy.shutdown()
        self.ntfy_thread.join(timeout=3)
        self.ntfy.server_close()
        self.temp.cleanup()

    def call(self, method, path, body=None, key=True, idem=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["X-API-Key"] = "x" * 40
        if idem:
            headers["Idempotency-Key"] = idem
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(f"http://127.0.0.1:{self.api.server_port}{path}", data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_event_pushes_preset_immediately_and_idempotently(self):
        path = "/v1/projects/backups/events/failed"
        status, job = self.call("POST", path, idem="failure-1")
        self.assertEqual(status, 201)
        status, repeated = self.call("POST", path, idem="failure-1")
        self.assertEqual(status, 200)
        self.assertEqual(job["id"], repeated["id"])
        deadline = time.monotonic() + 4
        while not Receiver.received and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(Receiver.received, [("/notif-backups", b"Check the backup logs.")])
        status, current = self.call("GET", f"/v1/projects/backups/notifications/{job['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(current["status"], "sent")

    def test_future_job_can_be_cancelled_and_api_requires_key(self):
        path = "/v1/projects/demo/notifications"
        status, _ = self.call("GET", path, key=False)
        self.assertEqual(status, 401)
        status, job = self.call("POST", path, {"message": "Later", "send_at": "2099-01-01T12:00:00Z"})
        self.assertEqual(status, 201)
        self.assertEqual(job["status"], "pending")
        status, cancelled = self.call("DELETE", f"{path}/{job['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(Receiver.received, [])

    def test_recurring_job_moves_to_next_interval(self):
        self.stop.set()
        self.dispatcher.join(timeout=3)
        job, _ = self.store.create("metrics", {
            "message": "Hourly check", "title": "", "priority": 3, "tags": [],
            "send_at": "2020-01-01T00:00:00Z", "every_seconds": 3600,
        }, None)
        row = self.store.claim()
        self.assertEqual(row["id"], job["id"])
        self.store.finish(row, None)
        current = self.store.get("metrics", job["id"])
        self.assertEqual(current["status"], "pending")
        self.assertIsNotNone(current["last_sent_at"])
        self.assertGreater(parse_time(current["send_at"]), parse_time(current["last_sent_at"]))


if __name__ == "__main__":
    unittest.main()
