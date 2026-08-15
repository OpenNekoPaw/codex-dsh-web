from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from unittest import mock


MODULE_PATH = (
    Path(__file__).parents[1] / "skills" / "dsh-web" / "scripts" / "dsh_client.py"
)
SPEC = importlib.util.spec_from_file_location("dsh_client", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dsh_client = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dsh_client
SPEC.loader.exec_module(dsh_client)


def event(
    sequence: Optional[int], event_type: str, data: dict[str, Any]
) -> dict[str, Any]:
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
    raw_response: Optional[bytes] = None
    response_mutator: Optional[Callable[[dict[str, Any]], None]] = None
    prompt_events: Optional[
        Callable[[dict[str, Any]], list[dict[str, Any]]]
    ] = None
    title = "Codex test session [session-1]"

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
            value = {
                "events": list(self.events),
                "projections": {"values": {"title": self.title}},
            }
        elif method == "session.list":
            value = {
                "items": [
                    {"sessionId": "session-1", "running": self.running},
                ]
            }
        elif method == "session.cancel":
            value = {"cancelled": True}
        elif method == "session.rename":
            type(self).title = request["payload"]["title"].strip()
            value = {"title": type(self).title, "seq": 2}
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
        FakeDshHandler.title = "Codex test session [session-1]"

    def test_health_create_list_and_cancel(self) -> None:
        self.client.health()
        self.assertEqual(self.client.create("/tmp"), "session-1")
        records = dsh_client.session_records(self.client.list_sessions())
        self.assertEqual(records[0]["sessionId"], "session-1")
        self.assertTrue(self.client.cancel("session-1")["cancelled"])

    def test_rename_and_ui_target_use_the_title_projection(self) -> None:
        renamed = self.client.rename("session-1", "Codex: inspect repo [session-1]")
        self.assertEqual(renamed["title"], "Codex: inspect repo [session-1]")
        self.assertEqual(
            dsh_client.ui_target(self.client, "session-1"),
            {
                "url": self.client.base_url,
                "sessionId": "session-1",
                "title": "Codex: inspect repo [session-1]",
            },
        )

    def test_ui_target_requires_a_visible_title(self) -> None:
        FakeDshHandler.title = None
        with self.assertRaisesRegex(dsh_client.DshClientError, "no visible title"):
            dsh_client.ui_target(self.client, "session-1")

    def test_dispatch_receipt_can_wait_for_the_correlated_turn(self) -> None:
        receipt = dsh_client.dispatch_prompt(
            self.client, "session-1", "work", "queue"
        )
        self.assertEqual(receipt.cursor, dsh_client.HistoryCursor(1, 1))
        self.assertTrue(receipt.rpc_id)
        self.assertEqual(
            dsh_client.wait_for_turn(
                self.client,
                "session-1",
                receipt.cursor,
                timeout=1,
                poll_interval=0.01,
                prompt_rpc_id=receipt.rpc_id,
            ),
            "done",
        )

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
            dsh_client,
            "open_request",
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

    def test_connection_refused_is_classified_as_unavailable(self) -> None:
        client = dsh_client.DshClient("http://127.0.0.1:1", 1)
        error = dsh_client.urllib.error.URLError(ConnectionRefusedError("refused"))
        with mock.patch.object(dsh_client, "open_request", side_effect=error):
            with self.assertRaises(dsh_client.DshUnavailableError):
                client.health()

    def test_loopback_requests_bypass_environment_proxies(self) -> None:
        request = dsh_client.urllib.request.Request("http://127.0.0.1:8765")
        response = mock.MagicMock()
        with mock.patch.object(
            dsh_client.DIRECT_OPENER, "open", return_value=response
        ) as direct_open, mock.patch.object(
            dsh_client.urllib.request, "urlopen"
        ) as proxied_open:
            self.assertIs(dsh_client.open_request(request, 2), response)
        direct_open.assert_called_once_with(request, timeout=2)
        proxied_open.assert_not_called()

    def test_local_web_target_accepts_loopback_only(self) -> None:
        self.assertEqual(
            dsh_client.local_web_target("http://localhost:8765"),
            ("localhost", 8765),
        )
        self.assertEqual(
            dsh_client.local_web_target("http://[::1]:9000/"),
            ("::1", 9000),
        )
        for url in (
            "https://127.0.0.1:8765",
            "http://example.com:8765",
            "http://127.0.0.1:8765/path",
        ):
            with self.subTest(url=url):
                with self.assertRaises(dsh_client.DshClientError):
                    dsh_client.local_web_target(url)

    def test_missing_dsh_error_includes_install_command(self) -> None:
        with mock.patch.object(dsh_client.shutil, "which", return_value=None):
            with self.assertRaisesRegex(
                dsh_client.DshClientError,
                "npm install --global @deepseek-ai/dsh",
            ):
                dsh_client.require_dsh_executable()

    def test_unsupported_python_version_has_a_clear_error(self) -> None:
        with mock.patch.object(dsh_client.sys, "version_info", (3, 8, 20)):
            with self.assertRaisesRegex(
                dsh_client.DshClientError, "Python 3.9 or later is required"
            ):
                dsh_client.require_supported_python()

    def test_start_reuses_a_healthy_server(self) -> None:
        client = mock.Mock(base_url="https://dsh.example.test")
        with mock.patch.object(dsh_client, "launch_dsh") as launch:
            result = dsh_client.start_dsh_server(client, 1, 0.01)
        self.assertFalse(result.started)
        self.assertIsNone(result.pid)
        self.assertIsNone(result.log_path)
        launch.assert_not_called()

    def test_start_launches_and_waits_for_health(self) -> None:
        client = mock.Mock(base_url="http://127.0.0.1:8765")
        client.health.side_effect = [dsh_client.DshUnavailableError("refused"), None]
        process = mock.Mock(pid=1234)
        process.poll.return_value = None
        with mock.patch.object(
            dsh_client, "require_dsh_executable", return_value="/bin/dsh"
        ), mock.patch.object(
            dsh_client, "dsh_version", return_value="1.0"
        ), mock.patch.object(
            dsh_client, "launch_dsh", return_value=process
        ) as launch:
            result = dsh_client.start_dsh_server(client, 1, 0.01)
        self.assertTrue(result.started)
        self.assertEqual(result.pid, 1234)
        launch.assert_called_once()

    def test_launch_dsh_does_not_use_a_shell(self) -> None:
        process = mock.sentinel.process
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dsh_client.subprocess, "Popen", return_value=process
        ) as popen:
            result = dsh_client.launch_dsh(
                "/usr/local/bin/dsh",
                "127.0.0.1",
                8765,
                Path(directory) / "dsh.log",
            )
        self.assertIs(result, process)
        command = popen.call_args.args[0]
        options = popen.call_args.kwargs
        self.assertEqual(command[0], "/usr/local/bin/dsh")
        self.assertNotIn("shell", options)

    def test_start_does_not_launch_for_an_unavailable_remote_url(self) -> None:
        client = mock.Mock(base_url="http://dsh.example.test:8765")
        client.health.side_effect = dsh_client.DshUnavailableError("refused")
        with mock.patch.object(dsh_client, "launch_dsh") as launch:
            with self.assertRaisesRegex(
                dsh_client.DshClientError, "loopback DSH_URL"
            ):
                dsh_client.start_dsh_server(client, 1, 0.01)
        launch.assert_not_called()

    def test_doctor_accepts_a_reachable_server_without_local_dsh(self) -> None:
        client = mock.Mock(base_url="http://127.0.0.1:8765")

        def command_path(name: str) -> Optional[str]:
            return "/usr/bin/npm" if name == "npm" else None

        with mock.patch.object(dsh_client.shutil, "which", side_effect=command_path):
            report = dsh_client.doctor_report(client)
        self.assertTrue(report["ready"])
        self.assertTrue(report["server"]["reachable"])
        self.assertFalse(report["dsh"]["ok"])

    def test_open_uses_the_platform_default_browser(self) -> None:
        with mock.patch.object(
            sys, "argv", ["dsh_client.py", "open"]
        ), mock.patch.object(
            dsh_client.webbrowser, "open", return_value=True
        ) as open_browser, mock.patch("builtins.print"):
            self.assertEqual(dsh_client.main(), 0)
        open_browser.assert_called_once_with(
            dsh_client.DEFAULT_URL, new=2, autoraise=True
        )

    def test_detached_process_options_are_platform_specific(self) -> None:
        with mock.patch.object(dsh_client.os, "name", "nt"):
            windows_options = dsh_client.detached_process_options(mock.sentinel.log)
        self.assertIn("creationflags", windows_options)
        self.assertNotIn("start_new_session", windows_options)

        with mock.patch.object(dsh_client.os, "name", "posix"):
            posix_options = dsh_client.detached_process_options(mock.sentinel.log)
        self.assertTrue(posix_options["start_new_session"])
        self.assertNotIn("creationflags", posix_options)

    def test_windows_batch_executable_uses_command_processor(self) -> None:
        with mock.patch.object(dsh_client.os, "name", "nt"), mock.patch.dict(
            os.environ, {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}
        ):
            command = dsh_client.executable_command(
                "C:\\Tools\\dsh.cmd", "--version"
            )
        self.assertEqual(
            command,
            [
                "C:\\Windows\\System32\\cmd.exe",
                "/d",
                "/s",
                "/c",
                "C:\\Tools\\dsh.cmd",
                "--version",
            ],
        )

    @unittest.skipIf(os.name == "nt", "same-process lock semantics differ on Windows")
    def test_session_lock_rejects_a_second_local_run(self) -> None:
        with dsh_client.session_lock("http://lock-test", "session-1"):
            with self.assertRaisesRegex(dsh_client.DshClientError, "another local"):
                with dsh_client.session_lock("http://lock-test", "session-1"):
                    pass


if __name__ == "__main__":
    unittest.main()
