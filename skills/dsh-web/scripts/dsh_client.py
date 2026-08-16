#!/usr/bin/env python3
"""Dependency-free CLI client for Codex-to-DSH Web collaboration loops."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import errno
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, NoReturn, Optional, Tuple, Union


DEFAULT_URL = "http://localhost:8765"
MIN_PYTHON = (3, 9)
DSH_PACKAGE = "@deepseek-ai/dsh"
DSH_INSTALL_COMMAND = f"npm install --global {DSH_PACKAGE}"
DSH_PROJECT_URL = "https://github.com/deepseek-ai/deepseek-harness"
DEFAULT_STARTUP_TIMEOUT = 20.0
DEFAULT_UI_LIMIT = 10
DEFAULT_UI_ACTIVITY_TTL = 2 * 3600.0
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PERMISSION_PRESETS = ("read-only", "workspace-write", "danger-full-access")
INTENT_PERMISSIONS = {
    "read": "read-only",
    "write": "workspace-write",
    "full-access": "danger-full-access",
}
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DshClientError(RuntimeError):
    """A transport, protocol, or DSH turn failure."""


class DshUnavailableError(DshClientError):
    """DSH Web is not accepting connections at the configured URL."""


@dataclass(frozen=True)
class HistoryCursor:
    length: int
    sequence: Optional[int]


@dataclass(frozen=True)
class RpcResponse:
    rpc_id: str
    value: Any


@dataclass(frozen=True)
class ServerStartResult:
    started: bool
    log_path: Optional[Path]
    pid: Optional[int]
    runtime_path: Optional[Path]


@dataclass(frozen=True)
class WaitReceipt:
    session_id: str
    rpc_id: str
    cursor: HistoryCursor
    ui_owner_id: Optional[str] = None
    ui_activity_id: Optional[str] = None


@dataclass(frozen=True)
class UiActivityDecision:
    activity_id: Optional[str]
    limit: int
    active: int
    reused: bool


@dataclass(frozen=True)
class UiReleaseDecision:
    close_ui: bool
    active: int


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


def env_nonnegative_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise DshClientError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise DshClientError(f"{name} must be a non-negative integer")
    return value


def require_supported_python() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        minimum = ".".join(str(value) for value in MIN_PYTHON)
        current = ".".join(str(value) for value in sys.version_info[:3])
        raise DshClientError(
            f"Python {minimum} or later is required; current interpreter is {current}"
        )


def is_connection_refused(reason: Any) -> bool:
    return isinstance(reason, ConnectionRefusedError) or getattr(
        reason, "errno", None
    ) == errno.ECONNREFUSED


def open_request(request: urllib.request.Request, timeout: float) -> Any:
    hostname = urllib.parse.urlsplit(request.full_url).hostname
    if hostname in LOOPBACK_HOSTS:
        return DIRECT_OPENER.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def dsh_install_hint() -> str:
    return (
        "DeepSeek Harness is not installed or is not on PATH. "
        f"After installing Node.js and npm, install it with `{DSH_INSTALL_COMMAND}`. "
        f"See {DSH_PROJECT_URL}. Ask the user before running an installer."
    )


def require_dsh_executable() -> str:
    executable = shutil.which("dsh")
    if executable is None:
        raise DshClientError(dsh_install_hint())
    return executable


def executable_command(executable: str, *args: str) -> list[str]:
    extension = os.path.splitext(executable)[1].lower()
    if os.name == "nt" and extension in {".bat", ".cmd"}:
        command_processor = os.environ.get("COMSPEC", "cmd.exe")
        return [command_processor, "/d", "/s", "/c", executable, *args]
    return [executable, *args]


def dsh_version(executable: str) -> str:
    try:
        result = subprocess.run(
            executable_command(executable, "--version"),
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DshClientError(f"cannot run dsh at {executable}: {error}") from error
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        detail = f": {output}" if output else ""
        raise DshClientError(f"dsh --version failed with exit code {result.returncode}{detail}")
    return output or "unknown"


def local_web_target(base_url: str) -> Tuple[str, int]:
    try:
        parsed = urllib.parse.urlsplit(base_url)
        port = parsed.port
    except ValueError as error:
        raise DshClientError(f"invalid DSH_URL: {base_url}") from error
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise DshClientError(
            "automatic startup requires an http loopback DSH_URL using "
            "127.0.0.1, localhost, or ::1"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise DshClientError("automatic startup requires DSH_URL without a path, query, or fragment")
    return parsed.hostname, port or 80


def local_bind_host(base_url: str) -> str:
    hostname, _ = local_web_target(base_url)
    return "127.0.0.1" if hostname == "localhost" else hostname


def server_log_path(base_url: str) -> Path:
    _, port = local_web_target(base_url)
    return Path(tempfile.gettempdir()) / f"dsh-web-{port}.log"


def resolved_dsh_home() -> Path:
    configured = os.environ.get("DSH_HOME")
    if configured is None or not configured.strip():
        return (Path.home() / ".dsh").resolve()
    return Path(configured.strip()).expanduser().resolve()


def server_runtime_path(base_url: str) -> Path:
    _, port = local_web_target(base_url)
    return resolved_dsh_home() / "runtime" / "codex-dsh-web" / str(port)


def dsh_process_environment(runtime_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    configured = environment.get("DSH_HOME")
    if configured is not None and configured.strip():
        environment["DSH_HOME"] = str(resolved_dsh_home())
    if os.name != "nt":
        environment["PWD"] = str(runtime_path)
        environment.pop("OLDPWD", None)
    return environment


def prepare_server_runtime(runtime_path: Path) -> None:
    try:
        runtime_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise DshClientError(
            f"cannot create DSH Web runtime directory {runtime_path}: {error}"
        ) from error
    if not runtime_path.is_dir():
        raise DshClientError(f"DSH Web runtime path is not a directory: {runtime_path}")


def detached_process_options(log_file: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        options["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        options["start_new_session"] = True
    return options


def launch_dsh(
    executable: str,
    host: str,
    port: int,
    log_path: Path,
    runtime_path: Path,
) -> Any:
    command = executable_command(
        executable,
        "--profile",
        "web",
        "--host",
        host,
        "--port",
        str(port),
    )
    prepare_server_runtime(runtime_path)
    try:
        with log_path.open("ab") as log_file:
            return subprocess.Popen(
                command,
                cwd=str(runtime_path),
                env=dsh_process_environment(runtime_path),
                **detached_process_options(log_file),
            )
    except OSError as error:
        raise DshClientError(f"failed to start DSH Web: {error}") from error


def start_dsh_server(
    client: "DshClient", startup_timeout: float, poll_interval: float
) -> ServerStartResult:
    try:
        client.health()
        return ServerStartResult(
            started=False, log_path=None, pid=None, runtime_path=None
        )
    except DshUnavailableError:
        pass

    log_path = server_log_path(client.base_url)
    executable = require_dsh_executable()
    dsh_version(executable)
    _, port = local_web_target(client.base_url)
    host = local_bind_host(client.base_url)
    runtime_path = server_runtime_path(client.base_url)
    process = launch_dsh(executable, host, port, log_path, runtime_path)
    deadline = time.monotonic() + startup_timeout
    last_error = "connection refused"

    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise DshClientError(
                f"DSH Web exited with code {return_code}; inspect {log_path}"
            )
        try:
            client.health()
            return ServerStartResult(
                started=True,
                log_path=log_path,
                pid=getattr(process, "pid", None),
                runtime_path=runtime_path,
            )
        except DshUnavailableError as error:
            last_error = str(error)
            time.sleep(poll_interval)

    raise DshClientError(
        f"DSH Web did not become ready within {startup_timeout:g} seconds "
        f"({last_error}); inspect {log_path}"
    )


def doctor_report(client: "DshClient") -> dict[str, Any]:
    python_version = ".".join(str(value) for value in sys.version_info[:3])
    dsh_path = shutil.which("dsh")
    npm_path = shutil.which("npm")
    report: dict[str, Any] = {
        "ready": False,
        "python": {
            "ok": sys.version_info[:2] >= MIN_PYTHON,
            "version": python_version,
            "minimum": ".".join(str(value) for value in MIN_PYTHON),
        },
        "dsh": {
            "ok": False,
            "path": dsh_path,
            "version": None,
            "installCommand": DSH_INSTALL_COMMAND,
            "projectURL": DSH_PROJECT_URL,
        },
        "npm": {"available": npm_path is not None, "path": npm_path},
        "server": {"url": client.base_url, "reachable": False},
    }

    try:
        report["server"]["managedRuntimePath"] = str(
            server_runtime_path(client.base_url)
        )
    except DshClientError:
        pass

    if dsh_path is not None:
        try:
            report["dsh"]["version"] = dsh_version(dsh_path)
            report["dsh"]["ok"] = True
        except DshClientError as error:
            report["dsh"]["error"] = str(error)
    else:
        report["dsh"]["error"] = dsh_install_hint()

    try:
        client.health()
        report["server"]["reachable"] = True
    except DshClientError as error:
        report["server"]["error"] = str(error)

    report["ready"] = report["python"]["ok"] and (
        report["server"]["reachable"] or report["dsh"]["ok"]
    )
    return report


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
            with open_request(request, timeout=self.http_timeout) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise DshClientError(f"HTTP {error.code} calling {method}{suffix}") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise DshClientError(f"HTTP timeout calling {method}") from error
            if is_connection_refused(error.reason):
                raise DshUnavailableError(
                    f"cannot reach {self.base_url} while calling {method}: {error.reason}"
                ) from error
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
            with open_request(request, timeout=self.http_timeout) as response:
                if not 200 <= response.status < 400:
                    raise DshClientError(f"health check returned HTTP {response.status}")
        except urllib.error.HTTPError as error:
            raise DshClientError(f"health check returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise DshClientError("health check timed out") from error
            if is_connection_refused(error.reason):
                raise DshUnavailableError(
                    f"cannot reach {self.base_url}: {error.reason}"
                ) from error
            raise DshClientError(f"cannot reach {self.base_url}: {error.reason}") from error
        except (TimeoutError, socket.timeout) as error:
            raise DshClientError("health check timed out") from error

    def list_workspaces(self) -> dict[str, Any]:
        value = self.post("workspace.list", {})
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise DshClientError("workspace.list did not return an items array")
        return value

    def ensure_workspace(self, cwd: str) -> dict[str, Any]:
        path = str(Path(cwd).expanduser().resolve())
        value = self.post("workspace.create", {"path": path})
        workspace = value.get("workspace") if isinstance(value, dict) else None
        if (
            not isinstance(workspace, dict)
            or not isinstance(workspace.get("workspaceId"), str)
            or not isinstance(workspace.get("path"), str)
            or not isinstance(workspace.get("sessionIds"), list)
        ):
            raise DshClientError("workspace.create did not return a valid workspace")
        return workspace

    def create(self, cwd: str) -> str:
        workspace = self.ensure_workspace(cwd)
        workspace_id = workspace["workspaceId"]
        value = self.post("session.create", {"workspaceId": workspace_id})
        if not isinstance(value, dict) or not isinstance(value.get("sessionId"), str):
            raise DshClientError("session.create did not return a sessionId")
        session_id = value["sessionId"]

        workspaces = self.list_workspaces()
        attached = any(
            isinstance(item, dict)
            and item.get("workspaceId") == workspace_id
            and isinstance(item.get("sessionIds"), list)
            and session_id in item["sessionIds"]
            for item in workspaces["items"]
        )
        if not attached:
            raise DshClientError(
                f'session.create returned "{session_id}" but DSH did not attach it '
                f'to workspace "{workspace_id}"'
            )
        return session_id

    def prompt_with_rpc_id(self, session_id: str, text: str, mode: str) -> RpcResponse:
        return self.post_with_rpc_id(
            "session.prompt",
            {
                "sessionId": session_id,
                "mode": mode,
                "content": [{"type": "text", "text": text}],
            },
        )

    def execute_command(self, session_id: str, line: str) -> dict[str, Any]:
        value = self.post(
            "commands/execute",
            {"args": {"agentId": session_id, "line": line}},
        )
        if not isinstance(value, dict) or not isinstance(value.get("commandId"), str):
            raise DshClientError(
                f"DSH did not recognize command {line!r}; upgrade DSH Web to a version "
                "that exposes /api/commands/execute"
            )
        result = value.get("result")
        if not isinstance(result, dict):
            raise DshClientError("commands/execute returned an invalid result")
        kind = result.get("kind")
        if kind == "error":
            raise DshClientError(
                f"DSH command failed: {result.get('text') or 'unknown command error'}"
            )
        if kind != "success":
            raise DshClientError("commands/execute returned an unknown result kind")
        return value

    def history(self, session_id: str) -> list[dict[str, Any]]:
        value = self.history_page(session_id)
        return [item for item in value["events"] if isinstance(item, dict)]

    def history_page(self, session_id: str) -> dict[str, Any]:
        value = self.post("session.history", {"sessionId": session_id})
        if not isinstance(value, dict) or not isinstance(value.get("events"), list):
            raise DshClientError("session.history did not return an events array")
        return value

    def list_sessions(self) -> Any:
        return self.post("session.list", {})

    def cancel(self, session_id: str) -> Any:
        return self.post("session.cancel", {"sessionId": session_id})

    def rename(self, session_id: str, title: str) -> dict[str, Any]:
        value = self.post(
            "session.rename", {"sessionId": session_id, "title": title}
        )
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("title"), str)
            or not value["title"]
            or isinstance(value.get("seq"), bool)
            or not isinstance(value.get("seq"), int)
        ):
            raise DshClientError("session.rename returned an invalid title result")
        return value


def unwrap_event(item: dict[str, Any]) -> dict[str, Any]:
    event = item.get("event", item)
    return event if isinstance(event, dict) else {}


def event_sequence(event: dict[str, Any]) -> Optional[int]:
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


def event_turn(event: dict[str, Any]) -> Optional[Union[int, str]]:
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    turn = data.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, (int, str)):
        return None
    return turn


def event_prompt_rpc_id(event: dict[str, Any]) -> Optional[str]:
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


def turn_reason(event: dict[str, Any]) -> Optional[dict[str, Any]]:
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
    prompt_rpc_id: Optional[str] = None,
) -> str:
    deadline = time.monotonic() + timeout
    latest_message = ""
    while time.monotonic() < deadline:
        events = events_after_cursor(client.history(session_id), cursor)
        active_turn: Optional[Union[int, str]] = None
        target_turn: Optional[Union[int, str]] = None
        messages_by_turn: dict[Union[int, str], str] = {}
        reasons_by_turn: dict[Union[int, str], dict[str, Any]] = {}
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


def session_permission(value: dict[str, Any]) -> dict[str, Any]:
    projections = value.get("projections")
    if not isinstance(projections, dict):
        raise DshClientError(
            "session history has no permission projection; upgrade DSH Web before "
            "using automatic permission selection"
        )
    values = projections.get("values")
    permissions = values.get("permissions") if isinstance(values, dict) else None
    if not isinstance(permissions, dict):
        raise DshClientError(
            "session history has no permission projection; upgrade DSH Web before "
            "using automatic permission selection"
        )
    current = permissions.get("currentValue")
    options = permissions.get("options")
    available = []
    if isinstance(options, list):
        available = [
            option["value"]
            for option in options
            if isinstance(option, dict)
            and isinstance(option.get("value"), str)
            and option["value"]
        ]
    if not isinstance(current, str) or not current or not available:
        raise DshClientError("session permission projection is invalid")
    return {"currentValue": current, "available": available}


def set_session_permission(
    client: DshClient, session_id: str, preset: str
) -> dict[str, Any]:
    with session_lock(client.base_url, session_id):
        ensure_session_idle(client, session_id)
        before = session_permission(client.history_page(session_id))
        if preset not in before["available"]:
            available = ", ".join(before["available"])
            raise DshClientError(
                f"DSH permission preset {preset!r} is unavailable (available: {available})"
            )
        changed = before["currentValue"] != preset
        if changed:
            client.execute_command(session_id, f"/permission {preset}")
        after = session_permission(client.history_page(session_id))
        if after["currentValue"] != preset:
            raise DshClientError(
                f"DSH permission verification failed: requested {preset!r}, "
                f"effective {after['currentValue']!r}"
            )
        return {
            "sessionId": session_id,
            "currentValue": after["currentValue"],
            "available": after["available"],
            "changed": changed,
        }


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


def ui_registry_paths() -> Tuple[Path, Path]:
    registry_root = Path(tempfile.gettempdir()) / "codex-dsh-web-ui"
    registry_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return registry_root / "owners.json", registry_root / "owners.lock"


@contextmanager
def ui_registry_lock() -> Iterator[Path]:
    state_path, lock_path = ui_registry_paths()
    lock_file = lock_path.open("a+b")
    acquired = False
    deadline = time.monotonic() + 5
    try:
        while True:
            try:
                lock_session_file(lock_file)
                acquired = True
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise DshClientError("timed out updating the DSH UI registry") from error
                time.sleep(0.05)
        yield state_path
    finally:
        try:
            if acquired:
                unlock_session_file(lock_file)
        finally:
            lock_file.close()


def read_ui_owners(state_path: Path, now: float) -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    owners = value.get("owners")
    if not isinstance(owners, dict):
        return {}
    active_owners: dict[str, dict[str, Any]] = {}
    for owner_id, owner in owners.items():
        if not isinstance(owner_id, str) or not isinstance(owner, dict):
            continue
        raw_activities = owner.get("activities")
        if not isinstance(raw_activities, dict):
            continue
        owner_expiry = owner.get("expiresAt")
        activities: dict[str, dict[str, Any]] = {}
        for activity_id, activity in raw_activities.items():
            if not isinstance(activity_id, str) or not isinstance(activity, dict):
                continue
            expires_at = activity.get("expiresAt", owner_expiry)
            if isinstance(expires_at, (int, float)) and expires_at > now:
                activities[activity_id] = {**activity, "expiresAt": expires_at}
        if not activities:
            continue
        expires_at = max(activity["expiresAt"] for activity in activities.values())
        active_owners[owner_id] = {
            "activities": activities,
            "updatedAt": owner.get("updatedAt", now),
            "expiresAt": expires_at,
        }
    return active_owners


def write_ui_owners(
    state_path: Path, owners: dict[str, dict[str, Any]]
) -> None:
    temporary_path = state_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps({"version": 1, "owners": owners}, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_path.replace(state_path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def codex_thread_id() -> str:
    for name in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "DSH_UI_OWNER_ID"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise DshClientError(
        "UI mode requires CODEX_THREAD_ID or CODEX_SESSION_ID; "
        "set DSH_UI_OWNER_ID only for an explicit non-Codex caller"
    )


def thread_ui_url(base_url: str, owner_id: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "codexThreadId"]
    query.append(("codexThreadId", owner_id))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", urllib.parse.urlencode(query), "")
    )


def acquire_ui_activity(
    base_url: str,
    owner_id: str,
    session_id: str,
    limit: int,
    ttl: float,
    now: float,
) -> UiActivityDecision:
    with ui_registry_lock() as state_path:
        owners = read_ui_owners(state_path, now)
        reused = owner_id in owners
        if not reused and len(owners) >= limit:
            write_ui_owners(state_path, owners)
            return UiActivityDecision(None, limit, len(owners), False)
        activity_id = uuid.uuid4().hex
        owner = owners.get(owner_id, {"activities": {}})
        activities = owner["activities"]
        expires_at = now + ttl
        activities[activity_id] = {
            "baseUrl": base_url,
            "sessionId": session_id,
            "startedAt": now,
            "expiresAt": expires_at,
        }
        owners[owner_id] = {
            "activities": activities,
            "updatedAt": now,
            "expiresAt": max(
                activity["expiresAt"] for activity in activities.values()
            ),
        }
        write_ui_owners(state_path, owners)
        return UiActivityDecision(activity_id, limit, len(owners), reused)


def release_ui_activity(
    owner_id: Optional[str],
    activity_id: Optional[str],
) -> UiReleaseDecision:
    if owner_id is None or activity_id is None:
        return UiReleaseDecision(False, 0)
    now = time.time()
    with ui_registry_lock() as state_path:
        owners = read_ui_owners(state_path, now)
        owner = owners.get(owner_id)
        if owner is None:
            write_ui_owners(state_path, owners)
            return UiReleaseDecision(True, 0)
        activities = owner["activities"]
        activities.pop(activity_id, None)
        if activities:
            owner["updatedAt"] = now
            owner["expiresAt"] = max(
                activity["expiresAt"] for activity in activities.values()
            )
            owners[owner_id] = owner
            close_ui = False
        else:
            owners.pop(owner_id, None)
            close_ui = True
        write_ui_owners(state_path, owners)
        return UiReleaseDecision(close_ui, len(activities))


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


def dispatch_prompt(
    client: DshClient,
    session_id: str,
    text: str,
    mode: str,
    ui_owner_id: Optional[str] = None,
    ui_activity_id: Optional[str] = None,
) -> WaitReceipt:
    with session_lock(client.base_url, session_id):
        ensure_session_idle(client, session_id)
        cursor = history_cursor(client.history(session_id))
        response = client.prompt_with_rpc_id(session_id, text, mode)
        return WaitReceipt(
            session_id=session_id,
            rpc_id=response.rpc_id,
            cursor=cursor,
            ui_owner_id=ui_owner_id,
            ui_activity_id=ui_activity_id,
        )


def encode_wait_receipt(receipt: WaitReceipt) -> str:
    if (receipt.ui_owner_id is None) != (receipt.ui_activity_id is None):
        raise DshClientError("wait receipt UI owner and activity must be paired")
    payload = {
        "v": 2 if receipt.ui_activity_id is not None else 1,
        "session": receipt.session_id,
        "rpc": receipt.rpc_id,
        "count": receipt.cursor.length,
        "seq": receipt.cursor.sequence,
    }
    if receipt.ui_activity_id is not None:
        payload["owner"] = receipt.ui_owner_id
        payload["ui"] = receipt.ui_activity_id
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_wait_receipt(value: str) -> WaitReceipt:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DshClientError("invalid wait receipt") from error
    if not isinstance(payload, dict) or payload.get("v") not in {1, 2}:
        raise DshClientError("invalid wait receipt")
    version = payload["v"]
    session_id = payload.get("session")
    rpc_id = payload.get("rpc")
    count = payload.get("count")
    sequence = payload.get("seq")
    ui_owner_id = payload.get("owner")
    ui_activity_id = payload.get("ui")
    if (
        not isinstance(session_id, str)
        or not session_id
        or not isinstance(rpc_id, str)
        or not rpc_id
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        or (
            sequence is not None
            and (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0)
        )
        or (
            ui_owner_id is not None
            and (not isinstance(ui_owner_id, str) or not ui_owner_id)
        )
        or (
            ui_activity_id is not None
            and (not isinstance(ui_activity_id, str) or not ui_activity_id)
        )
        or ((ui_owner_id is None) != (ui_activity_id is None))
        or (version == 1 and ui_owner_id is not None)
        or (version == 2 and ui_owner_id is None)
    ):
        raise DshClientError("invalid wait receipt")
    return WaitReceipt(
        session_id=session_id,
        rpc_id=rpc_id,
        cursor=HistoryCursor(length=count, sequence=sequence),
        ui_owner_id=ui_owner_id,
        ui_activity_id=ui_activity_id,
    )


def task_title(prompt: str, session_id: str) -> str:
    summary = " ".join(prompt.split())
    if not summary:
        raise DshClientError("task prompt must not be empty")
    if len(summary) > 56:
        summary = f"{summary[:53].rstrip()}..."
    compact_id = "".join(character for character in session_id if character.isalnum())
    if len(compact_id) >= 8:
        suffix = f"{compact_id[:4]}-{compact_id[-4:]}"
    else:
        suffix = compact_id or "session"
    return f"Codex: {summary} [{suffix}]"


def ensure_server(
    client: DshClient, startup_timeout: float, poll_interval: float
) -> None:
    try:
        client.health()
    except DshUnavailableError:
        start_dsh_server(client, startup_timeout, poll_interval)


def run_task(
    client: DshClient,
    *,
    cwd: Optional[str],
    session_id: Optional[str],
    intent: str,
    prompt: str,
    show_ui: bool,
    timeout: float,
    startup_timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    ensure_server(client, startup_timeout, poll_interval)
    if session_id is None:
        if cwd is None:
            raise DshClientError("task requires --cwd when --session is not provided")
        resolved_cwd = Path(cwd).expanduser().resolve()
        if not resolved_cwd.is_dir():
            raise DshClientError(f"session cwd is not a directory: {resolved_cwd}")
        session_id = client.create(str(resolved_cwd))

    permission = INTENT_PERMISSIONS[intent]
    permission_result = set_session_permission(client, session_id, permission)
    title = client.rename(session_id, task_title(prompt, session_id))["title"]

    output: dict[str, Any] = {
        "sessionId": session_id,
        "permission": permission_result["currentValue"],
        "title": title,
    }
    if show_ui:
        ui_limit = env_nonnegative_int("DSH_UI_LIMIT", DEFAULT_UI_LIMIT)
        owner_id = codex_thread_id()
        activity = acquire_ui_activity(
            client.base_url,
            owner_id,
            session_id,
            ui_limit,
            env_float("DSH_UI_ACTIVITY_TTL", DEFAULT_UI_ACTIVITY_TTL),
            time.time(),
        )
        if activity.activity_id is None:
            raise DshClientError(
                f"DSH Web UI owner limit reached ({activity.active}/{activity.limit}); "
                "wait for another Codex task to release its shared DSH UI"
            )
        try:
            dispatch = dispatch_prompt(
                client,
                session_id,
                prompt,
                "queue",
                ui_owner_id=owner_id,
                ui_activity_id=activity.activity_id,
            )
        except BaseException:
            release_ui_activity(owner_id, activity.activity_id)
            raise
        output.update(
            {
                "status": "dispatched",
                "ui": {
                    "url": thread_ui_url(client.base_url, owner_id),
                    "title": title,
                    "ownerId": owner_id,
                    "reuse": activity.reused,
                    "owners": {"active": activity.active, "limit": activity.limit},
                },
                "receipt": encode_wait_receipt(dispatch),
            }
        )
        return output

    output.update(
        {
            "status": "completed",
            "answer": run_prompt(
                client,
                session_id,
                prompt,
                "queue",
                timeout,
                poll_interval,
            ),
        }
    )
    return output


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
        description="Run Codex tasks through a local DSH Web service."
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
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=env_float("DSH_STARTUP_TIMEOUT", DEFAULT_STARTUP_TIMEOUT),
        help="timeout while starting the local DSH Web service in seconds",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="check Python, DSH, npm, and server readiness")

    task_parser = subparsers.add_parser(
        "task", help="create or reuse a session, send a prompt, and return the result"
    )
    location = task_parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--cwd", help="repository path for a new session")
    location.add_argument("--session", help="existing DSH session ID")
    task_parser.add_argument(
        "--intent",
        choices=tuple(INTENT_PERMISSIONS),
        required=True,
        help="read, write, or explicitly requested full access",
    )
    task_parser.add_argument("--prompt", required=True)
    ui_mode = task_parser.add_mutually_exclusive_group()
    ui_mode.add_argument(
        "--ui",
        dest="ui",
        action="store_true",
        default=True,
        help="dispatch so Codex can select the session in DSH Web (default)",
    )
    ui_mode.add_argument(
        "--no-ui",
        dest="ui",
        action="store_false",
        help="wait without opening the DSH Web session",
    )

    wait_parser = subparsers.add_parser(
        "wait", help="wait for a task previously dispatched with task --ui"
    )
    wait_parser.add_argument("receipt")

    release_parser = subparsers.add_parser(
        "release", help="release UI ownership without cancelling the DSH session"
    )
    release_parser.add_argument("receipt")

    debug_parser = subparsers.add_parser(
        "debug", help="low-level service and session diagnostics"
    )
    debug_commands = debug_parser.add_subparsers(dest="debug_command", required=True)
    debug_commands.add_parser("health", help="check whether DSH Web is reachable")
    debug_commands.add_parser("start", help="start a local DSH Web service if needed")
    history_parser = debug_commands.add_parser("history", help="print session history")
    history_parser.add_argument("session_id")
    history_parser.add_argument("--messages", action="store_true")
    debug_commands.add_parser("list", help="list sessions")
    cancel_parser = debug_commands.add_parser("cancel", help="cancel a session")
    cancel_parser.add_argument("session_id")
    permission_parser = debug_commands.add_parser(
        "permission", help="inspect or enforce a session permission preset"
    )
    permission_parser.add_argument("session_id")
    permission_parser.add_argument("preset", nargs="?", choices=PERMISSION_PRESETS)
    return parser


def validate_positive(parser: argparse.ArgumentParser, name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        parser.error(f"{name} must be a finite number greater than zero")


def main() -> int:
    require_supported_python()
    parser = build_parser()
    args = parser.parse_args()
    validate_positive(parser, "--http-timeout", args.http_timeout)
    validate_positive(parser, "--timeout", args.timeout)
    validate_positive(parser, "--poll-interval", args.poll_interval)
    validate_positive(parser, "--startup-timeout", args.startup_timeout)
    client = DshClient(args.url, args.http_timeout)

    if args.command == "doctor":
        report = doctor_report(client)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 1
    if args.command == "task":
        print(
            json.dumps(
                run_task(
                    client,
                    cwd=args.cwd,
                    session_id=args.session,
                    intent=args.intent,
                    prompt=args.prompt,
                    show_ui=args.ui,
                    timeout=args.timeout,
                    startup_timeout=args.startup_timeout,
                    poll_interval=args.poll_interval,
                ),
                ensure_ascii=False,
            )
        )
    elif args.command == "wait":
        receipt = decode_wait_receipt(args.receipt)
        owner_id = receipt.ui_owner_id
        release = UiReleaseDecision(False, 0)
        wait_error: Optional[BaseException] = None
        answer: Optional[str] = None
        try:
            answer = wait_for_turn(
                client,
                receipt.session_id,
                receipt.cursor,
                args.timeout,
                args.poll_interval,
                prompt_rpc_id=receipt.rpc_id,
            )
        except BaseException as error:
            wait_error = error
        finally:
            release = release_ui_activity(
                owner_id,
                receipt.ui_activity_id,
            )
        output: dict[str, Any] = {
            "status": "completed" if wait_error is None else "failed",
            "sessionId": receipt.session_id,
        }
        if wait_error is None:
            output["answer"] = answer
        else:
            output["error"] = (
                "interrupted" if isinstance(wait_error, KeyboardInterrupt) else str(wait_error)
            )
        if receipt.ui_activity_id is not None:
            output["ui"] = {
                "ownerId": owner_id,
                "close": release.close_ui,
                "activeTasks": release.active,
            }
        print(json.dumps(output, ensure_ascii=False))
        if wait_error is not None:
            raise wait_error
    elif args.command == "release":
        receipt = decode_wait_receipt(args.receipt)
        release = release_ui_activity(
            receipt.ui_owner_id,
            receipt.ui_activity_id,
        )
        print(
            json.dumps(
                {
                    "status": "released",
                    "sessionId": receipt.session_id,
                    "ui": {
                        "ownerId": receipt.ui_owner_id,
                        "close": release.close_ui,
                        "activeTasks": release.active,
                    },
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "debug" and args.debug_command == "health":
        client.health()
        print(f"DSH Web is reachable at {client.base_url}")
    elif args.command == "debug" and args.debug_command == "start":
        result = start_dsh_server(client, args.startup_timeout, args.poll_interval)
        if result.started:
            pid = f" (pid {result.pid})" if result.pid is not None else ""
            print(
                f"Started DSH Web at {client.base_url}{pid}; "
                f"runtime: {result.runtime_path}; log: {result.log_path}"
            )
        else:
            print(f"DSH Web is already reachable at {client.base_url}")
    elif args.command == "debug" and args.debug_command == "permission":
        if args.preset is None:
            output = {
                "sessionId": args.session_id,
                **session_permission(client.history_page(args.session_id)),
            }
        else:
            output = set_session_permission(client, args.session_id, args.preset)
        print(json.dumps(output, ensure_ascii=False))
    elif args.command == "debug" and args.debug_command == "history":
        events = client.history(args.session_id)
        output = compact_messages(events) if args.messages else events
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "debug" and args.debug_command == "list":
        print(json.dumps(client.list_sessions(), ensure_ascii=False, indent=2))
    elif args.command == "debug" and args.debug_command == "cancel":
        print(json.dumps(client.cancel(args.session_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DshClientError as error:
        fail(str(error))
    except KeyboardInterrupt:
        fail("interrupted", 130)
