# DSH Web for Codex

[English](README.md) | 简体中文

`codex-dsh-web` 是一个本地 Codex 插件，让 Codex 通过 DSH Web HTTP API 与 DeepSeek Harness 协作。

Codex 可以创建或复用 DSH session、发送开发任务、等待 DSH 完成，并在本地检查代码与运行测试。若验证失败，Codex 会把结果发回同一个 session，形成持续的开发—验证循环。浏览器中的 DSH Web 同时展示会话、工具调用和执行轨迹。

## 工作方式

```text
Codex
  │
  ├─ POST /api/session.create ── 创建独立 session
  ├─ POST /api/session.prompt ── 发送任务或验证结果
  ├─ POST /api/session.history ─ 等待 turn/end 并读取回答
  │
  └─ 本地检查 diff、运行 test/lint/build
                    │
                    ▼
          DSH Web http://127.0.0.1:8765
          ├─ 本地 HTTP API
          └─ 浏览器可视化界面
```

一个 DSH Web 进程可以同时承载多个独立 session。不同 Codex 任务默认创建不同的 `sessionId`，不会为每个会话启动一个新 DSH 服务进程。

## 目录结构

```text
codex-dsh-web/
├── .codex-plugin/plugin.json
├── skills/dsh-web/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/api.md
│   └── scripts/dsh_client.py
└── tests/test_dsh_client.py
```

插件 ID 是 `codex-dsh-web`，用户界面显示为 **DSH Web for Codex**，skill 名称是 `$dsh-web`。

## 前置条件

- 已安装 `dsh`，并且 `dsh --profile web --help` 可运行。
- 已在 DSH Web Models 页面或环境变量中配置 DeepSeek API Key。
- Codex 允许访问本机回环网络，并能写入目标仓库和 `DSH_HOME`（通常是 `~/.dsh`）。
- Python 3.10 或更高版本；客户端仅使用标准库。

启动 DSH Web：

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
open http://127.0.0.1:8765
```

## 个人安装

个人 marketplace 默认位于 `~/.agents/plugins/marketplace.json`，插件源码通常放在 `~/plugins/`：

```bash
git clone https://github.com/OpenNekoPaw/codex-dsh-web.git \
  "$HOME/plugins/codex-dsh-web"
mkdir -p "$HOME/.agents/plugins"
```

创建或合并以下 marketplace 配置：

```json
{
  "name": "personal",
  "interface": {"displayName": "Personal"},
  "plugins": [
    {
      "name": "codex-dsh-web",
      "source": {"source": "local", "path": "./plugins/codex-dsh-web"},
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

默认个人 marketplace 会被 Codex 自动发现，不需要运行 `codex plugin marketplace add`。重启 ChatGPT/Codex 桌面应用，在 **Plugins → Personal** 安装插件，或使用 CLI：

```bash
codex plugin add codex-dsh-web@personal
```

安装后创建一个新的 Codex 任务，已打开的旧任务不会自动加载新 skill。

## 使用

最可靠的调用方式是显式指定 skill：

```text
使用 $dsh-web，让 DSH 修复失败测试，Codex 检查改动并运行测试验证。
```

也可以自然表达：

```text
让 dsh web 实现这个功能，完成后由 Codex 独立验证。
```

skill 的描述允许隐式触发，但 Codex 不会仅因为端口 `8765` 已启动就主动扫描或调用 DSH。对于没有提到 DSH 的普通开发请求，默认不会使用该插件。若项目希望所有开发任务优先委派给 DSH，可在项目 `AGENTS.md` 中声明：

```markdown
涉及代码实现、修复或测试时，优先使用 `$dsh-web` 委派给 DSH Web，
然后由 Codex 独立检查改动并运行验证。
```

## 直接使用客户端

无需安装插件也可以验证 HTTP 客户端：

```bash
CLIENT="$PWD/skills/dsh-web/scripts/dsh_client.py"

python3 "$CLIENT" health
SESSION_ID="$(python3 "$CLIENT" create --cwd "$PWD")"
python3 "$CLIENT" run "$SESSION_ID" "读取 README.md 并概括项目，不要修改文件"
python3 "$CLIENT" history "$SESSION_ID" --messages
```

继续同一个会话：

```bash
python3 "$CLIENT" run "$SESSION_ID" \
  "验证结果：测试仍有一个失败，相关错误如下：<error>。请继续修复。"
```

### 客户端命令

| 命令 | 用途 |
| --- | --- |
| `health` | 检查 DSH Web 是否可访问 |
| `create` | 为目标目录创建 session |
| `run` | 发送消息并等待新一轮完成 |
| `prompt` | 只发送消息，不等待 |
| `wait` | 等待后续 `turn/end` |
| `history` | 输出原始历史或精简消息 |
| `list` | 列出 DSH sessions |
| `cancel` | 取消指定 session |
| `open` | 在 macOS 打开 DSH Web 页面 |

### 环境变量

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DSH_URL` | `http://127.0.0.1:8765` | DSH Web 地址 |
| `DSH_HTTP_TIMEOUT` | `30` | 单次 HTTP 请求超时秒数 |
| `DSH_TIMEOUT` | `600` | 等待一轮完成的超时秒数 |
| `DSH_POLL_INTERVAL` | `2` | 历史轮询间隔秒数 |

## 验证开发版本

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/dsh-web/scripts/dsh_client.py
python3 /path/to/skill-creator/scripts/quick_validate.py skills/dsh-web
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

端到端验证会调用真实模型，可能产生 API 费用：

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
CLIENT="$PWD/skills/dsh-web/scripts/dsh_client.py"
SESSION_ID="$(python3 "$CLIENT" create --cwd "$PWD")"
python3 "$CLIENT" run "$SESSION_ID" "读取 README.md，只回复项目名称，不修改文件"
```

成功标准：命令返回 DSH 回答，并且浏览器中的 `http://127.0.0.1:8765` 出现相同 session 的对话与轨迹。

## 更新本地安装

Codex 使用 `~/.codex/plugins/cache/` 中的已安装副本，不会直接读取持续变化的源码目录。修改插件后需要更新 cachebuster、重新安装，并新建 Codex 任务：

```bash
python3 /path/to/plugin-creator/scripts/update_plugin_cachebuster.py \
  "$HOME/plugins/codex-dsh-web"
codex plugin add codex-dsh-web@personal
```

## 常见问题

### `health` 提示连接被拒绝

```bash
dsh --profile web --port 8765 > /tmp/dsh-web.log 2>&1 &
tail -n 100 /tmp/dsh-web.log
```

### Codex 找不到 `$dsh-web`

确认插件已安装，然后完全重启桌面应用并新建任务。旧任务不会重新加载新增的 skill。

### Codex 没有自动调用 DSH

使用 `$dsh-web` 显式调用，或者在请求中明确写出“使用 dsh web”。若需要项目级默认行为，在目标仓库的 `AGENTS.md` 中加入协作规则。

### 多个 Codex 任务是否启动多个 DSH

正常情况下不会。skill 先检查同一个 `DSH_URL`；多个任务共享一个 DSH Web 进程，但分别创建 session。只有使用不同端口或不同 `DSH_URL` 时才会运行多个服务实例。

## 安全说明

- 不要把 API Key、密码或完整环境变量发送到 DSH session。
- 反馈测试错误时只发送必要的命令、退出码和相关错误片段。
- DSH 的回复不能替代验证；Codex 应检查实际文件并运行相关测试。
- DSH 对目标仓库的写入能力受其权限配置和 Codex 所在环境约束。

更多本地 marketplace 和插件打包说明参见 [OpenAI 插件文档](https://developers.openai.com/plugins/build/plugins)。
