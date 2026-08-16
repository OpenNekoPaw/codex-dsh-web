# DSH Web for Codex

English | [简体中文](README_CN.md)

`codex-dsh-web` is a local Codex plugin that lets Codex collaborate with DeepSeek Harness through the DSH Web HTTP API.

Codex can create or reuse a DSH session, delegate development tasks, wait for DSH to finish, inspect the resulting files, and run local validation. When validation fails, Codex can send the result back to the same session and continue the implementation–verification loop. The DSH Web browser interface displays the same conversation, tool calls, and execution trace.

## How it works

```text
Codex
  │
  ├─ POST /api/session.create ── create an isolated session
  ├─ POST /api/commands/execute ─ enforce and verify its permission
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

The shared service process runs from a dedicated directory under
`$DSH_HOME/runtime/codex-dsh-web/<port>`. Each session receives its actual
repository through the required `session.create` `cwd`, so the daemon runtime,
project workspace, and persistent DSH data remain separate.

In Codex Desktop, the DSH page can be opened directly in the built-in Browser/WebView panel. The HTTP API remains the reliable control channel; the embedded page provides the visible conversation and trace, and can also be inspected or operated when browser control is explicitly requested.

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

- Python 3.9 or later. The client uses only the Python standard library.
- DeepSeek Harness is installed and `dsh --profile web --help` works. Its npm
  package is `@deepseek-ai/dsh`.
- A DeepSeek API key is configured in the DSH Web Models page or inherited environment.
- Codex can access the loopback network and write to the target repository and `DSH_HOME` (normally `~/.dsh`).

Install DSH manually when needed:

```bash
npm install --global @deepseek-ai/dsh
dsh --version
```

The plugin does not install Python, Node.js, npm, or DSH during plugin
installation. On first use, the skill checks for Python 3.9+, then checks DSH
only when the configured server is unavailable. It explains the missing
dependency and asks before running any installer.

### Platform support

The dependency-free client supports macOS, Linux, and Windows. It uses
platform-specific file locking and detached-process flags, stores logs in the
operating system temporary directory, and uses the Python default-browser API
for its external-browser fallback. The Codex Browser/WebView remains the
preferred UI surface.

The plugin does not require `zsh`, `bash`, or another login shell. Codex should
run the Python client with an explicit existing working directory and pass the
target repository through `create --cwd`. A stale task directory can produce a
process-spawn `No such file or directory` error before any shell starts; that is
not evidence that `zsh` is missing.

The client never starts the shared DSH Web process inside a target repository or
plugin cache. DSH treats its process directory as a fallback workspace and reads
that directory's `.env` during startup, so the managed runtime is intentionally
project-neutral and stable across plugin upgrades.

Examples use `python3` on macOS and Linux. On Windows, replace it with `py -3`;
`python` is also valid on any platform when it resolves to Python 3.9 or later.

| Platform | Python check | Client invocation |
| --- | --- | --- |
| macOS / Linux | `python3 --version` | `python3 "/absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py" <command>` |
| Windows PowerShell | `py -3 --version` | `py -3 "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py" <command>` |
| Windows Command Prompt | `py -3 --version` | `py -3 "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py" <command>` |

These are launcher differences, not separate implementations. Every platform
runs the same Python client and uses the same client subcommands and HTTP API.

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

To keep the live DSH interface beside the Codex task, ask Codex to open it:

```text
Use $dsh-web for this task and open the DSH Web UI in the built-in browser.
```

Codex Desktop should open `DSH_URL` in its Browser/WebView panel. When that
surface is unavailable, the client's `open` command falls back to the platform
default browser. Opening the page alone does not replace API-based result
collection or synchronize the visible session; UI inspection or interaction
must be explicitly requested.

DSH Web currently keeps the selected session in client-side state: choosing a
session does not change the `/` URL. For an API-driven task, the skill assigns a
unique title, dispatches the prompt, opens the sidebar or session search when it
is collapsed, searches the exact title, clicks its session item, and verifies
both `aria-selected="true"` and the visible conversation title. Loading `/` may
restore an older client-side selection, so any old conversation or New Session
composer is a synchronization failure until those checks pass.

The in-app Browser is the primary control surface. Computer Use is a fallback
only when semantic Browser control remains unable to interact with the page
after inspection and recovery; a collapsed sidebar by itself does not require
the fallback.

The first plugin starter prompt performs this UI-only action, so opening the
plugin without an implementation request should still open the Browser panel
instead of asking what code change to make. A URL link or website preview card
does not count as opening the panel.

### DSH session configuration

The plugin does not require a fixed agent preset or model. Permission selection
is automatic and does not require the user to configure DSH Web:

- `minimal` is a practical low-overhead preset, but it is not required by the protocol.
- Codex selects and verifies `read-only` for analysis and `workspace-write` for implementation.
- `danger-full-access` is used only when the user explicitly requests work that needs writes outside the workspace boundary.
- Select the DSH model according to task quality, latency, and cost needs. The client reuses the session's configured model and does not hard-code one.

The client applies permissions through the same command RPC used by the DSH Web
UI, then verifies `session.history` reports the requested effective preset before
it sends a prompt. It never treats a natural-language "do not modify files"
instruction as a permission boundary. Agent preset and model selection remain
unchanged unless the user asks to change them.

## Direct client usage

You can test the HTTP client without installing the plugin:

```text
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py doctor
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py start
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py health
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py create --cwd /absolute/repository/path --permission read-only
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py run <session-id> "Read README.md and summarize the project. Do not modify files."
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py history <session-id> --messages
```

Continue the same session:

```text
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py run <session-id> "Validation result: one test still fails with <error>. Please continue fixing it."
```

PowerShell uses the same client without POSIX shell syntax:

```powershell
$Client = "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py"
$Repository = "C:\absolute\repository\path"
py -3 $Client doctor
py -3 $Client start
$SessionId = py -3 $Client create --cwd $Repository --permission read-only
py -3 $Client run $SessionId "Read README.md and summarize the project. Do not modify files."
```

Windows Command Prompt can invoke the client directly as well. Keep the
session ID printed by `create` and pass it to the next command:

```bat
py -3 "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py" doctor
py -3 "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py" start
py -3 "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py" create --cwd "C:\absolute\repository\path" --permission read-only
py -3 "C:\absolute\plugin\path\skills\dsh-web\scripts\dsh_client.py" run <session-id> "Read README.md and summarize the project. Do not modify files."
```

### Client commands

| Command | Purpose |
| --- | --- |
| `doctor` | Report Python, DSH, npm, and server readiness without installing anything |
| `health` | Check whether DSH Web is reachable |
| `start` | Reuse or start a detached local loopback DSH Web service and report its runtime and log paths |
| `create` | Create a session rooted at a required explicit target directory and enforce `--permission` (default `workspace-write`) |
| `permission` | Inspect or automatically switch and verify an existing session's permission preset |
| `rename` | Pin a stable, unique title for exact browser selection |
| `ui-target` | Print the base UI URL and projected title for a session |
| `run` | Lock the session, reject an already-running session, send a prompt, and wait for its correlated turn |
| `dispatch` | Send a prompt and print its RPC ID plus the pre-prompt history cursor for UI-first waiting |
| `prompt` | Send a prompt without waiting |
| `wait` | Wait for a later or explicitly correlated `turn/end`; cursor flags and `--rpc-id` resume a `dispatch` receipt |
| `history` | Print raw history or a compact transcript |
| `list` | List DSH sessions |
| `cancel` | Cancel a session |
| `open` | Open DSH Web in the platform default browser as a fallback |

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DSH_URL` | `http://127.0.0.1:8765` | DSH Web base URL |
| `DSH_HTTP_TIMEOUT` | `30` | Timeout for each HTTP request in seconds |
| `DSH_TIMEOUT` | `600` | Timeout while waiting for a turn in seconds |
| `DSH_POLL_INTERVAL` | `2` | History polling interval in seconds |
| `DSH_STARTUP_TIMEOUT` | `20` | Timeout while starting a local DSH Web service in seconds |
| `DSH_HOME` | `~/.dsh` | DSH state root; the managed Web runtime is below `runtime/codex-dsh-web/<port>` |

