---
name: dsh-web
description: Delegate a development task to a local DSH Web session, optionally show the exact active session in Codex Desktop, then let Codex inspect and verify the result. Use when the user asks to use, open, call, or collaborate with DSH Web or DeepSeek Harness Web.
---

# DSH Web

Use the bundled Python client. It owns server startup, session creation, permissions, stable titles, prompting, and correlated waiting. Codex remains responsible for inspecting files and running validation.

## Locate the client

Resolve `scripts/dsh_client.py` relative to this skill directory and invoke it by absolute path.

Use Python 3.9 or later:

- macOS/Linux: prefer `python3`, then `python`.
- Windows: prefer `py -3`, then `python`.
- If Python is missing or too old, explain the requirement and ask before installing anything.

The client is cross-platform and does not depend on `zsh`, `bash`, or shell scripts. Run it from an existing directory and pass the target repository as an absolute `--cwd`.

## Run a task

Choose the intent without asking the user to configure DSH permissions:

- `read`: inspection, explanation, review, diagnosis, or planning.
- `write`: implementation, fixes, refactors, formatting, or tests that may write files.
- `full-access`: only when the user explicitly requests work requiring writes outside the repository and normal temporary paths.

For a new session:

```text
<python> <client> task \
  --cwd <absolute-repository-path> \
  --intent <read|write|full-access> \
  --prompt "<specific task and constraints>"
```

The client automatically:

1. Reuses a healthy DSH Web service or starts one after connection refusal.
2. Creates the session in the requested repository.
3. Maps intent to and verifies the effective DSH permission.
4. Assigns a unique visible title.
5. Sends the prompt and waits for the correlated answer.

The result is one JSON object. Keep its `sessionId` for follow-up work.

To continue the same session:

```text
<python> <client> task \
  --session <session-id> \
  --intent <read|write|full-access> \
  --prompt "<follow-up task or validation feedback>"
```

Use one session sequentially. Create separate sessions for genuinely parallel work.

## Show the active session

When the user asks to see DSH Web in Codex Desktop, add `--ui`:

```text
<python> <client> task \
  --cwd <absolute-repository-path> \
  --intent write \
  --prompt "<task>" \
  --ui
```

A dispatched result contains:

- `ui.url`: the DSH Web address.
- `ui.title`: the exact session title.
- `receipt`: an opaque value used by `wait`.

Use the Codex in-app Browser control to open `ui.url`. DSH Web stores the selected session in frontend state, so opening the root URL may show an old session. Reveal the session list or search, select the exact `ui.title`, and verify that both the selected item and visible conversation title match.

Use Computer Use only when normal Browser control is unavailable or cannot operate the page after a retry.

After selecting the session, wait for the result:

```text
<python> <client> wait <receipt>
```

Do not decode or edit the receipt.

If the user only asks to open DSH Web without delegating a task, run `doctor`. If the server is not reachable but DSH is installed, run `debug start`, then open the reported URL in the in-app Browser.

## Verify independently

After DSH completes:

1. Inspect the relevant files and diff.
2. Run tests, lint, build, or focused checks appropriate to the task.
3. Do not attribute unrelated repository changes to the current DSH session.
4. If validation fails because of DSH's work, send the concise failure back with another `task --session ...` call.
5. Stop only when the requested outcome is verified or a real blocker is reported.

A DSH answer is evidence, not verification. Prefer file contents, version-control state, and command results.

## Dependencies and failures

Run:

```text
<python> <client> doctor
```

The report distinguishes Python, npm, DSH, and server readiness. DSH is an external dependency installed with:

```text
npm install --global @deepseek-ai/dsh
```

Never install Python, Node.js, npm, or DSH without user approval.

Use `debug` only for troubleshooting. Its low-level commands are documented in [references/api.md](references/api.md); they are not part of the normal collaboration flow.
