---
name: dsh-web
description: Delegate a development task to a local DSH Web session, always open and select the exact active session in the Codex in-app Browser side panel, then let Codex inspect and verify the result. Never use Computer Use picture-in-picture for the DSH UI. Use when the user asks to use, open, call, or collaborate with DSH Web or DeepSeek Harness Web.
---

# DSH Web

Use the bundled Python client. It owns server startup, session creation, permissions, stable titles, prompting, and correlated waiting. Always show the exact task session in the Codex in-app Browser side panel. Codex remains responsible for inspecting files and running validation.

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
  --prompt "<specific task and constraints>" \
  --ui
```

The client automatically:

1. Reuses a healthy DSH Web service or starts one after connection refusal.
2. Creates the session in the requested repository.
3. Maps intent to and verifies the effective DSH permission.
4. Assigns a unique visible title.
5. Dispatches the prompt and returns the exact UI title plus an opaque wait receipt.

Keep the returned `sessionId` for follow-up work.

To continue the same session:

```text
<python> <client> task \
  --session <session-id> \
  --intent <read|write|full-access> \
  --prompt "<follow-up task or validation feedback>" \
  --ui
```

Use one session sequentially. Create separate sessions for genuinely parallel work.

## Open the exact active session

Use UI-first behavior for every delegated task, even when the user does not separately ask to see the interface. Always pass `--ui`. Use `--no-ui` only when the user explicitly requests no WebView.

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

Immediately use the available in-app Browser control skill to open `ui.url` in Codex's side-panel WebView. Explicitly select the in-app Browser surface; do not let URL-based browser selection choose another surface. Do not merely print the URL or return a link.

Open `ui.url` exactly as returned. The default is `http://localhost:8765`; never rewrite `localhost` to `127.0.0.1`, because the in-app Browser can stall on the numeric loopback address.

DSH Web stores the selected session in frontend state, so opening the root URL may show an old session. Reveal the session list or search, select the exact `ui.title`, and verify that both the selected item and visible conversation title match. Do not continue while an old session or the new-session page is selected.

Never use Computer Use, `@Computer`, an external browser, or picture-in-picture to open or control the DSH UI. If the in-app Browser skill or side panel is unavailable, report that exact limitation instead of substituting another surface. API prompting and result collection may continue, but do not claim that the UI was opened.

Only after the exact session is visibly selected, wait for the result:

```text
<python> <client> wait <receipt>
```

Do not decode or edit the receipt.

If the user only asks to open DSH Web without delegating a task, run `doctor`. If the server is not reachable but DSH is installed, run `debug start`, then open the reported URL in the in-app Browser side panel under the same no-Computer-Use rule.

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
