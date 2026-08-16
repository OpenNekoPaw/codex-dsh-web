# Client reference

The bundled client is a dependency-free Python 3.9+ interface to DSH Web.

```text
python3 dsh_client.py [global options] {doctor,task,wait,debug}
```

On Windows, `py -3` can replace `python3`.

## Global options

| Option | Default | Purpose |
| --- | --- | --- |
| `--url` | `DSH_URL` or `http://localhost:8765` | DSH Web base URL |
| `--http-timeout` | 30 seconds | Per-request timeout |
| `--timeout` | 600 seconds | Task completion timeout |
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

The command checks health, starts a refused local loopback service, creates or reuses the session, verifies permissions, sets a stable title, and correlates the answer to its prompt.

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
    "url": "http://localhost:8765",
    "title": "Codex: Implement the feature [a65d-ed81]"
  },
  "receipt": "opaque-value"
}
```

Codex must open `ui.url` in the in-app Browser side panel, never Computer Use picture-in-picture or an external browser. After Codex selects the exact title in that DSH Web UI:

Use the returned `localhost` URL verbatim. Do not normalize it to `127.0.0.1`. Automatic startup still binds the managed DSH process to IPv4 loopback.

```text
python3 dsh_client.py wait <receipt>
```

`receipt` is opaque and versioned. Do not parse, edit, or persist it as a public protocol. A completed wait returns compact JSON with `status`, `sessionId`, and `answer`.

Use `--no-ui` only for an explicitly headless call. It waits in the task command and returns:

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

These commands are for diagnosis and compatibility checks. Normal skill operation should use `task` and `wait`.

## Environment variables

The timeout options also accept:

- `DSH_URL`
- `DSH_HTTP_TIMEOUT`
- `DSH_TIMEOUT`
- `DSH_POLL_INTERVAL`
- `DSH_STARTUP_TIMEOUT`
- `DSH_HOME`

Automatic startup is limited to plain HTTP loopback URLs. The managed process runs from `$DSH_HOME/runtime/codex-dsh-web/<port>`, separate from the repository and plugin cache.
