# Client reference

The bundled client is a dependency-free Python 3.9+ interface to DSH Web.

```text
python3 dsh_client.py [global options] {doctor,task,wait,release,debug}
```

On Windows, `py -3` can replace `python3`.

## Global options

| Option | Default | Purpose |
| --- | --- | --- |
| `--url` | `DSH_URL` or `http://localhost:8765` | DSH Web base URL |
| `--http-timeout` | 30 seconds | Per-request timeout |
| `--timeout` | 3600 seconds | Task completion timeout |
| `--poll-interval` | 2 seconds | History polling interval |
| `--startup-timeout` | 20 seconds | Local server startup timeout |

Global options must appear before the command.

## doctor

```text
python3 dsh_client.py doctor
```

Prints one JSON report covering Python, npm, DSH, and server readiness. It does not install dependencies.

## task

Create a session for a repository:

```text
python3 dsh_client.py task \
  --cwd /absolute/repository/path \
  --intent write \
  --prompt "Implement the feature" \
  --ui
```

Continue an existing session:

```text
python3 dsh_client.py task \
  --session <session-id> \
  --intent read \
  --prompt "Review the current implementation" \
  --ui
```

Intent mapping:

| Intent | Effective DSH permission |
| --- | --- |
| `read` | `read-only` |
| `write` | `workspace-write` |
| `full-access` | `danger-full-access` |

The command checks health, starts a refused local loopback service, creates or reuses the repository's registered DSH workspace, attaches each new session to that workspace, verifies permissions, sets a stable title, and correlates the answer to its prompt. Workspace creation is idempotent for the same canonical directory, so repeated sessions do not create duplicate workspace groups or fall into the ungrouped section.

## Default UI task and wait

```text
python3 dsh_client.py task \
  --cwd /absolute/repository/path \
  --intent write \
  --prompt "Implement the feature" \
  --ui
```

UI mode is the default; `--ui` makes the intent explicit. The command dispatches immediately:

```json
{
  "status": "dispatched",
  "sessionId": "...",
  "permission": "workspace-write",
  "title": "Codex: Implement the feature [a65d-ed81]",
  "ui": {
    "url": "http://localhost:8765/?codexThreadId=01a0089b-...",
    "title": "Codex: Implement the feature [a65d-ed81]",
    "ownerId": "01a0089b-...",
    "reuse": false,
    "owners": {"active": 1, "limit": 10}
  },
  "receipt": "opaque-value"
}
```

Codex must reuse the one in-app Browser tab owned by `ui.ownerId`, never Computer Use picture-in-picture, an external browser, or a headless fallback. The owner is the Codex task ID, not the DSH URL or session ID. After Codex selects the exact title in that DSH Web UI:

Use the returned `localhost` URL verbatim. Do not normalize it to `127.0.0.1`. Automatic startup still binds the managed DSH process to IPv4 loopback.

```text
python3 dsh_client.py wait <receipt>
```

`receipt` is opaque and versioned. Do not parse, edit, or persist it as a public protocol. `wait` releases the receipt's UI activity on completion, timeout, error, or interruption. Current receipts return `ui.close` and `ui.activeTasks`; close the shared tab only when `ui.close` is true.

If orchestration fails before `wait` can return cleanup state, release UI ownership without waiting for or cancelling DSH:

```text
python3 dsh_client.py release <receipt>
```

Apply the returned `ui.close` value using the same rule. `release` is idempotent and does not cancel or delete the DSH session.

The lower-level client retains `--no-ui` for explicit direct callers, but the `dsh-web` skill always uses UI mode and never selects it as a fallback. A direct `--no-ui` call waits in the task command and returns:

```json
{
  "status": "completed",
  "sessionId": "...",
  "permission": "workspace-write",
  "title": "Codex: Implement the feature [a65d-ed81]",
  "answer": "..."
}
```

## debug

Low-level commands are grouped under `debug`:

```text
python3 dsh_client.py debug health
python3 dsh_client.py debug start
python3 dsh_client.py debug list
python3 dsh_client.py debug history <session-id> [--messages]
python3 dsh_client.py debug permission <session-id> [preset]
python3 dsh_client.py debug cancel <session-id>
```

These commands are for diagnosis and compatibility checks. Normal skill operation should use `task` and `wait`, with `release` only as the cleanup fallback.

## Environment variables

The timeout options also accept:

- `DSH_URL`
- `DSH_HTTP_TIMEOUT`
- `DSH_TIMEOUT` (default: `3600` seconds)
- `DSH_POLL_INTERVAL`
- `DSH_STARTUP_TIMEOUT`
- `DSH_HOME`
- `DSH_UI_LIMIT` (default: `10` concurrent Codex task owners)
- `DSH_UI_ACTIVITY_TTL` (default: `18000` seconds)
- `DSH_UI_OWNER_ID` (explicit non-Codex owner override)

Automatic startup is limited to plain HTTP loopback URLs. The managed process runs from `$DSH_HOME/runtime/codex-dsh-web/<port>`, separate from the repository and plugin cache.
