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

在 Codex Desktop 中，可以直接把 DSH 页面打开到内置 Browser/WebView 面板。HTTP API 仍是可靠的控制通道；内嵌页面负责展示对话与轨迹，并可在明确要求浏览器控制时供 Codex 检查或操作。

## 目录结构

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

插件 ID 是 `codex-dsh-web`，用户界面显示为 **DSH Web for Codex**，skill 名称是 `$dsh-web`。

## 前置条件

- Python 3.9 或更高版本；客户端仅使用 Python 标准库。
- 已安装 DeepSeek Harness，并且 `dsh --profile web --help` 可运行；对应
  npm 包为 `@deepseek-ai/dsh`。
- 已在 DSH Web Models 页面或环境变量中配置 DeepSeek API Key。
- Codex 允许访问本机回环网络，并能写入目标仓库和 `DSH_HOME`（通常是 `~/.dsh`）。

需要时可手动安装 DSH：

```bash
npm install --global @deepseek-ai/dsh
dsh --version
```

安装插件时不会自动安装 Python、Node.js、npm 或 DSH。首次使用时，skill
先检查 Python 3.9+；只有配置的 DSH Web 服务不可用时才检查本机 DSH。
依赖缺失时会说明原因，并在执行任何安装器之前征求用户同意。

### 平台支持

无第三方依赖的客户端支持 macOS、Linux 和 Windows。文件锁和后台进程
参数会按平台选择，日志写入操作系统临时目录，外部浏览器回退使用 Python
标准库。Codex Browser/WebView 仍是首选 UI。

插件不依赖 `zsh`、`bash` 或其他登录 shell。Codex 应从明确存在的工作目录
直接运行 Python 客户端，并通过 `create --cwd` 传入目标仓库的绝对路径。任务
保存的旧目录被删除或改名时，进程可能在任何 shell 启动前就返回 `No such
file or directory`；这不能说明 `zsh` 缺失。

文档中的 macOS/Linux 示例使用 `python3`。Windows 请替换为 `py -3`；
如果 `python` 指向 Python 3.9 或更高版本，也可以在任意平台使用。

| 平台 | Python 检查 | 客户端调用 |
| --- | --- | --- |
| macOS / Linux | `python3 --version` | `python3 "/插件绝对路径/skills/dsh-web/scripts/dsh_client.py" <命令>` |
| Windows PowerShell | `py -3 --version` | `py -3 "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py" <命令>` |
| Windows 命令提示符 | `py -3 --version` | `py -3 "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py" <命令>` |

这些只是 Python 启动器的差异，不是三套实现。所有平台运行同一个 Python
客户端，使用相同的子命令和 HTTP API。

## 安装

将本 GitHub 仓库注册为 Codex 插件 marketplace，然后安装插件：

```bash
codex plugin marketplace add OpenNekoPaw/codex-dsh-web --ref main
codex plugin add codex-dsh-web@codex-dsh-web
```

确认安装结果：

