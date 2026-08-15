# Codex DSH Web plugin

This local Codex plugin lets Codex drive DSH Web through its HTTP API while the browser shows the same session's conversation, tool calls, and trace.

The `dsh-web` skill provides a dependency-free client and an iterative workflow:

1. Create a DSH Web session for a repository.
2. Send work to DSH and wait for the new turn to finish.
3. Let Codex inspect and test the changes.
4. Return validation feedback to the same session and repeat.

## Prerequisites

- `dsh` installed with the `web` profile available.
- A configured DeepSeek API key, either in DSH Web's Models page or the inherited shell environment.
- Codex network access to loopback and write access to the target repository and `DSH_HOME` (normally `~/.dsh`).

Start DSH Web on the default port:

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
open http://127.0.0.1:8765
```

## Development installation

This repository is a plugin source. Place or copy it inside a local marketplace root, then point the marketplace entry at that in-root copy. For example, if the copy is at `<marketplace-root>/plugins/codex-dsh-skill`, use this entry in `<marketplace-root>/.agents/plugins/marketplace.json`:

```json
{
  "name": "local-dsh",
  "interface": {"displayName": "Local DSH"},
  "plugins": [
    {
      "name": "codex-dsh-skill",
      "source": {
        "source": "local",
        "path": "./plugins/codex-dsh-skill"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

Register and install it:

```bash
codex plugin marketplace add <marketplace-root>
codex plugin add codex-dsh-skill@local-dsh
```

Start a new Codex task after installation so the bundled skill is discovered. See OpenAI's [plugin packaging documentation](https://developers.openai.com/plugins/build/plugins) for personal and repository marketplace options.

For source-level testing, invoke the client directly:

```bash
CLIENT="skills/dsh-web/scripts/dsh_client.py"
python3 "$CLIENT" health
SID="$(python3 "$CLIENT" create --cwd "$PWD")"
python3 "$CLIENT" run "$SID" "请检查当前项目并修复失败的测试"
```

Run `python3 skills/dsh-web/scripts/dsh_client.py --help` for all commands and environment overrides.

## Validation

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py skills/dsh-web
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
python3 -m unittest discover -s tests -v
```
