#!/usr/bin/env python3
"""Dependency-free CLI client for Codex-to-DSH Web collaboration loops."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, NoReturn


DEFAULT_URL = "http://127.0.0.1:8765"


class DshClientError(RuntimeError):
    """A transport, protocol, or DSH turn failure."""


@dataclass(frozen=True)
class HistoryCursor:
    length: int
    sequence: int | None


@dataclass(frozen=True)
class RpcResponse:
    rpc_id: str
    value: Any


def env_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as error:
        raise DshClientError(f"{name} must be a number, got {raw_value!r}") from error
    if not math.isfinite(value) or value <= 0:
        raise DshClientError(f"{name} must be a finite number greater than zero")
    return value


def fail(message: str, exit_code: int = 1) -> NoReturn:
    print(f"DSH_ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


class DshClient:
    def __init__(self, base_url: str, http_timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_timeout = http_timeout

    def post_with_rpc_id(self, method: str, payload: dict[str, Any]) -> RpcResponse:
        rpc_id = str(uuid.uuid4())
        envelope = {
            "type": "client-request",
            "rpcId": rpc_id,
            "method": method,
            "payload": payload,
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/{method}",
            data=json.dumps(envelope).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise DshClientError(f"HTTP {error.code} calling {method}{suffix}") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise DshClientError(f"HTTP timeout calling {method}") from error
            raise DshClientError(
                f"cannot reach {self.base_url} while calling {method}: {error.reason}"
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise DshClientError(f"HTTP timeout calling {method}") from error

        try:
            response_payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise DshClientError(f"invalid JSON response from {method}") from error
        if not isinstance(response_payload, dict):
            raise DshClientError(f"invalid response envelope from {method}")
        if response_payload.get("type") != "server-response":
            raise DshClientError(f"invalid response type from {method}")
        if response_payload.get("rpcId") != rpc_id:
            raise DshClientError(f"rpcId mismatch in response from {method}")
        result = response_payload.get("result")
        if not isinstance(result, dict):
            raise DshClientError(f"missing result object in response from {method}")
        if result.get("ok") is False:
            error = result.get("error") or result.get("failure") or result
            raise DshClientError(f"RPC {method} failed: {format_error(error)}")
        if "value" not in result:
            raise DshClientError(f"missing result.value in response from {method}")
        return RpcResponse(rpc_id=rpc_id, value=result["value"])

    def post(self, method: str, payload: dict[str, Any]) -> Any:
        return self.post_with_rpc_id(method, payload).value

    def health(self) -> None:
        request = urllib.request.Request(self.base_url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
                if not 200 <= response.status < 400:
                    raise DshClientError(f"health check returned HTTP {response.status}")
        except urllib.error.HTTPError as error:
            raise DshClientError(f"health check returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise DshClientError("health check timed out") from error
            raise DshClientError(f"cannot reach {self.base_url}: {error.reason}") from error
        except (TimeoutError, socket.timeout) as error:
            raise DshClientError("health check timed out") from error

    def create(self, cwd: str) -> str:
        value = self.post("session.create", {"cwd": cwd})
        if not isinstance(value, dict) or not isinstance(value.get("sessionId"), str):
            raise DshClientError("session.create did not return a sessionId")
        return value["sessionId"]

    def prompt(self, session_id: str, text: str, mode: str) -> Any:
        return self.prompt_with_rpc_id(session_id, text, mode).value

    def prompt_with_rpc_id(self, session_id: str, text: str, mode: str) -> RpcResponse:
        return self.post_with_rpc_id(
            "session.prompt",
            {
                "sessionId": session_id,
                "mode": mode,
                "content": [{"type": "text", "text": text}],
            },
        )

    def history(self, session_id: str) -> list[dict[str, Any]]:
        value = self.post("session.history", {"sessionId": session_id})
        if not isinstance(value, dict) or not isinstance(value.get("events"), list):
            raise DshClientError("session.history did not return an events array")
        return [item for item in value["events"] if isinstance(item, dict)]

    def list_sessions(self) -> Any:
        return self.post("session.list", {})

    def cancel(self, session_id: str) -> Any:
        return self.post("session.cancel", {"sessionId": session_id})


def unwrap_event(item: dict[str, Any]) -> dict[str, Any]:
    event = item.get("event", item)
    return event if isinstance(event, dict) else {}


def event_sequence(event: dict[str, Any]) -> int | None:
    sequence = event.get("seq")
    return sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None


def history_cursor(events: list[dict[str, Any]]) -> HistoryCursor:
    sequences = [
        sequence
        for item in events
        if (sequence := event_sequence(unwrap_event(item))) is not None
    ]
    return HistoryCursor(length=len(events), sequence=max(sequences) if sequences else None)


def events_after_cursor(
    events: list[dict[str, Any]], cursor: HistoryCursor
) -> list[dict[str, Any]]:
    if cursor.sequence is None:
        return events[cursor.length :]
    return [
        item
        for index, item in enumerate(events)
        if index >= cursor.length
        or (
            (sequence := event_sequence(unwrap_event(item))) is not None
            and sequence > cursor.sequence
        )
    ]


def event_turn(event: dict[str, Any]) -> int | str | None:
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    turn = data.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, (int, str)):
        return None
    return turn


def event_prompt_rpc_id(event: dict[str, Any]) -> str | None:
    if event.get("type") != "user/message":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    source = data.get("source")
    if not isinstance(source, dict):
        return None
    rpc_id = source.get("rpcId")
    return rpc_id if isinstance(rpc_id, str) else None


def extract_message(event: dict[str, Any]) -> str:
    data = event.get("data")
    if not isinstance(data, dict):
        return ""
    message = data.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def turn_reason(event: dict[str, Any]) -> dict[str, Any] | None:
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    reason = data.get("reason")
    return reason if isinstance(reason, dict) else None


def format_error(error: Any) -> str:
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if code and message:
            return f"{code}: {message}"
        if message:
            return str(message)
        return json.dumps(error, ensure_ascii=False, sort_keys=True)
    return repr(error)


def wait_for_turn(
    client: DshClient,
    session_id: str,
    cursor: HistoryCursor,
    timeout: float,
    poll_interval: float,
    prompt_rpc_id: str | None = None,
) -> str:
    deadline = time.monotonic() + timeout
    latest_message = ""
    while time.monotonic() < deadline:
        events = events_after_cursor(client.history(session_id), cursor)
        active_turn: int | str | None = None
        target_turn: int | str | None = None
        messages_by_turn: dict[int | str, str] = {}
        reasons_by_turn: dict[int | str, dict[str, Any]] = {}
        for item in events:
            event = unwrap_event(item)
            event_type = event.get("type")
            turn = event_turn(event)
            if event_type == "turn/start":
                active_turn = turn
            elif prompt_rpc_id is not None and event_prompt_rpc_id(event) == prompt_rpc_id:
                target_turn = turn if turn is not None else active_turn
            elif event_type == "assistant/message":
                message = extract_message(event)
                message_turn = turn if turn is not None else active_turn
                if prompt_rpc_id is not None and message_turn is not None and message:
                    messages_by_turn[message_turn] = message
                elif prompt_rpc_id is None and message:
                    latest_message = message
            elif event_type == "turn/end":
                reason = turn_reason(event)
                if reason is None:
                    raise DshClientError("turn/end did not contain a reason")
                reason_turn = turn if turn is not None else active_turn
                if prompt_rpc_id is not None and reason_turn is not None:
                    reasons_by_turn[reason_turn] = reason
                elif prompt_rpc_id is None:
                    return finish_turn(latest_message, reason)

        if target_turn is not None and target_turn in reasons_by_turn:
            return finish_turn(
                messages_by_turn.get(target_turn, ""), reasons_by_turn[target_turn]
            )
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
    suffix = " for the prompted turn" if prompt_rpc_id is not None else ""
    raise DshClientError(f"timeout after {timeout:g}s waiting for turn/end{suffix}")


def finish_turn(message: str, reason: dict[str, Any]) -> str:
    kind = reason.get("kind")
    if kind == "completed":
        return message
    error = reason.get("error") or reason.get("failure") or reason
    raise DshClientError(f"turn ended with {kind or 'unknown'}: {format_error(error)}")


def session_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict):
        records = value.get("items")
        if not isinstance(records, list):
            records = value.get("sessions")
    else:
        records = None
    if not isinstance(records, list):
        raise DshClientError("session.list did not return a session array")
    return [record for record in records if isinstance(record, dict)]


def ensure_session_idle(client: DshClient, session_id: str) -> None:
    record = next(
        (
            item
            for item in session_records(client.list_sessions())
            if item.get("sessionId") == session_id
        ),
        None,
    )
    if record is None:
        raise DshClientError(f"session not found: {session_id}")
    if record.get("running") is True:
        raise DshClientError(
            "session is already running; wait for it to finish or use a separate session"
        )


@contextmanager
def session_lock(base_url: str, session_id: str) -> Iterator[None]:
    lock_root = Path(tempfile.gettempdir()) / "codex-dsh-web-locks"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(f"{base_url}\0{session_id}".encode("utf-8")).hexdigest()
    lock_path = lock_root / f"{key}.lock"
    lock_file = lock_path.open("a+b")
    acquired = False
    try:
        try:
            lock_session_file(lock_file)
            acquired = True
        except OSError as error:
            raise DshClientError(
                "another local dsh_client run is already using this session"
            ) from error
        yield
    finally:
        try:
            if acquired:
                unlock_session_file(lock_file)
        finally:
            lock_file.close()


def lock_session_file(lock_file: Any) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        if not lock_file.read(1):
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_session_file(lock_file: Any) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_prompt(
    client: DshClient,
    session_id: str,
    text: str,
    mode: str,
    timeout: float,
    poll_interval: float,
) -> str:
    with session_lock(client.base_url, session_id):
        ensure_session_idle(client, session_id)
        cursor = history_cursor(client.history(session_id))
        response = client.prompt_with_rpc_id(session_id, text, mode)
        return wait_for_turn(
            client,
            session_id,
            cursor,
            timeout,
            poll_interval,
            prompt_rpc_id=response.rpc_id,
        )


def compact_messages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in events:
        event = unwrap_event(item)
        event_type = event.get("type")
        if event_type == "assistant/message":
            messages.append(
                {
                    "seq": event_sequence(event),
                    "type": event_type,
                    "text": extract_message(event),
                }
            )
        elif event_type in {"turn/start", "turn/end"}:
            entry: dict[str, Any] = {
                "seq": event_sequence(event),
                "type": event_type,
            }
            if event_type == "turn/end":
                entry["reason"] = turn_reason(event)
            messages.append(entry)
    return messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call the DSH Web HTTP API and wait for session turns."
    )
    parser.add_argument("--url", default=os.environ.get("DSH_URL", DEFAULT_URL))
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=env_float("DSH_HTTP_TIMEOUT", 30.0),
        help="timeout for each HTTP request in seconds",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=env_float("DSH_TIMEOUT", 600.0),
        help="timeout while waiting for a turn in seconds",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=env_float("DSH_POLL_INTERVAL", 2.0),
        help="history polling interval in seconds",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="check whether DSH Web is reachable")

    create_parser = subparsers.add_parser("create", help="create a session")
    create_parser.add_argument("--cwd", default=os.getcwd())

    prompt_parser = subparsers.add_parser("prompt", help="queue a prompt")
    prompt_parser.add_argument("session_id")
    prompt_parser.add_argument("text")
    prompt_parser.add_argument("--mode", default="queue")

    run_parser = subparsers.add_parser("run", help="prompt and wait for the new turn")
    run_parser.add_argument("session_id")
    run_parser.add_argument("text")
    run_parser.add_argument("--mode", default="queue")

    history_parser = subparsers.add_parser("history", help="print session history")
    history_parser.add_argument("session_id")
    history_parser.add_argument("--messages", action="store_true")

    wait_parser = subparsers.add_parser("wait", help="wait for a later turn/end")
    wait_parser.add_argument("session_id")
    wait_parser.add_argument("--after-seq", type=int)
    wait_parser.add_argument("--after-count", type=int)

    subparsers.add_parser("list", help="list sessions")

    cancel_parser = subparsers.add_parser("cancel", help="cancel a session")
    cancel_parser.add_argument("session_id")

    subparsers.add_parser("open", help="open DSH Web in the macOS default browser")
    return parser


def validate_positive(parser: argparse.ArgumentParser, name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        parser.error(f"{name} must be a finite number greater than zero")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_positive(parser, "--http-timeout", args.http_timeout)
    validate_positive(parser, "--timeout", args.timeout)
    validate_positive(parser, "--poll-interval", args.poll_interval)
    if args.command == "wait":
        if args.after_seq is not None and args.after_seq < 0:
            parser.error("--after-seq must be zero or greater")
        if args.after_count is not None and args.after_count < 0:
            parser.error("--after-count must be zero or greater")
    client = DshClient(args.url, args.http_timeout)

    if args.command == "health":
        client.health()
        print(f"DSH Web is reachable at {client.base_url}")
    elif args.command == "create":
        cwd = str(Path(args.cwd).expanduser().resolve())
        if not Path(cwd).is_dir():
            raise DshClientError(f"session cwd is not a directory: {cwd}")
        print(client.create(cwd))
    elif args.command == "prompt":
        print(json.dumps(client.prompt(args.session_id, args.text, args.mode), ensure_ascii=False))
    elif args.command == "run":
        print(
            run_prompt(
                client,
                args.session_id,
                args.text,
                args.mode,
                args.timeout,
                args.poll_interval,
            )
        )
    elif args.command == "history":
        events = client.history(args.session_id)
        output = compact_messages(events) if args.messages else events
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "wait":
        current_events = client.history(args.session_id)
        if args.after_count is None and args.after_seq is None:
            cursor = history_cursor(current_events)
        else:
            cursor = HistoryCursor(
                length=(
                    args.after_count
                    if args.after_count is not None
                    else len(current_events)
                ),
                sequence=args.after_seq,
            )
        print(
            wait_for_turn(
                client,
                args.session_id,
                cursor,
                args.timeout,
                args.poll_interval,
            )
        )
    elif args.command == "list":
        print(json.dumps(client.list_sessions(), ensure_ascii=False, indent=2))
    elif args.command == "cancel":
        print(json.dumps(client.cancel(args.session_id), ensure_ascii=False))
    elif args.command == "open":
        if sys.platform != "darwin":
            raise DshClientError("the open command currently supports macOS only")
        subprocess.run(["open", client.base_url], check=True)
        print(client.base_url)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DshClientError as error:
        fail(str(error))
    except KeyboardInterrupt:
        fail("interrupted", 130)
