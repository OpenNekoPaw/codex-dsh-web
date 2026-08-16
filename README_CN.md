# DSH Web for Codex

[English](README.md) | 简体中文

`codex-dsh-web` 是一个轻量的 Codex 插件，用于把开发任务委派给本地 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) Web 会话。

Codex 通过 DSH Web 本地 API 发送任务，默认在内置 Browser 侧栏中打开准确的活动会话，随后由 Codex 自己检查文件并运行验证。

![Codex 与 DSH Web 并排协作](docs/assets/codex-dsh-web-demo.png)

## 功能

- 多个独立 session 复用一个本地 DSH Web 服务。
- 为目标仓库创建或继续已有 session，并把新 session 登记到该仓库的 DSH 工作区。
- 自动选择并验证 DSH 权限。
- 发送任务并等待匹配的回答。
- 每个 Codex 任务最多复用一个 DSH Browser 标签，并在其中切换多个 DSH session。
- 最后一个 DSH UI 操作完成、超时或失败后自动释放共享标签。
- 由 Codex 负责审查改动和运行测试。

插件不会让 Codex 对每个请求都调用 DSH。只有用户提到 DSH Web、DeepSeek Harness Web，或显式使用 `$dsh-web` 时才会触发。

## 前置条件

- 支持插件的 Codex。
- Python 3.9 或更高版本。
- Node.js/npm 和 DeepSeek Harness：

```bash
npm install --global @deepseek-ai/dsh
dsh --version
```

- 已为 DSH Web 配置模型和 API Key。

Python 客户端仅使用标准库，支持 macOS、Linux 和 Windows，不依赖 `zsh` 或其他登录 shell。

安装插件不会静默安装 Python、Node.js、npm 或 DSH。缺少依赖时，Codex 会报告问题，并在运行安装器之前征求同意。

## 安装

将 GitHub 仓库添加为 Codex 插件 marketplace，然后安装插件：

```bash
codex plugin marketplace add OpenNekoPaw/codex-dsh-web --ref main
codex plugin add codex-dsh-web@codex-dsh-web
```

确认安装结果：

```bash
codex plugin marketplace list
codex plugin list
```

安装或更新后请新建 Codex 任务，使 skill 被重新加载。

## 使用

显式调用最可靠：

```text
使用 $dsh-web 修复失败测试，然后由 Codex 检查改动并运行测试。
```

也可以使用自然语言：

```text
让 DSH Web 只读评审当前仓库。
```

DSH 执行轨迹默认打开，无需额外说明 UI：

```text
使用 $dsh-web 实现这个功能。
```

Codex 会先派发任务，再复用当前 Codex 任务在 Browser 侧栏中的 DSH Web 标签，按唯一标题选择 session，验证可见会话，然后等待结果。同一 Codex 任务中的多个 DSH session 会在这个标签内切换，不再持续新增标签。

创建新 session 时，客户端会先按仓库的规范化路径幂等创建或解析 DSH 工作区，再用该工作区 ID 创建 session，并校验归属关系。这样新 session 会保存在对应仓库分组中，不再落入“未分组”。

UI 所有权以 `CODEX_THREAD_ID` 或 `CODEX_SESSION_ID` 为键，不以 DSH 服务地址或 DSH session ID 为键。客户端默认等待 DSH turn 最多 1 小时，最多允许 10 个并发 Codex UI owner，并按 5 小时 TTL 清理遗留 activity。最后一个 activity 会通知 Codex 关闭共享标签；关闭 UI 不会取消 DSH session。

插件不得使用 Computer Use 画中画、外部浏览器或 headless 回退承载该界面。如果内置 Browser 侧栏不可用，Codex 会先释放 UI 所有权并报告限制，而不是静默切换界面类型。

默认界面地址为 `http://localhost:8765`。Browser URL 必须保留 `localhost`；部分 Codex 内置 Browser 环境访问等价的 `127.0.0.1` 时会卡住。托管的 DSH 进程仍只绑定 IPv4 回环地址。

如果项目希望始终优先委派给 DSH，可以在 `AGENTS.md` 添加简短规则：

```markdown
实现或评审任务优先使用 `$dsh-web`，完成后由 Codex 独立检查并验证结果。
```

## 权限策略

用户无需手动配置 DSH 权限。Codex 根据任务意图设置 session 的有效权限：

| 任务意图 | DSH 权限 |
| --- | --- |
| 评审、分析、诊断、规划 | `read-only` |
| 实现、修复、重构、测试 | `workspace-write` |
| 明确要求在工作区外操作 | `danger-full-access` |

客户端通过 DSH 设置权限，并在发送 prompt 前验证实际生效值。模型和 agent preset 仍由 DSH 配置管理。

## 更新或卸载

刷新 marketplace 并重新安装当前版本：

```bash
codex plugin marketplace upgrade codex-dsh-web
codex plugin add codex-dsh-web@codex-dsh-web
```

卸载本地插件：

```bash
codex plugin remove codex-dsh-web
```

## 常见问题

### 未安装 DSH

通过 Codex 或直接运行内置诊断：

```bash
python3 /插件路径/skills/dsh-web/scripts/dsh_client.py doctor
```

诊断会报告 Python、npm、DSH 和服务状态，并给出 DSH 安装命令。

### Browser 展示旧 session

skill 会先派发任务，再按返回的准确标题选择会话，而不是依赖根页面保存的旧状态。如果仍显示旧 session，应将其视为会话切换失败。

如果 DSH 出现在 Computer Use 画中画中，说明选择了错误的浏览器界面。请在更新插件后新建任务；新版 skill 强制使用内置 Browser 侧栏并禁止该回退。

如果 Browser 一直停留在加载状态，请确认地址使用 `localhost`，而不是 `127.0.0.1`。

### DSH Browser 标签过多

更新后的任务会复用带有自身 `codexThreadId` 查询参数的标签，并关闭同一 owner 下的重复标签。只要当前任务还有 DSH UI activity，临时标签就会保留；最后一次 `wait` 或兜底 `release` 后再关闭，任务中断结束时 Browser 也可以自动回收。旧插件版本遗留的标签需要一次性手动关闭或重启 Codex。

### session 已在运行

等待该 session 完成，或使用新 session。客户端会阻止两个本地调用者同时把同一个 DSH session 当作自己的活动任务。

## 开发

客户端的正常使用界面有意保持为五个命令：

```text
doctor
task
wait
release
debug
```

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

直接调用方式和低层诊断见[客户端参考](skills/dsh-web/references/api.md)。
