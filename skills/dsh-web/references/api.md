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
- Missing DSH: run `doctor`, install Node.js/npm if needed, then install
  DeepSeek Harness with `npm install --global @deepseek-ai/dsh` only after the
  user authorizes installation.
- HTTP 403: the request authority may have failed the browser trust fence; use loopback and check DSH Web's `--trusted-host` support.
- HTTP 404: the running DSH Web version may not expose the expected method.
- RPC error: inspect the returned error object and session history.
- Local startup failure: use the log path printed by `start` or `doctor`; it is
  stored in the operating system's temporary directory.
- Wait timeout: inspect `history --messages`, `list`, and the reported server log; do not blindly create another session.
