"""Small persistent notification scheduler for ntfy."""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.header import Header
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request

LOG = logging.getLogger("notif_scheduler")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_BODY = 8192


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("send_at must be an ISO 8601 date-time with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("send_at must be an ISO 8601 date-time with a timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("send_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_text(value: object, field: str, limit: int, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value.encode("utf-8")) > limit:
        raise ValueError(f"{field} must be a string of 1 to {limit} bytes" if required else f"{field} must be a string of at most {limit} bytes")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{field} contains control characters")
    return value


class Config:
    def __init__(self) -> None:
        self.api_key = os.environ.get("SCHEDULER_API_KEY", "")
        if len(self.api_key) < 32 or self.api_key.startswith("replace-with-"):
            raise ValueError("SCHEDULER_API_KEY must contain at least 32 characters")
        self.ntfy_base = os.environ.get("NTFY_BASE_URL", "http://ntfy:80").rstrip("/")
        parsed = parse.urlparse(self.ntfy_base)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("NTFY_BASE_URL must be an HTTP(S) server origin")
        self.ntfy_token = os.environ.get("NTFY_TOKEN", "")
        self.topic_prefix = os.environ.get("NTFY_TOPIC_PREFIX", "notif-")
        if not NAME.fullmatch(self.topic_prefix + "example"):
            raise ValueError("NTFY_TOPIC_PREFIX must contain only letters, digits, _ or -")
        self.database = Path(os.environ.get("DATABASE_PATH", "./data/scheduler.db"))
        self.host = os.environ.get("SCHEDULER_BIND", "0.0.0.0")
        self.port = int(os.environ.get("SCHEDULER_PORT", "8080"))
        events_path = Path(os.environ.get("EVENTS_PATH", "./events.json"))
        try:
            events = json.loads(events_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load event presets from {events_path}") from exc
        if not isinstance(events, dict):
            raise ValueError("Event presets must be a JSON object")
        self.events: dict[str, dict[str, dict]] = {}
        for project, presets in events.items():
            if not NAME.fullmatch(project) or not isinstance(presets, dict):
                raise ValueError("Each event project must have a valid name and event object")
            self.events[project] = {}
            for event_name, preset in presets.items():
                if not NAME.fullmatch(event_name) or not isinstance(preset, dict) or set(preset) - {"message", "title", "priority", "tags"}:
                    raise ValueError(f"Invalid event preset {project}/{event_name}")
                self.events[project][event_name] = validate_job(preset)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    message TEXT NOT NULL,
                    title TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    tags TEXT NOT NULL,
                    send_at TEXT NOT NULL,
                    every_seconds INTEGER,
                    status TEXT NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_sent_at TEXT,
                    last_error TEXT,
                    lease_until TEXT,
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(project, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project, created_at);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public(row: sqlite3.Row) -> dict:
        return {key: row[key] for key in ("id", "project", "message", "title", "priority", "send_at", "every_seconds", "status", "attempts", "last_sent_at", "last_error", "created_at")} | {"tags": json.loads(row["tags"])}

    def create(self, project: str, data: dict, idempotency_key: str | None) -> tuple[dict, bool]:
        now = iso(utc_now())
        job_id = str(uuid.uuid4())
        with self.connection() as db:
            try:
                db.execute("""INSERT INTO jobs
                    (id, project, message, title, priority, tags, send_at, every_seconds,
                     status, next_attempt_at, idempotency_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                    (job_id, project, data["message"], data["title"], data["priority"],
                     json.dumps(data["tags"]), data["send_at"], data["every_seconds"],
                     data["send_at"], idempotency_key, now))
            except sqlite3.IntegrityError:
                row = db.execute("SELECT * FROM jobs WHERE project=? AND idempotency_key=?", (project, idempotency_key)).fetchone()
                return self.public(row), False
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return self.public(row), True

    def get(self, project: str, job_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE project=? AND id=?", (project, job_id)).fetchone()
            return self.public(row) if row else None

    def list(self, project: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM jobs WHERE project=? ORDER BY created_at DESC LIMIT 100", (project,)).fetchall()
            return [self.public(row) for row in rows]

    def cancel(self, project: str, job_id: str) -> dict | None:
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='cancelled' WHERE project=? AND id=? AND status IN ('pending', 'sending')", (project, job_id))
            row = db.execute("SELECT * FROM jobs WHERE project=? AND id=?", (project, job_id)).fetchone()
            return self.public(row) if row else None

    def claim(self) -> sqlite3.Row | None:
        now = iso(utc_now())
        lease = iso(utc_now() + timedelta(seconds=60))
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM jobs WHERE
                (status='pending' AND send_at<=? AND next_attempt_at<=?)
                OR (status='sending' AND lease_until<=?)
                ORDER BY next_attempt_at LIMIT 1""", (now, now, now)).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='sending', lease_until=? WHERE id=?", (lease, row["id"]))
            return row

    def finish(self, row: sqlite3.Row, error_message: str | None) -> None:
        now = utc_now()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT status FROM jobs WHERE id=?", (row["id"],)).fetchone()
            if not current or current["status"] != "sending":
                return
            if error_message:
                attempts = row["attempts"] + 1
                retry = iso(now + timedelta(seconds=min(3600, 30 * 2 ** min(attempts - 1, 7))))
                db.execute("""UPDATE jobs SET status='pending', attempts=?, next_attempt_at=?,
                    lease_until=NULL, last_error=? WHERE id=?""",
                    (attempts, retry, error_message[:300], row["id"]))
            elif row["every_seconds"]:
                scheduled = parse_time(row["send_at"])
                interval = timedelta(seconds=row["every_seconds"])
                if scheduled <= now:
                    elapsed = (now - scheduled).total_seconds()
                    scheduled += interval * (int(elapsed // row["every_seconds"]) + 1)
                next_at = iso(scheduled)
                db.execute("""UPDATE jobs SET status='pending', send_at=?, next_attempt_at=?,
                    attempts=0, last_sent_at=?, last_error=NULL, lease_until=NULL WHERE id=?""",
                    (next_at, next_at, iso(now), row["id"]))
            else:
                db.execute("""UPDATE jobs SET status='sent', attempts=0, last_sent_at=?,
                    last_error=NULL, lease_until=NULL WHERE id=?""", (iso(now), row["id"]))


def validate_job(body: object) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    unknown = set(body) - {"message", "title", "priority", "tags", "send_at", "every_seconds"}
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    message = validate_text(body.get("message"), "message", 4000, required=True)
    title = validate_text(body.get("title", ""), "title", 200)
    if "\n" in title or "\r" in title:
        raise ValueError("title must be one line")
    priority = body.get("priority", 3)
    if type(priority) is not int or not 1 <= priority <= 5:
        raise ValueError("priority must be an integer from 1 to 5")
    tags = body.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 10 or any(
        not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", tag) for tag in tags
    ):
        raise ValueError("tags must be a list of at most 10 short tag names")
    send_at = parse_time(body["send_at"]) if "send_at" in body else utc_now()
    every = body.get("every_seconds")
    if every is not None and (type(every) is not int or not 60 <= every <= 31_536_000):
        raise ValueError("every_seconds must be an integer from 60 to 31536000")
    return {"message": message, "title": title, "priority": priority, "tags": tags,
            "send_at": iso(send_at), "every_seconds": every}


def publish(config: Config, row: sqlite3.Row) -> None:
    topic = config.topic_prefix + row["project"]
    url = f"{config.ntfy_base}/{parse.quote(topic)}"
    headers = {"Content-Type": "text/plain; charset=utf-8", "Priority": str(row["priority"])}
    if row["title"]:
        headers["Title"] = Header(row["title"], "utf-8").encode()
    if row["tags"] != "[]":
        headers["Tags"] = ",".join(json.loads(row["tags"]))
    if config.ntfy_token:
        headers["Authorization"] = f"Bearer {config.ntfy_token}"
    req = request.Request(url, data=row["message"].encode("utf-8"), headers=headers, method="POST")
    with request.urlopen(req, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"ntfy returned HTTP {response.status}")


def worker(config: Config, store: Store, stop: threading.Event) -> None:
    while not stop.is_set():
        row = store.claim()
        if row is None:
            stop.wait(1)
            continue
        error_message = None
        try:
            publish(config, row)
        except (error.HTTPError, error.URLError, OSError, RuntimeError) as exc:
            error_message = str(exc)
            LOG.warning("Delivery failed for job %s: %s", row["id"], error_message)
        store.finish(row, error_message)


def make_handler(config: Config, store: Store):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, payload: object) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self) -> bool:
            supplied = self.headers.get("X-API-Key", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), config.api_key.encode("utf-8")):
                self.reply(HTTPStatus.UNAUTHORIZED, {"error": "Invalid API key"})
                return False
            return True

        def handle_api(self, method: str) -> None:
            path = parse.urlsplit(self.path).path
            if path == "/healthz" and method == "GET":
                self.reply(200, {"status": "ok"})
                return
            parts = path.strip("/").split("/")
            if (len(parts) not in (4, 5) or parts[:2] != ["v1", "projects"]
                or parts[3] not in ("notifications", "events")
                or not NAME.fullmatch(parts[2]) or len(config.topic_prefix + parts[2]) > 64):
                self.reply(404, {"error": "Not found"})
                return
            project = parts[2]
            if not self.authorized():
                return
            if parts[3] == "events":
                if method != "POST" or len(parts) != 5:
                    self.reply(405, {"error": "Method not allowed"})
                    return
                preset = config.events.get(project, {}).get(parts[4])
                if preset is None:
                    self.reply(404, {"error": "Unknown event"})
                    return
                idem = self.headers.get("Idempotency-Key")
                if idem is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", idem):
                    self.reply(400, {"error": "Idempotency-Key must be 1 to 128 letters, digits, _ or -"})
                    return
                job, created = store.create(project, {**preset, "send_at": iso(utc_now())}, idem)
                self.reply(201 if created else 200, job)
                return
            job_id = parts[4] if len(parts) == 5 else None
            if job_id and not re.fullmatch(r"[0-9a-f-]{36}", job_id):
                self.reply(404, {"error": "Not found"})
                return
            if method == "POST" and not job_id:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 1 or size > MAX_BODY:
                        raise ValueError("Body must be 1 to 8192 bytes")
                    body = json.loads(self.rfile.read(size))
                    data = validate_job(body)
                    idem = self.headers.get("Idempotency-Key")
                    if idem is not None and (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", idem)):
                        raise ValueError("Idempotency-Key must be 1 to 128 letters, digits, _ or -")
                    job, created = store.create(project, data, idem)
                except (ValueError, json.JSONDecodeError) as exc:
                    self.reply(400, {"error": str(exc)})
                    return
                self.reply(201 if created else 200, job)
            elif method == "GET" and not job_id:
                self.reply(200, {"notifications": store.list(project)})
            elif method == "GET" and job_id:
                job = store.get(project, job_id)
                self.reply(200, job) if job else self.reply(404, {"error": "Not found"})
            elif method == "DELETE" and job_id:
                job = store.cancel(project, job_id)
                self.reply(200, job) if job else self.reply(404, {"error": "Not found"})
            else:
                self.reply(405, {"error": "Method not allowed"})

        def do_GET(self) -> None:
            self.handle_api("GET")

        def do_POST(self) -> None:
            self.handle_api("POST")

        def do_DELETE(self) -> None:
            self.handle_api("DELETE")

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Config()
    store = Store(config.database)
    stop = threading.Event()
    dispatcher = threading.Thread(target=worker, args=(config, store, stop), daemon=True)
    dispatcher.start()
    server = ThreadingHTTPServer((config.host, config.port), make_handler(config, store))
    LOG.info("Scheduler listening on %s:%s", config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        stop.set()
        dispatcher.join(timeout=11)


if __name__ == "__main__":
    main()
