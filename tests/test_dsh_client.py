from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from unittest import mock


MODULE_PATH = (
    Path(__file__).parents[1] / "skills" / "dsh-web" / "scripts" / "dsh_client.py"
)
SPEC = importlib.util.spec_from_file_location("dsh_client", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dsh_client = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dsh_client
SPEC.loader.exec_module(dsh_client)


def event(sequence: int | None, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {"type": event_type, "data": data}
    if sequence is not None:
        value["seq"] = sequence
    return {"event": value}


def completed_turn(
    start_sequence: int,
    turn: int,
    rpc_id: str,
    message: str,
) -> list[dict[str, Any]]:
    return [
        event(start_sequence, "turn/start", {"turn": turn}),
        event(
            start_sequence + 1,
            "user/message",
            {"source": {"kind": "user", "rpcId": rpc_id}},
        ),
        event(
            start_sequence + 2,
            "assistant/message",
            {
                "turn": turn,
                "message": {"content": [{"type": "text", "text": message}]},
            },
        ),
        event(
            start_sequence + 3,
            "turn/end",
            {"turn": turn, "reason": {"kind": "completed"}},
        ),
    ]


class FakeDshHandler(BaseHTTPRequestHandler):
    events: list[dict[str, Any]] = []
    running = False
    http_status = 200
    raw_response: bytes | None = None
    response_mutator: Callable[[dict[str, Any]], None] | None = None
    prompt_events: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        self.send_response(self.http_status)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self) -> None:
        length = int(self.headers["content-length"])
        request = json.loads(self.rfile.read(length))
        if self.http_status != 200:
            self.send_response(self.http_status)
            self.end_headers()
            self.wfile.write(b"request rejected")
            return

        method = request["method"]
        if method == "session.create":
            value: Any = {"sessionId": "session-1"}
        elif method == "session.prompt":
            factory = type(self).prompt_events
            new_events = (
                factory(request)
                if factory is not None
                else completed_turn(2, 1, request["rpcId"], "done")
            )
            self.events.extend(new_events)
            value = {"queued": True}
        elif method == "session.history":
            value = {"events": list(self.events)}
        elif method == "session.list":
            value = {
                "items": [
                    {"sessionId": "session-1", "running": self.running},
                ]
            }
        elif method == "session.cancel":
            value = {"cancelled": True}
        else:
            value = None

        response = {
            "type": "server-response",
            "rpcId": request["rpcId"],
            "result": {"ok": True, "value": value},
        }
        response_mutator = type(self).response_mutator
        if response_mutator is not None:
            response_mutator(response)
        body = type(self).raw_response
        if body is None:
            body = json.dumps(response).encode("utf-8")
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
            event(1, "turn/end", {"turn": 0, "reason": {"kind": "completed"}})
        ]
        FakeDshHandler.running = False
        FakeDshHandler.http_status = 200
        FakeDshHandler.raw_response = None
        FakeDshHandler.response_mutator = None
        FakeDshHandler.prompt_events = None

    def test_health_create_list_and_cancel(self) -> None:
        self.client.health()
        self.assertEqual(self.client.create("/tmp"), "session-1")
        records = dsh_client.session_records(self.client.list_sessions())
        self.assertEqual(records[0]["sessionId"], "session-1")
        self.assertTrue(self.client.cancel("session-1")["cancelled"])

    def test_run_prompt_correlates_the_prompt_rpc_id(self) -> None:
        def queued_turns(request: dict[str, Any]) -> list[dict[str, Any]]:
            return completed_turn(2, 1, "external-rpc", "previous queued turn") + completed_turn(
                6, 2, request["rpcId"], "current prompt"
            )

        FakeDshHandler.prompt_events = queued_turns
        answer = dsh_client.run_prompt(
            self.client,
            "session-1",
            "work",
            "queue",
            timeout=1,
            poll_interval=0.01,
        )
        self.assertEqual(answer, "current prompt")

    def test_run_prompt_rejects_a_running_session(self) -> None:
        FakeDshHandler.running = True
        with self.assertRaisesRegex(dsh_client.DshClientError, "already running"):
            dsh_client.run_prompt(
                self.client,
                "session-1",
                "work",
                "queue",
                timeout=1,
                poll_interval=0.01,
            )

    def test_wait_for_turn_reports_target_turn_error(self) -> None:
        rpc_id = "target-rpc"
        FakeDshHandler.events = [
            event(2, "turn/start", {"turn": 3}),
            event(3, "user/message", {"source": {"rpcId": rpc_id}}),
            event(
                4,
                "turn/end",
                {
                    "turn": 3,
                    "reason": {
                        "kind": "error",
                        "error": {"code": "bad", "message": "failed"},
                    },
                },
            ),
        ]
        with self.assertRaisesRegex(dsh_client.DshClientError, "bad: failed"):
            dsh_client.wait_for_turn(
                self.client,
                "session-1",
                dsh_client.HistoryCursor(length=0, sequence=1),
                timeout=1,
                poll_interval=0.01,
                prompt_rpc_id=rpc_id,
            )

    def test_history_cursor_falls_back_to_length(self) -> None:
        events = [event(None, "turn/start", {})]
        cursor = dsh_client.history_cursor(events)
        self.assertIsNone(cursor.sequence)
        new_event = event(None, "turn/end", {"reason": {"kind": "completed"}})
        self.assertEqual(dsh_client.events_after_cursor(events + [new_event], cursor), [new_event])

    def test_mixed_sequence_history_keeps_new_unsequenced_events(self) -> None:
        old_events = [event(10, "turn/start", {"turn": 1})]
        cursor = dsh_client.history_cursor(old_events)
        unsequenced = event(None, "assistant/message", {"turn": 1})
        sequenced = event(11, "turn/end", {"turn": 1})
        self.assertEqual(
            dsh_client.events_after_cursor(old_events + [unsequenced, sequenced], cursor),
            [unsequenced, sequenced],
        )

    def test_response_envelope_failures(self) -> None:
        cases = {
            "invalid response type": lambda response: response.update(type="client-request"),
            "rpcId mismatch": lambda response: response.update(rpcId="wrong"),
            "missing result object": lambda response: response.update(result=None),
            "missing result.value": lambda response: response.update(result={"ok": True}),
            "RPC session.list failed": lambda response: response.update(
                result={"ok": False, "error": {"code": "bad", "message": "failed"}}
            ),
        }
        for expected, mutator in cases.items():
            with self.subTest(expected=expected):
                FakeDshHandler.response_mutator = mutator
                with self.assertRaisesRegex(dsh_client.DshClientError, expected):
                    self.client.list_sessions()
                FakeDshHandler.response_mutator = None

    def test_invalid_json_and_http_error(self) -> None:
        FakeDshHandler.raw_response = b"not-json"
        with self.assertRaisesRegex(dsh_client.DshClientError, "invalid JSON"):
            self.client.list_sessions()

        FakeDshHandler.raw_response = None
        FakeDshHandler.http_status = 403
        with self.assertRaisesRegex(dsh_client.DshClientError, "HTTP 403"):
            self.client.list_sessions()

    def test_socket_timeout_is_wrapped(self) -> None:
        with mock.patch.object(
            dsh_client.urllib.request,
            "urlopen",
            side_effect=socket.timeout("timed out"),
        ):
            with self.assertRaisesRegex(dsh_client.DshClientError, "HTTP timeout"):
                self.client.list_sessions()
            with self.assertRaisesRegex(dsh_client.DshClientError, "health check timed out"):
                self.client.health()

    def test_non_finite_environment_values_are_rejected(self) -> None:
        for raw_value in ("nan", "inf", "-inf", "1e999"):
            with self.subTest(raw_value=raw_value):
                with mock.patch.dict(os.environ, {"DSH_TIMEOUT": raw_value}):
                    with self.assertRaisesRegex(dsh_client.DshClientError, "finite number"):
                        dsh_client.env_float("DSH_TIMEOUT", 1)

    def test_session_records_accepts_known_shapes(self) -> None:
        item = {"sessionId": "session-1"}
        self.assertEqual(dsh_client.session_records([item]), [item])
        self.assertEqual(dsh_client.session_records({"items": [item]}), [item])
        self.assertEqual(dsh_client.session_records({"sessions": [item]}), [item])
        with self.assertRaisesRegex(dsh_client.DshClientError, "session array"):
            dsh_client.session_records({})

    def test_bare_wait_snapshots_current_history(self) -> None:
        old_events = list(FakeDshHandler.events)
        fake_client = mock.Mock()
        fake_client.history.return_value = old_events
        with mock.patch.object(dsh_client, "DshClient", return_value=fake_client), mock.patch.object(
            dsh_client,
            "wait_for_turn",
            return_value="later",
        ) as wait_for_turn, mock.patch.object(
            sys,
            "argv",
            ["dsh_client.py", "wait", "session-1"],
        ), mock.patch("builtins.print"):
            self.assertEqual(dsh_client.main(), 0)
        cursor = wait_for_turn.call_args.args[2]
        self.assertEqual(cursor, dsh_client.history_cursor(old_events))

    @unittest.skipIf(os.name == "nt", "same-process lock semantics differ on Windows")
    def test_session_lock_rejects_a_second_local_run(self) -> None:
        with dsh_client.session_lock("http://lock-test", "session-1"):
            with self.assertRaisesRegex(dsh_client.DshClientError, "another local"):
                with dsh_client.session_lock("http://lock-test", "session-1"):
                    pass


if __name__ == "__main__":
    unittest.main()
