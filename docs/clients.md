# 客户端适配

[← 返回首页](../README.md) · [English](clients.en.md)

SlideMuse 使用标准 `SKILL.md` 和共用的 Python 工具。安装器负责把完整运行文件放入所选客户端的技能目录，安装隔离依赖并校验；客户端负责发现和调用技能。

## 安装到指定客户端

在克隆出的仓库目录执行下面对应的一条命令：

| 客户端 | 命令 | 用户级安装位置 |
| :--- | :--- | :--- |
| Codex | `python install.py --client codex` | `~/.agents/skills/slidemuse/` |
| Claude Code | `python install.py --client claude` | `~/.claude/skills/slidemuse/` |
| OpenCode | `python install.py --client opencode` | `~/.config/opencode/skills/slidemuse/` |
| WorkBuddy | `python install.py --client workbuddy` | `~/.workbuddy/skills/slidemuse/` |
| Trae 国际版 | `python install.py --client trae` | `~/.trae/skills/slidemuse/` |
| Trae 国内版 | `python install.py --client trae-cn` | `~/.trae-cn/skills/slidemuse/` |
| Qoder IDE / CLI | `python install.py --client qoder` | `~/.qoder/skills/slidemuse/` |
| Qoder 国内版 | `python install.py --client qoder-cn` | `~/.qoder-cn/skills/slidemuse/` |

`~` 是操作系统当前用户目录。国内版和国际版同时存在时，使用表中的明确选项。QoderWork 是另一款产品，本表中的 `qoder` 指 Qoder IDE / CLI。

未指定 `--client` 时，安装器检测客户端配置目录和可用命令：只找到一个就使用它；找到多个会列出名称和可选命令。没有检测到客户端时沿用 Codex 默认值，也可以直接指定尚未启动过的客户端。

先核对路径可运行 `python install.py --client workbuddy --dry-run --json`。`--dry-run` 不安装；`--skip-deps` 只复制运行文件，不代表依赖校验通过。日常安装使用默认选项即可。

## 启用和调用

- **WorkBuddy**：在技能页面的已安装列表中启用 SlideMuse，在新任务中选择它，或明确说“使用 slidemuse 技能”。不同版本的导入方式可查看[官方技能说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。
- **Trae**：在技能设置或技能选择面板中找到 SlideMuse，开启新会话后说“使用 slidemuse 技能”；也可以按[官方导入流程](https://www.trae.ai/blog/trae_tutorial_0115)添加技能包。
- **Qoder**：在新会话输入 `/slidemuse`，或在 `/` 技能列表中选择它。Qoder CLI 已打开时可执行 `/skills reload`；IDE 可重启刷新。参见[IDE 技能](https://docs.qoder.com/extensions/skills)与[CLI 技能](https://docs.qoder.com/cli/Skills)。
- **Codex / Claude Code / OpenCode**：可明确说“使用 slidemuse 技能”；Codex 也支持 `$slidemuse`，Claude Code 支持 `/slidemuse`。

Trae / Qoder 国内版与国际版的目录区分也可参照 [Skills CLI 的客户端注册实现](https://github.com/vercel-labs/skills/blob/main/src/agents.ts)。

## 制作能力和验证

所有客户端使用相同的内容方案、风格选择、图片生成、可编辑还原与交付检查流程。图像生成和编辑由当前客户端的原生工具或已连接服务提供；安装器不会额外配置生图服务。只有 Python 时可以编译、检查和还原已准备好的材料。

安装完成后，在单独的工作目录里运行安装目录下的 `slidemuse.py doctor --json`，并让客户端确认能发现 `slidemuse`。需要完整扩展依赖时，在对应安装命令后添加 `--with-editable --with-generate`。

升级时再次执行同一条安装命令。安装器先在暂存目录复制、安装并校验，再切换新版本；失败会保留或恢复原安装。其他技能目录保持独立。
