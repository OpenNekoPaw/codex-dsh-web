#!/usr/bin/env python3
"""Dependency-free CLI client for Codex-to-DSH Web collaboration loops."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn


DEFAULT_URL = "http://127.0.0.1:8765"


class DshClientError(RuntimeError):
    """A transport, protocol, or DSH turn failure."""


@dataclass(frozen=True)
class HistoryCursor:
    length: int
    sequence: int | None


def env_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as error:
        raise DshClientError(f"{name} must be a number, got {raw_value!r}") from error
    if value <= 0:
        raise DshClientError(f"{name} must be greater than zero")
    return value


def fail(message: str, exit_code: int = 1) -> NoReturn:
    print(f"DSH_ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


class DshClient:
    def __init__(self, base_url: str, http_timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_timeout = http_timeout

    def post(self, method: str, payload: dict[str, Any]) -> Any:
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
            raise DshClientError(
                f"cannot reach {self.base_url} while calling {method}: {error.reason}"
            ) from error
        except TimeoutError as error:
            raise DshClientError(f"HTTP timeout calling {method}") from error

        try:
            response_payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise DshClientError(f"invalid JSON response from {method}") from error
        if not isinstance(response_payload, dict):
            raise DshClientError(f"invalid response envelope from {method}")
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
        return result["value"]

    def health(self) -> None:
        request = urllib.request.Request(self.base_url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
                if not 200 <= response.status < 400:
                    raise DshClientError(f"health check returned HTTP {response.status}")
        except urllib.error.HTTPError as error:
            raise DshClientError(f"health check returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise DshClientError(f"cannot reach {self.base_url}: {error.reason}") from error
        except TimeoutError as error:
            raise DshClientError("health check timed out") from error

    def create(self, cwd: str) -> str:
        value = self.post("session.create", {"cwd": cwd})
        if not isinstance(value, dict) or not isinstance(value.get("sessionId"), str):
            raise DshClientError("session.create did not return a sessionId")
        return value["sessionId"]

    def prompt(self, session_id: str, text: str, mode: str) -> Any:
        return self.post(
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
        for item in events
        if (sequence := event_sequence(unwrap_event(item))) is not None
        and sequence > cursor.sequence
    ]


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
) -> str:
    deadline = time.monotonic() + timeout
    latest_message = ""
    while time.monotonic() < deadline:
        events = events_after_cursor(client.history(session_id), cursor)
        for item in events:
            event = unwrap_event(item)
            if event.get("type") == "assistant/message":
                message = extract_message(event)
                if message:
                    latest_message = message
            elif event.get("type") == "turn/end":
                reason = turn_reason(event)
                if reason is None:
                    raise DshClientError("turn/end did not contain a reason")
                kind = reason.get("kind")
                if kind == "completed":
                    return latest_message
                error = reason.get("error") or reason.get("failure") or reason
                raise DshClientError(f"turn ended with {kind or 'unknown'}: {format_error(error)}")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
    raise DshClientError(f"timeout after {timeout:g}s waiting for turn/end")


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
    wait_parser.add_argument("--after-count", type=int, default=0)

    subparsers.add_parser("list", help="list sessions")

    cancel_parser = subparsers.add_parser("cancel", help="cancel a session")
    cancel_parser.add_argument("session_id")

    subparsers.add_parser("open", help="open the DSH Web browser UI")
    return parser


def validate_positive(parser: argparse.ArgumentParser, name: str, value: float) -> None:
    if value <= 0:
        parser.error(f"{name} must be greater than zero")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_positive(parser, "--http-timeout", args.http_timeout)
    validate_positive(parser, "--timeout", args.timeout)
    validate_positive(parser, "--poll-interval", args.poll_interval)
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
        cursor = history_cursor(client.history(args.session_id))
        client.prompt(args.session_id, args.text, args.mode)
        print(
            wait_for_turn(
                client,
                args.session_id,
                cursor,
                args.timeout,
                args.poll_interval,
            )
        )
    elif args.command == "history":
        events = client.history(args.session_id)
        output = compact_messages(events) if args.messages else events
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "wait":
        cursor = HistoryCursor(length=args.after_count, sequence=args.after_seq)
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
