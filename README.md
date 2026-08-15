# DSH Web for Codex

English | [简体中文](README_CN.md)

`codex-dsh-web` is a local Codex plugin that lets Codex collaborate with DeepSeek Harness through the DSH Web HTTP API.

Codex can create or reuse a DSH session, delegate development tasks, wait for DSH to finish, inspect the resulting files, and run local validation. When validation fails, Codex can send the result back to the same session and continue the implementation–verification loop. The DSH Web browser interface displays the same conversation, tool calls, and execution trace.

## How it works

```text
Codex
  │
  ├─ POST /api/session.create ── create an isolated session
  ├─ POST /api/session.prompt ── send a task or validation result
  ├─ POST /api/session.history ─ wait for turn/end and read the answer
  │
  └─ inspect diffs and run test/lint/build locally
                    │
                    ▼
          DSH Web http://127.0.0.1:8765
          ├─ local HTTP API
          └─ browser visualization
```

One DSH Web process can host multiple independent sessions. Separate Codex tasks normally create separate `sessionId` values while sharing the same service process.

## Project structure

```text
codex-dsh-web/
├── .agents/plugins/marketplace.json
├── .codex-plugin/plugin.json
├── skills/dsh-web/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/api.md
│   └── scripts/dsh_client.py
└── tests/test_dsh_client.py
```

The plugin ID is `codex-dsh-web`, its display name is **DSH Web for Codex**, and its skill is `$dsh-web`.

## Requirements

- `dsh` is installed and `dsh --profile web --help` works.
- A DeepSeek API key is configured in the DSH Web Models page or inherited environment.
- Codex can access the loopback network and write to the target repository and `DSH_HOME` (normally `~/.dsh`).
- Python 3.10 or later. The client uses only the Python standard library.

Start DSH Web:

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
open http://127.0.0.1:8765
```

## Installation

Register this GitHub repository as a Codex plugin marketplace, then install the plugin:

```bash
codex plugin marketplace add OpenNekoPaw/codex-dsh-web --ref main
codex plugin add codex-dsh-web@codex-dsh-web
```

To confirm the installation:

```bash
codex plugin marketplace list
codex plugin list
```

Start a new Codex task after installation. Existing tasks do not automatically load newly installed skills.

## Usage

Explicitly naming the skill is the most reliable invocation method:

```text
Use $dsh-web to ask DSH to fix the failing tests, then inspect the changes and run the tests yourself.
```

Natural-language invocation also works:

```text
Use dsh web to implement this feature, then have Codex independently verify it.
```

The skill metadata permits implicit invocation, but Codex does not scan for or call DSH merely because port `8765` is running. Ordinary development requests that do not mention DSH do not use this plugin by default. To make DSH the preferred collaborator for one project, add a rule to that project's `AGENTS.md`:

```markdown
For code implementation, fixes, or testing, prefer `$dsh-web` to delegate the
work to DSH Web, then independently inspect the changes and run validation.
```

## Direct client usage

You can test the HTTP client without installing the plugin:

```bash
CLIENT="$PWD/skills/dsh-web/scripts/dsh_client.py"

python3 "$CLIENT" health
SESSION_ID="$(python3 "$CLIENT" create --cwd "$PWD")"
python3 "$CLIENT" run "$SESSION_ID" "Read README.md and summarize the project. Do not modify files."
python3 "$CLIENT" history "$SESSION_ID" --messages
```

Continue the same session:

```bash
python3 "$CLIENT" run "$SESSION_ID" \
  "Validation result: one test still fails with <error>. Please continue fixing it."
```

### Client commands

| Command | Purpose |
| --- | --- |
| `health` | Check whether DSH Web is reachable |
| `create` | Create a session rooted at a target directory |
| `run` | Send a prompt and wait for the new turn |
| `prompt` | Send a prompt without waiting |
| `wait` | Wait for a subsequent `turn/end` |
| `history` | Print raw history or a compact transcript |
| `list` | List DSH sessions |
| `cancel` | Cancel a session |
| `open` | Open DSH Web on macOS |

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DSH_URL` | `http://127.0.0.1:8765` | DSH Web base URL |
| `DSH_HTTP_TIMEOUT` | `30` | Timeout for each HTTP request in seconds |
| `DSH_TIMEOUT` | `600` | Timeout while waiting for a turn in seconds |
| `DSH_POLL_INTERVAL` | `2` | History polling interval in seconds |

## Validate a development version

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/dsh-web/scripts/dsh_client.py
python3 /path/to/skill-creator/scripts/quick_validate.py skills/dsh-web
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

An end-to-end test calls a real model and may incur API charges:

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
CLIENT="$PWD/skills/dsh-web/scripts/dsh_client.py"
SESSION_ID="$(python3 "$CLIENT" create --cwd "$PWD")"
python3 "$CLIENT" run "$SESSION_ID" "Read README.md and reply with only the project name. Do not modify files."
```

The test succeeds when the command returns a DSH answer and `http://127.0.0.1:8765` shows the same session and trace.

## Update the installation

Refresh the GitHub marketplace snapshot, reinstall the plugin, and start a new Codex task:

```bash
codex plugin marketplace upgrade codex-dsh-web
codex plugin add codex-dsh-web@codex-dsh-web
```

## Troubleshooting

### `health` reports connection refused

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
tail -n 100 /tmp/dsh-web.log
```

### Codex cannot find `$dsh-web`

Confirm that the plugin is installed, fully restart the desktop app, and start a new task. Existing tasks do not reload newly added skills.

### Codex does not invoke DSH automatically

Invoke `$dsh-web` explicitly or mention “use dsh web” in the request. Add a collaboration rule to the target repository's `AGENTS.md` when project-wide default behavior is desired.

### Do multiple Codex tasks start multiple DSH processes?

Normally, no. The skill checks the same `DSH_URL` first. Multiple tasks share one DSH Web process while creating separate sessions. Multiple service processes are used only when tasks are configured with different ports or `DSH_URL` values.

## Security

- Do not send API keys, passwords, or complete environment dumps to a DSH session.
- When returning validation failures, include only the command, exit code, and relevant error excerpt.
- Treat DSH responses as collaboration output, not verification. Codex should inspect the actual files and run relevant tests.
- DSH write access is governed by its permission configuration and the surrounding Codex environment.

See the [OpenAI plugin documentation](https://developers.openai.com/plugins/build/plugins) for additional local marketplace and plugin packaging guidance.
