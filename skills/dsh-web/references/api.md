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

Treat a mismatched `rpcId`, a non-object `result`, or `result.ok` set to false as a protocol error.

## Methods

| Method | Payload | Important result |
| --- | --- | --- |
| `session.create` | `{"cwd":"/absolute/path"}` | `value.sessionId` |
| `session.prompt` | `{"sessionId":"...","mode":"queue","content":[{"type":"text","text":"..."}]}` | acknowledgement |
| `session.history` | `{"sessionId":"..."}` | `value.events[]` |
| `session.list` | `{}` | implementation-defined session collection |
| `session.cancel` | `{"sessionId":"..."}` | acknowledgement |

## History events

History entries normally wrap the event as `{"event": {...}}`; tolerate an unwrapped event for compatibility. The relevant event fields are:

- `seq`: monotonically increasing sequence number when provided.
- `type: "turn/start"`: a turn began.
- `type: "assistant/message"`: final assistant message; text blocks live at `data.message.content[]`.
- `type: "assistant/chunk"`: streamed content for the UI; ignore when extracting a final answer.
- `type: "turn/end"`: terminal event; `data.reason.kind` is normally `completed` or `error`.

When sequence numbers are unavailable, the client uses the history array length captured before prompting as its cursor. When both are available, it filters by sequence number to avoid replaying old messages.

## Common failures

- Connection refused: DSH Web is not listening at `DSH_URL`.
- HTTP 403: the request authority may have failed the browser trust fence; use loopback and check DSH Web's `--trusted-host` support.
- HTTP 404: the running DSH Web version may not expose the expected method.
- RPC error: inspect the returned error object and session history.
- Wait timeout: inspect `history --messages`, `list`, and `/tmp/dsh-web.log`; do not blindly create another session.