## Validate a development version

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/dsh-web/scripts/dsh_client.py
python3 /path/to/skill-creator/scripts/quick_validate.py skills/dsh-web
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

An end-to-end test calls a real model and may incur API charges:

```text
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py start
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py create --cwd /absolute/repository/path --permission read-only
python3 /absolute/plugin/path/skills/dsh-web/scripts/dsh_client.py run <session-id> "Read README.md and reply with only the project name. Do not modify files."
```

The test succeeds when the command returns a DSH answer and the browser's DSH
sidebar has selected that session title, with its conversation and trace visible.
The URL itself remains `http://127.0.0.1:8765/`.

### Session concurrency

`run` uses a cross-process local lock per `DSH_URL` and `sessionId`, checks
`session.list` for an already-running session, and correlates the prompt RPC ID
with the resulting DSH turn. Use one session sequentially and create separate
sessions for parallel work. Manual prompts entered in the DSH UI or sent by
another client are outside the local lock and can still race, so they should use
a different session while Codex is running a task.

## Update the installation

Refresh the GitHub marketplace snapshot, reinstall the plugin, and start a new Codex task:

```bash
codex plugin marketplace upgrade codex-dsh-web
codex plugin add codex-dsh-web@codex-dsh-web
```

## Troubleshooting

### `health` reports connection refused

```bash
python3 skills/dsh-web/scripts/dsh_client.py doctor
python3 skills/dsh-web/scripts/dsh_client.py start
```

`start` prints the platform-specific log path when startup fails.

### An existing DSH service was started from a project directory

The client intentionally reuses a healthy service and cannot change that
process's working directory in place. Confirm that no DSH session is running,
stop the existing service, and run `start` once. The replacement process uses
the managed runtime directory and future sessions continue to receive their
repository through `create --cwd`.

### Python or DSH is missing

Use Python 3.9 or later. Try `python3 --version` or `python --version` on macOS
and Linux, and `py -3 --version` on Windows. Install Python only after the user
approves use of the platform installer.

If `doctor` reports that DSH is missing, install Node.js/npm first when needed,
then run `npm install --global @deepseek-ai/dsh`. The skill must ask before
running either installation.

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
- DSH write access is governed by the permission preset automatically selected and verified by the client, plus the surrounding Codex environment.

See the [OpenAI plugin documentation](https://developers.openai.com/plugins/build/plugins) for additional local marketplace and plugin packaging guidance.
