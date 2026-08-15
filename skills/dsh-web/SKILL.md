---
name: dsh-web
description: Drive a local DSH Web server from Codex through its HTTP API, including starting or checking the server, opening its UI in the Codex Desktop browser, creating and reusing sessions, sending prompts, waiting for completed turns, reviewing history, verifying code changes, and returning validation feedback to the same session. Use when the user asks Codex to open, call, delegate to, collaborate with, converse with, or execute work through dsh web or DeepSeek Harness web, especially for iterative implementation and test-fix loops with browser-visible traces.
---

# DSH Web

Use the bundled client to keep JSON envelopes, error handling, and turn polling deterministic. Keep Codex responsible for inspecting the resulting files and running relevant validation; DSH Web is a collaborator, not the source of truth.

## Locate the client

Set the client path from this skill directory before invoking it:

```bash
DSH_CLIENT="<skill-directory>/scripts/dsh_client.py"
```

Do not assume the caller's repository contains a copy of this script. Use the absolute installed skill path supplied by Codex's skill context.

## Run the collaboration loop

1. Check the local server:

   ```bash
   python3 "$DSH_CLIENT" health
   ```

   If unavailable, start it only when running a local service is within the user's request:

   ```bash
   dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
   ```

   Re-run `health`; if startup fails, inspect `/tmp/dsh-web.log`.

   Treat invoking the plugin without an implementation task as a request to open
   the DSH UI and confirm health. In Codex Desktop, use the Codex app action that
   opens a URL in a browser panel, target `DSH_URL`, and place it beside the task.
   Do not satisfy this request by only printing the URL, returning a Markdown
   link, or rendering a website preview card. The UI is considered opened only
   when Codex has requested an actual Browser/WebView panel.

   If the Codex app browser-panel action is unavailable, use
   `python3 "$DSH_CLIENT" open` as the macOS external-browser fallback and state
   that the fallback was used. Opening the page is for visualization; continue
   to use the HTTP API for deterministic prompting and history reads. Use browser
   control only when the user asks Codex to inspect or interact with the visible
   UI.

2. Create one session rooted at the target repository:

   ```bash
   SESSION_ID="$(python3 "$DSH_CLIENT" create --cwd "$PWD")"
   ```

3. Send the task and wait atomically for the new turn:

   ```bash
   python3 "$DSH_CLIENT" run "$SESSION_ID" "<specific task and constraints>"
   ```

   Prefer `run` over separate `prompt` and `wait` calls. It snapshots existing history before prompting, so an immediately completed turn cannot be mistaken for an older one. Preserve `SESSION_ID` for the whole loop.

   `run` serializes local callers for the same session, rejects a session that
   DSH reports as running, and correlates the prompt RPC ID with its turn. Use one
   session sequentially; create a separate session for parallel work.

4. Inspect the workspace changes and independently run the narrowest relevant tests, lint, or build. Do not accept an `assistant/message` as proof that work succeeded.

5. If validation fails or more work is needed, send a concise result back to the same session:

   ```bash
   python3 "$DSH_CLIENT" run "$SESSION_ID" "验证结果：<command and relevant failure>. 请继续修复。"
   ```

6. Repeat inspection and validation until the requested result is complete. Report the DSH contribution and Codex's actual verification separately.

## Use lower-level commands

Use these only when the combined loop is unsuitable:

- `prompt <session-id> <text>` queues a prompt without waiting.
- `wait <session-id>` snapshots current history and waits only for a later
  `turn/end`. Use `--after-seq` and/or `--after-count` to resume from an explicit
  cursor.
- `history <session-id>` prints raw history; add `--messages` for a compact transcript.
- `list` prints known sessions and state.
- `cancel <session-id>` requests cancellation.
- `open` opens the browser UI only when the user explicitly asks.

Set `DSH_URL` to override `http://127.0.0.1:8765`, `DSH_HTTP_TIMEOUT` for each HTTP request, `DSH_TIMEOUT` for turn waiting, and `DSH_POLL_INTERVAL` for polling. Pass global flags before the subcommand when preferred.

Read [references/api.md](references/api.md) when debugging envelopes, response shapes, event parsing, trust-fence failures, or version compatibility.

## Respect session configuration

- Do not require a particular DSH agent preset or model. Reuse the session's
  configured preset and model unless the user asks to change them. The `minimal`
  preset is a sensible low-overhead default, not a protocol requirement.
- Match DSH permissions to the task: use read-only for analysis, workspace-write
  for implementation, and danger-full-access only when the user explicitly needs
  operations outside the workspace boundary.
- The current HTTP client does not set the preset, model, or permission policy.
  Configure those in DSH Web before prompting when the defaults are unsuitable.

## Apply safeguards

- Reuse the same session only for one coherent task and repository.
- Do not send another `run` to a session while it is working. The local lock
  protects bundled-client callers, but manual UI prompts or other clients can
  still race with it.
- Never include secrets, tokens, or unnecessary environment data in prompts or validation logs.
- Avoid sending unbounded command output; include the command, exit code, and relevant tail or error excerpt.
- Treat DSH HTTP errors, RPC errors, error turn endings, and timeouts as failures. Inspect history or the server log before retrying.
- Do not start duplicate servers when `health` already succeeds.
- Do not cancel a running session unless the user asks or cancellation is needed to recover the requested workflow.
