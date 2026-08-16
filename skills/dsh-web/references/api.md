# Client reference

The bundled client is a dependency-free Python 3.9+ interface to DSH Web.

```text
python3 dsh_client.py [global options] {doctor,task,wait,debug}
```

On Windows, `py -3` can replace `python3`.

## Global options

| Option | Default | Purpose |
| --- | --- | --- |
| `--url` | `DSH_URL` or `http://127.0.0.1:8765` | DSH Web base URL |
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
  --prompt "Implement the feature"
```

Continue an existing session:

```text
python3 dsh_client.py task \
  --session <session-id> \
  --intent read \
  --prompt "Review the current implementation"
```

Intent mapping:

| Intent | Effective DSH permission |
| --- | --- |
| `read` | `read-only` |
| `write` | `workspace-write` |
| `full-access` | `danger-full-access` |

Without `--ui`, the command waits and returns:

```json
{
  "status": "completed",
  "sessionId": "...",
  "permission": "workspace-write",
  "title": "Codex: Implement the feature [a65d-ed81]",
  "answer": "..."
}
```

The command checks health, starts a refused local loopback service, creates or reuses the session, verifies permissions, sets a stable title, and correlates the answer to its prompt.

## task --ui and wait

```text
python3 dsh_client.py task \
  --cwd /absolute/repository/path \
  --intent write \
  --prompt "Implement the feature" \
  --ui
```

This dispatches immediately:

```json
{
  "status": "dispatched",
  "sessionId": "...",
  "permission": "workspace-write",
  "title": "Codex: Implement the feature [a65d-ed81]",
  "ui": {
    "url": "http://127.0.0.1:8765",
    "title": "Codex: Implement the feature [a65d-ed81]"
  },
  "receipt": "opaque-value"
}
```

After Codex selects the exact title in the DSH Web UI:

```text
python3 dsh_client.py wait <receipt>
```

`receipt` is opaque and versioned. Do not parse, edit, or persist it as a public protocol. A completed wait returns compact JSON with `status`, `sessionId`, and `answer`.

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
