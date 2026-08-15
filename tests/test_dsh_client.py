from __future__ import annotations

import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MODULE_PATH = (
    Path(__file__).parents[1] / "skills" / "dsh-web" / "scripts" / "dsh_client.py"
)
SPEC = importlib.util.spec_from_file_location("dsh_client", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dsh_client = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dsh_client
SPEC.loader.exec_module(dsh_client)


class FakeDshHandler(BaseHTTPRequestHandler):
    events: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self) -> None:
        length = int(self.headers["content-length"])
        request = json.loads(self.rfile.read(length))
        method = request["method"]
        if method == "session.create":
            value: Any = {"sessionId": "session-1"}
        elif method == "session.prompt":
            self.events.extend(
                [
                    {"event": {"seq": 2, "type": "turn/start", "data": {}}},
                    {
                        "event": {
                            "seq": 3,
                            "type": "assistant/message",
                            "data": {
                                "message": {
                                    "content": [{"type": "text", "text": "done"}]
                                }
                            },
                        }
                    },
                    {
                        "event": {
                            "seq": 4,
                            "type": "turn/end",
                            "data": {"reason": {"kind": "completed"}},
                        }
                    },
                ]
            )
            value = {"queued": True}
        elif method == "session.history":
            value = {"events": list(self.events)}
        elif method == "session.list":
            value = {"sessions": [{"sessionId": "session-1"}]}
        elif method == "session.cancel":
            value = {"cancelled": True}
        else:
            value = None
        response = {
            "type": "server-response",
            "rpcId": request["rpcId"],
            "result": {"ok": True, "value": value},
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DshClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeDshHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.client = dsh_client.DshClient(f"http://{host}:{port}", 2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self) -> None:
        FakeDshHandler.events = [
            {
                "event": {
                    "seq": 1,
                    "type": "turn/end",
                    "data": {"reason": {"kind": "completed"}},
                }
            }
        ]

    def test_health_create_list_and_cancel(self) -> None:
        self.client.health()
        self.assertEqual(self.client.create("/tmp"), "session-1")
        self.assertEqual(self.client.list_sessions()["sessions"][0]["sessionId"], "session-1")
        self.assertTrue(self.client.cancel("session-1")["cancelled"])

    def test_prompt_then_wait_ignores_previous_turn(self) -> None:
        cursor = dsh_client.history_cursor(self.client.history("session-1"))
        self.client.prompt("session-1", "work", "queue")
        answer = dsh_client.wait_for_turn(
            self.client, "session-1", cursor, timeout=1, poll_interval=0.01
        )
        self.assertEqual(answer, "done")

    def test_history_cursor_falls_back_to_length(self) -> None:
        events = [{"event": {"type": "turn/start"}}]
        cursor = dsh_client.history_cursor(events)
        self.assertIsNone(cursor.sequence)
        self.assertEqual(
            dsh_client.events_after_cursor(
                events + [{"event": {"type": "turn/end"}}], cursor
            ),
            [{"event": {"type": "turn/end"}}],
        )

    def test_error_turn_raises(self) -> None:
        FakeDshHandler.events = [
            {
                "event": {
                    "seq": 2,
                    "type": "turn/end",
                    "data": {
                        "reason": {
                            "kind": "error",
                            "error": {"code": "bad", "message": "failed"},
                        }
                    },
                }
            }
        ]
        with self.assertRaisesRegex(dsh_client.DshClientError, "bad: failed"):
            dsh_client.wait_for_turn(
                self.client,
                "session-1",
                dsh_client.HistoryCursor(length=0, sequence=1),
                timeout=1,
                poll_interval=0.01,
            )


if __name__ == "__main__":
    unittest.main()
