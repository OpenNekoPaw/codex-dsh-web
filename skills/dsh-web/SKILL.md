---
name: dsh-web
description: Delegate a development task to a local DSH Web session, always open and select the exact active session in the Codex in-app Browser side panel, then let Codex inspect and verify the result. Never use Computer Use picture-in-picture for the DSH UI. Use when the user asks to use, open, call, or collaborate with DSH Web or DeepSeek Harness Web.
---

# DSH Web

Use the bundled Python client. It owns server startup, session creation, permissions, stable titles, prompting, correlated waiting, and logical UI ownership. Always show the exact task session in one shared Codex in-app Browser tab. Codex remains responsible for inspecting files and running validation.

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
2. Creates or reuses the DSH workspace for the requested repository and attaches the new session to it, so the session is not left ungrouped.
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

Use UI mode for every delegated task, even when the user does not separately ask to see the interface. Always pass `--ui`; do not use `--no-ui` in this skill and never fall back to a headless browser or external browser.

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
- `ui.ownerId`: the current Codex task ID from `CODEX_THREAD_ID` or `CODEX_SESSION_ID`.
- `ui.reuse`: whether that Codex task already has registered DSH UI activity.
- `receipt`: an opaque value used by `wait`.

Immediately use the available in-app Browser control skill and explicitly select the in-app Browser surface. Do not let URL-based browser selection choose another surface. Do not merely print the URL or return a link.

Open `ui.url` exactly as returned. The default is `http://localhost:8765`; never rewrite `localhost` to `127.0.0.1`, because the in-app Browser can stall on the numeric loopback address.

## Reuse one task-owned tab

Treat `ui.ownerId`, not the DSH service URL or DSH session ID, as the UI owner. One Codex task may own at most one live DSH tab, and that tab may switch among multiple DSH sessions.

The client waits up to one hour for a DSH turn by default. The registry defaults to 10 concurrent Codex UI owners and a five-hour activity TTL. `DSH_TIMEOUT`, `DSH_UI_LIMIT`, and `DSH_UI_ACTIVITY_TTL` may override those values.

Before opening a tab:

1. Reuse the live DSH tab binding already held for `ui.ownerId` when available.
2. Otherwise inspect this task's in-app Browser tabs and recover the one whose URL contains the returned `codexThreadId=<ui.ownerId>` query value.
3. If more than one matching tab exists for the same owner, keep one and close the duplicates with the Browser's documented tab-close operation.
4. Create a tab only when no live matching tab exists, regardless of the value of `ui.reuse`.
5. Never close or reuse a DSH tab whose `codexThreadId` belongs to another Codex task.

Navigate the retained tab to `ui.url` when its current address differs. A later DSH task or session in the same Codex task must switch this tab instead of creating another one.

Keep the DSH tab temporary. Do not mark it deliverable or handoff unless the user explicitly asks to keep that UI open. This lets the Browser reclaim an agent-created tab automatically if the Codex turn ends or is interrupted before explicit cleanup.

DSH Web stores the selected session in frontend state, so opening the root URL may show an old session. Reveal the session list or search, select the exact `ui.title`, and verify that both the selected item and visible conversation title match. Do not continue while an old session or the new-session page is selected.

Never use Computer Use, `@Computer`, an external browser, a headless browser, or picture-in-picture to open or control the DSH UI. If the in-app Browser skill or side panel is unavailable after dispatch, run the fallback `release` cleanup, report that exact limitation, and do not substitute another surface or claim that the UI was opened.

Only after the exact session is visibly selected, wait for the result:

```text
<python> <client> wait <receipt>
```

Do not decode or edit the receipt. Read the JSON printed by `wait` even when the command exits nonzero. It always releases that activity and reports `ui.close` for current receipts:

- If `ui.close` is `false`, other DSH activities in this Codex task still need the shared tab; keep it open.
- If `ui.close` is `true`, close the retained DSH tab. Closing the tab must not cancel or delete any DSH session.

Run the task, Browser selection, and wait inside a cleanup-aware flow. If `wait` was not reached or did not return a cleanup result because UI setup or orchestration failed, run:

```text
<python> <client> release <receipt>
```

Then apply its `ui.close` result using the same rule. `release` is idempotent, does not wait for the DSH turn, and does not cancel the DSH session. Use it only as the fallback cleanup path; normal completion and timeout cleanup belong to `wait`.

If the user only asks to open DSH Web without delegating a task, run `doctor`. If the server is not reachable but DSH is installed, run `debug start`, then open the reported URL in the in-app Browser side panel under the same single-tab and no-Computer-Use rules.

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
