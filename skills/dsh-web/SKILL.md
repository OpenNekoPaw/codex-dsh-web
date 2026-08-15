---
name: dsh-web
description: Drive a local DSH Web server from Codex through its HTTP API, including starting or checking the server, opening its UI in the Codex Desktop browser, creating and reusing sessions, sending prompts, waiting for completed turns, reviewing history, verifying code changes, and returning validation feedback to the same session. Use when the user asks Codex to open, call, delegate to, collaborate with, converse with, or execute work through dsh web or DeepSeek Harness web, especially for iterative implementation and test-fix loops with browser-visible traces.
---

# DSH Web

Use the bundled client to keep JSON envelopes, error handling, and turn polling deterministic. Keep Codex responsible for inspecting the resulting files and running relevant validation; DSH Web is a collaborator, not the source of truth.

## Locate the client

Use the absolute client path from this skill directory. Do not assume the
caller's repository contains a copy of the script.

Before invoking it, choose a Python 3.9-or-later launcher:

- On macOS or Linux, try `python3`, then `python`.
- On Windows, try `py -3`, then `python`, then `python3`.
- Run the candidate with `--version` and reject Python older than 3.9.
- If no supported interpreter exists, tell the user that Python 3.9+ is a
  required external dependency and ask before running any platform package
  manager or installer. Do not install Python silently.

In the examples below, replace `<python>` with the selected launcher and
`<client>` with `<skill-directory>/scripts/dsh_client.py`. Keep `py -3` as two
arguments rather than one quoted executable name.

## Run the collaboration loop

1. Check the local server:

   ```text
   <python> <client> health
   ```

   If the command reports connection refused, run the dependency report:

   ```text
   <python> <client> doctor
   ```

   When `doctor` reports that `dsh` is missing, explain that DeepSeek Harness is
   an external dependency. Show its reported install command
   (`npm install --global @deepseek-ai/dsh`). If npm is also missing, explain
   that Node.js and npm must be installed first. Ask the user before running
   either installer; do not infer authorization from invoking this skill.

   If the dependencies are available and running a local service is within the
   user's request, start it through the cross-platform client:

   ```text
   <python> <client> start
   ```

   `start` reuses an already healthy service, starts only an `http` loopback
   `DSH_URL`, waits for readiness, and reports the platform temporary-directory
   log path. Do not start a second process after an HTTP, trust-fence, or timeout
   error; diagnose that error instead.

   Treat invoking the plugin without an implementation task as a request to open
   the DSH UI and confirm health. In Codex Desktop, use the in-app Browser control
   surface to open `DSH_URL` and place it beside the task.
   Do not satisfy this request by only printing the URL, returning a Markdown
   link, or rendering a website preview card. The UI is considered opened only
   when Codex has requested an actual Browser/WebView panel.

   If the Codex app browser-panel action is unavailable, use `<python> <client>
   open` as the platform default-browser fallback and state that the fallback
   was used. Opening the page is for visualization; continue to use the HTTP API
   for deterministic prompting and history reads. Use browser control only when
   the user asks Codex to inspect or interact with the visible UI.

2. Create one session rooted at the target repository:

   ```text
   <python> <client> create --cwd <absolute-repository-path>
   ```

   Capture the printed session ID and reuse it for the complete task.

   Immediately give the session a stable, unique UI title. Use a concise task
   description plus a short suffix from the session ID, for example:

   ```text
   <python> <client> rename <session-id> "Codex: fix login tests [a65d-ed81]"
   ```

   Keep the accepted title printed by `rename`. The explicit rename pins the
   title so DSH's automatic title generation cannot make browser selection
   ambiguous.

3. When no live UI synchronization is requested, send the task and wait
   atomically for the new turn:

   ```text
   <python> <client> run <session-id> "<specific task and constraints>"
   ```

   Prefer `run` over separate `prompt` and `wait` calls. It snapshots existing history before prompting, so an immediately completed turn cannot be mistaken for an older one. Preserve `SESSION_ID` for the whole loop.

   `run` serializes local callers for the same session, rejects a session that
   DSH reports as running, and correlates the prompt RPC ID with its turn. Use one
   session sequentially; create a separate session for parallel work.

   When the user wants the built-in DSH UI to show the active session while it is
   working, split the same correlated operation into dispatch, selection, and
   wait:

   ```text
   <python> <client> dispatch <session-id> "<specific task and constraints>"
   <python> <client> ui-target <session-id>
   ```

   Capture `rpcId`, `afterCount`, and optional `afterSeq` from `dispatch`, plus
   `url` and `title` from `ui-target`. Then use the Codex in-app Browser:

   - Reuse or open a tab at the returned `url`.
   - Locate the session-search textbox by its accessible label (for example,
     `Search sessions...` or `搜索会话...`) and fill the returned exact title.
   - Wait for a session `treeitem` containing that title, click it, and verify
     that the item has `aria-selected="true"` and the conversation header or
     breadcrumb contains the same title.
   - Do not report the active session as visible when the tab only shows the New
     Session entry page, workspace chooser, or root composer.

   DSH Web 0.1.0-rc.6 keeps session selection in client-side state and leaves the
   URL at `/`; do not invent or navigate to a `/session/<id>` route. If the title
   is not visible immediately, keep the browser tab open and wait briefly for the
   session list update instead of opening another DSH server.

   After the correct session is selected, wait for the dispatched turn without
   losing an immediately completed result:

   ```text
   <python> <client> wait <session-id> --after-count <afterCount> [--after-seq <afterSeq>] --rpc-id <rpcId>
   ```

   Omit `--after-seq` when `dispatch` prints `null`. If in-app Browser control is
   unavailable, use the default-browser fallback, report the exact session title
   for manual selection, and state that automatic session switching was not
   available.

4. Inspect the workspace changes and independently run the narrowest relevant tests, lint, or build. Do not accept an `assistant/message` as proof that work succeeded.

5. If validation fails or more work is needed, send a concise result back to the same session:

   ```text
   <python> <client> run <session-id> "验证结果：<command and relevant failure>. 请继续修复。"
   ```

6. Repeat inspection and validation until the requested result is complete. Report the DSH contribution and Codex's actual verification separately.

## Use lower-level commands

Use these only when the combined loop is unsuitable:

- `doctor` reports Python, DSH, npm, and server readiness without installing anything.
- `start` starts one local loopback DSH Web service when `health` reports connection refused.
- `prompt <session-id> <text>` queues a prompt without waiting.
- `rename <session-id> <title>` pins a stable title for exact UI selection.
- `ui-target <session-id>` prints the base URL and title used to find the session
  in the DSH sidebar; DSH does not expose a per-session URL.
- `dispatch <session-id> <text>` queues a prompt and prints a correlation receipt
  so Codex can select the UI session before waiting.
- `wait <session-id>` snapshots current history and waits only for a later
  `turn/end`. Use `--after-seq` and/or `--after-count` to resume from an explicit
  cursor, and `--rpc-id` to wait for the turn created by `dispatch`.
- `history <session-id>` prints raw history; add `--messages` for a compact transcript.
- `list` prints known sessions and state.
- `cancel <session-id>` requests cancellation.
- `open` opens the browser UI in the platform default browser only when the user explicitly asks and the Codex Browser/WebView action is unavailable.

Set `DSH_URL` to override `http://127.0.0.1:8765`, `DSH_HTTP_TIMEOUT` for each HTTP request, `DSH_TIMEOUT` for turn waiting, `DSH_POLL_INTERVAL` for polling, and `DSH_STARTUP_TIMEOUT` for local service startup. Pass global flags before the subcommand when preferred.

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
