# DSH Web HTTP API

Use this reference to debug the bundled client or work around a DSH Web compatibility issue.

## Transport

The default base URL is `http://127.0.0.1:8765`. Send JSON with `POST /api/<method>`:

```json
{
  "type": "client-request",
  "rpcId": "3c261d97-90ff-4894-9a54-6d7f8a62cb27",
  "method": "session.create",
  "payload": {"cwd": "/absolute/path/to/repo"}
}
```

The expected response repeats the request ID:

```json
{
  "type": "server-response",
  "rpcId": "3c261d97-90ff-4894-9a54-6d7f8a62cb27",
  "result": {"ok": true, "value": {"sessionId": "..."}}
}
```

Treat a response type other than `server-response`, a mismatched `rpcId`, a
non-object `result`, or `result.ok` set to false as a protocol error.

The Python client does not require a POSIX login shell. It calls DSH with an
argument vector and the platform subprocess API. Run it from an explicitly
verified working directory; a stale `cwd` can make process creation fail before
`/bin/sh`, `zsh`, PowerShell, or the requested executable starts.

The managed DSH Web process runs from
`$DSH_HOME/runtime/codex-dsh-web/<port>`, not from a project or plugin cache.
DSH treats its process directory as the fallback workspace and loads a `.env`
from that directory during boot. Every API-created session must therefore send
its own absolute `cwd`; DSH uses that session cwd as the workspace-write sandbox
boundary.

## Methods

| Method | Payload | Important result |
| --- | --- | --- |
| `session.create` | `{"cwd":"/absolute/path"}` | `value.sessionId` |
| `session.rename` | `{"sessionId":"...","title":"..."}` | normalized `value.title` and event `seq` |
| `session.prompt` | `{"sessionId":"...","mode":"queue","content":[{"type":"text","text":"..."}]}` | acknowledgement |
| `session.history` | `{"sessionId":"..."}` | `value.events[]` |
| `session.list` | `{}` | session collection; current servers expose `items[].running` |
| `session.cancel` | `{"sessionId":"..."}` | acknowledgement |

## History events

History entries normally wrap the event as `{"event": {...}}`; tolerate an unwrapped event for compatibility. The relevant event fields are:

- `seq`: monotonically increasing sequence number when provided.
- `type: "turn/start"`: a turn began.
- `type: "user/message"`: the prompt source currently repeats its request RPC ID
  at `data.source.rpcId`; `run` uses it with `data.turn` to identify the prompted
  turn.
- `type: "assistant/message"`: final assistant message; text blocks live at `data.message.content[]`.
- `type: "assistant/chunk"`: streamed content for the UI; ignore when extracting a final answer.
- `type: "turn/end"`: terminal event; `data.reason.kind` is normally `completed` or `error`.

When sequence numbers are unavailable, the client uses the history array length
captured before prompting as its cursor. In mixed histories it keeps both events
with a newer sequence and unsequenced events appended after the captured length.

`run` checks `session.list` before prompting, takes a cross-process lock scoped to
the DSH URL and session ID, and waits for the turn associated with the prompt RPC
ID. This protects bundled-client callers. Prompts sent manually in the DSH UI or
through another client remain external concurrency and should use a separate
session.

`dispatch` performs the same idle check and pre-prompt history snapshot but
returns the prompt `rpcId`, history count, and sequence cursor instead of waiting.
Pass that receipt to `wait --rpc-id ...` after selecting the session in the UI.
This preserves correlation even when the turn completes before browser
selection finishes.

The browser UI does not expose a per-session route in DSH Web 0.1.0-rc.6. Its
address remains the base `/` URL after a session is selected. `ui-target` reads
the `projections.values.title` field from the tail `session.history` response;
Codex must search for and click that title in the session tree, then verify the
selected state and conversation header.

## Common failures

- Connection refused: DSH Web is not listening at `DSH_URL`.
- Missing Python: use Python 3.9 or later. On Windows, `py -3` is a supported
  launcher; on macOS and Linux, prefer `python3`.
- Process spawn `No such file or directory`: verify the command tool's explicit
  working directory first, then verify the executable. Do not diagnose a missing
  `zsh`; this client never requires it.
- Missing DSH: run `doctor`, install Node.js/npm if needed, then install
  DeepSeek Harness with `npm install --global @deepseek-ai/dsh` only after the
  user authorizes installation.
- HTTP 403: the request authority may have failed the browser trust fence; use loopback and check DSH Web's `--trusted-host` support.
- HTTP 404: the running DSH Web version may not expose the expected method.
- RPC error: inspect the returned error object and session history.
- Local startup failure: use the log path printed by `start` or `doctor`; it is
  stored in the operating system's temporary directory.
- Existing service has a project cwd: stop that service only after confirming
  that no session is running, then run `start` once so the managed runtime path
  takes effect. A healthy existing service is intentionally reused.
- Wait timeout: inspect `history --messages`, `list`, and the reported server log; do not blindly create another session.