```bash
codex plugin marketplace list
codex plugin list
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

若希望在 Codex 任务旁持续显示 DSH 界面，可以直接要求 Codex 打开：

```text
使用 $dsh-web 完成这个任务，并在内置浏览器中打开 DSH Web UI。
```

Codex Desktop 会优先在 Browser/WebView 面板打开 `DSH_URL`。若该界面不可用，客户端的 `open` 命令会回退到当前平台默认浏览器。仅打开页面不能替代通过 API 读取结果；需要 Codex 检查或操作 UI 时应明确提出。

DSH Web 当前把选中的会话保存在前端状态中，切换会话后 URL 仍是 `/`，不存在可直接拼接的会话路由。对于 API 驱动的任务，skill 会先设置唯一标题、派发 prompt，再在 DSH 侧边栏搜索并点击该标题，最后校验会话条目已选中且对话标题一致。仍显示“新会话”输入页不算已经切换到本次调用的 session。

插件的第一条 starter prompt 只执行打开 UI 的动作，因此即使没有附带实现任务，也应直接打开 Browser 面板，而不是追问要修改什么代码。仅显示 URL 链接或网页预览卡片不算已经打开面板。

### DSH session 配置

插件不强制固定的 agent preset、权限策略或模型：

- `minimal` 是开销较低的实用默认值，但不是协议要求。
- 只读分析使用 read-only，实现任务使用 workspace-write。仅在任务明确需要访问工作区以外资源时使用 danger-full-access。
- DSH 模型应按任务质量、延迟和成本选择；客户端复用 session 已配置的模型，不硬编码具体模型。

当前 HTTP 客户端创建 session 时只设置工作目录。若默认配置不合适，应先在 DSH Web 中调整 preset、权限或模型，再发送任务。

## 直接使用客户端

无需安装插件也可以验证 HTTP 客户端：

```text
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py doctor
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py start
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py health
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py create --cwd /仓库绝对路径
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py run <session-id> "读取 README.md 并概括项目，不要修改文件"
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py history <session-id> --messages
```

继续同一个会话：

```text
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py run <session-id> "验证结果：测试仍有一个失败，相关错误如下：<error>。请继续修复。"
```

PowerShell 使用相同客户端，无需 POSIX shell 语法：

```powershell
$Client = "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py"
$Repository = "C:\仓库绝对路径"
py -3 $Client doctor
py -3 $Client start
$SessionId = py -3 $Client create --cwd $Repository
py -3 $Client run $SessionId "读取 README.md 并概括项目，不要修改文件"
```

Windows 命令提示符也可以直接调用客户端。保留 `create` 输出的 session ID，
并传给下一条命令：

```bat
py -3 "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py" doctor
py -3 "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py" start
py -3 "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py" create --cwd "C:\仓库绝对路径"
py -3 "C:\插件绝对路径\skills\dsh-web\scripts\dsh_client.py" run <session-id> "读取 README.md 并概括项目，不要修改文件"
```

### 客户端命令

| 命令 | 用途 |
| --- | --- |
| `doctor` | 检查 Python、DSH、npm 和服务状态，不执行安装 |
| `health` | 检查 DSH Web 是否可访问 |
| `start` | 复用或后台启动本机 loopback DSH Web，并输出日志路径 |
| `create` | 为目标目录创建 session |
| `rename` | 固定唯一标题，供内置浏览器精确选择 session |
| `ui-target` | 输出 session 对应的基础 UI 地址和投影标题 |
| `run` | 锁定 session、拒绝正在运行的 session、发送消息并等待与本次请求关联的 turn |
| `dispatch` | 发送消息并输出 RPC ID 与发送前历史游标，便于先切换 UI 再等待 |
| `prompt` | 只发送消息，不等待 |
| `wait` | 等待后续或明确关联的 `turn/end`；可用游标参数和 `--rpc-id` 承接 `dispatch` |
| `history` | 输出原始历史或精简消息 |
| `list` | 列出 DSH sessions |
| `cancel` | 取消指定 session |
| `open` | 作为回退方案，在当前平台默认浏览器打开 DSH Web |

### 环境变量

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DSH_URL` | `http://127.0.0.1:8765` | DSH Web 地址 |
| `DSH_HTTP_TIMEOUT` | `30` | 单次 HTTP 请求超时秒数 |
| `DSH_TIMEOUT` | `600` | 等待一轮完成的超时秒数 |
| `DSH_POLL_INTERVAL` | `2` | 历史轮询间隔秒数 |
| `DSH_STARTUP_TIMEOUT` | `20` | 启动本机 DSH Web 的超时秒数 |

## 验证开发版本

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/dsh-web/scripts/dsh_client.py
python3 /path/to/skill-creator/scripts/quick_validate.py skills/dsh-web
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

端到端验证会调用真实模型，可能产生 API 费用：

```text
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py start
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py create --cwd /仓库绝对路径
python3 /插件绝对路径/skills/dsh-web/scripts/dsh_client.py run <session-id> "读取 README.md，只回复项目名称，不修改文件"
```

成功标准：命令返回 DSH 回答，浏览器中的 DSH 侧边栏选中了对应标题，并展示该 session 的对话与轨迹。URL 本身仍保持 `http://127.0.0.1:8765/`。

### Session 并发

`run` 会按 `DSH_URL` 和 `sessionId` 获取跨进程本地锁，通过
`session.list` 检查 session 是否正在运行，并使用 prompt RPC ID 关联对应
的 DSH turn。同一个 session 应串行使用，并行任务应创建不同 session。
在 DSH UI 中手动输入的消息或其他客户端发送的 prompt 不受本地锁保护，
Codex 执行期间应使用不同 session，避免竞争。

## 更新安装

刷新 GitHub marketplace 快照、重新安装插件，然后新建 Codex 任务：

```bash
codex plugin marketplace upgrade codex-dsh-web
codex plugin add codex-dsh-web@codex-dsh-web
```

## 常见问题

### `health` 提示连接被拒绝

```bash
python3 skills/dsh-web/scripts/dsh_client.py doctor
python3 skills/dsh-web/scripts/dsh_client.py start
```

启动失败时，`start` 会输出当前平台对应的日志路径。

### 缺少 Python 或 DSH

需要 Python 3.9 或更高版本。macOS/Linux 可检查 `python3 --version` 或
`python --version`，Windows 可检查 `py -3 --version`。只有用户同意后才可
使用平台安装器安装 Python。

若 `doctor` 提示缺少 DSH，先在需要时安装 Node.js/npm，再执行
`npm install --global @deepseek-ai/dsh`。skill 在执行这些安装前必须先征求同意。

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
