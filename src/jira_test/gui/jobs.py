"""One subprocess per operation; reader threads never interact with Tk."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue

from .storage import Redactor


class JobController:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._events: Queue[dict] = Queue()
        self._operation = ""

    @property
    def running(self) -> bool:
        return bool(
            self._process
            and (self._process.poll() is None or self._reader and self._reader.is_alive())
        )

    def start(self, operation: str, payload: dict) -> bool:
        if self.running:
            return False
        self._operation = operation
        environment = dict(os.environ)
        package_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (package_root, environment.get("PYTHONPATH", "")))
        )
        environment["PYTHONUNBUFFERED"] = "1"
        credentials = payload.get("credentials", {})
        credentials = {
            key: credentials.get(key, environment.get("JIRA_" + key.upper(), ""))
            for key in ("username", "password")
        }
        environment.pop("JIRA_USERNAME", None)
        environment.pop("JIRA_PASSWORD", None)
        redactor = Redactor(credentials)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "jira_test.gui.worker"],
            cwd=self.workspace,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(
            target=self._read, args=(self._process, redactor), daemon=True
        )
        self._reader.start()
        assert self._process.stdin is not None
        self._process.stdin.write(
            json.dumps(
                {
                    **payload,
                    "operation": operation,
                    "workspace": str(self.workspace),
                    "credentials": credentials,
                }
            )
            + "\n"
        )
        self._process.stdin.flush()
        return True

    def _read(self, process: subprocess.Popen, redactor: Redactor) -> None:
        finished = False
        assert process.stdout is not None
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict) or "type" not in event:
                        raise ValueError("Not a worker event")
                except ValueError:
                    event = {
                        "type": "log",
                        "operation": self._operation,
                        "data": {"message": line.rstrip()},
                    }
                finished = finished or event["type"] == "finished"
                self._events.put(redactor.data(event))
        finally:
            code = process.wait()
            process.stdout.close()
            if process.stdin:
                process.stdin.close()
            if not finished:
                self._events.put(
                    {
                        "type": "error",
                        "operation": self._operation,
                        "data": {"message": "Worker exited before finalizing reports"},
                    }
                )
                self._events.put(
                    {
                        "type": "finished",
                        "operation": self._operation,
                        "data": {"outcome": "incomplete", "exitstatus": code},
                    }
                )

    def poll(self) -> list[dict]:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                return events

    def cancel(self) -> None:
        if self._process and self._process.poll() is None and self._process.stdin:
            try:
                self._process.stdin.write('{"command":"cancel"}\n')
                self._process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
