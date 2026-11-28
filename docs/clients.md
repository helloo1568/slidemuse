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

升级时先下载并解压所需的新版本，再从新源码目录执行同一条安装命令。安装器复制的是自身目录中的源码，不会先从 GitHub 拉取新版；从旧下载目录重装仍是旧版。它先在暂存目录复制、安装并校验，再切换新版本；失败会保留或恢复原安装。其他技能目录保持独立。

## WorkBuddy 预览与样式排查

如果选型时只看到 PNG 附件卡片，按[风格预览](../references/style-options.md)生成一份 2×2 HTML 对比预览，将 HTML 路径作为 `present_files` 的第一项，并查看返回的 `previewed`。

先让 WorkBuddy 报告本任务实际读取的 `SKILL.md` 绝对路径，再对同一目录运行 `python "<实际技能目录>/slidemuse.py" --version`；不要用下载文件名推断实际加载版本。`doctor --json` 的 `skill_root` 和 `skill_version` 也可用于核对。标准安装目标是 `~/.workbuddy/skills/slidemuse/`，其他导入方式以实际读取位置为准。

2.30.0 修复了选定总览后正式请求只保留文字风格、未附视觉参考的断点。更新后沿用已确认内容和选中的那一套图，用 `style-reference` 登记完整单页参考，再通过 `produce request` 或 `generate prepare --page-spec` 生成。真实图像调用必须附参考图，不能只发送路径或 JSON 文字；逐页检查 `style_consistency`。参考裁切仅用于风格输入，不能当最终页交付。

排查现有产物时比较三份材料：所选风格图、同一页组装前的 PNG/JPEG、最终 PPTX。如果单页原图已偏离，应修生成；原图正确而可编辑版不同，应修 Scene/Manifest 并真实渲染对照。标准 Page Spec 图片导出直接嵌入指定原图，不重新设计；不要把含预览和旧稿的混合目录交给旧目录合并入口。既有材料与选择均保留，不必重新做四套选型。

## WorkBuddy 项目交付检查

在独立的 SlideMuse 项目中配置一次，再把同一目录选为 WorkBuddy 任务目录：

```sh
python slidemuse.py workbuddy setup <project>
```

命令在项目内配置 `.workbuddy/settings.local.json` 和专用审阅目录。WorkBuddy 若弹出打开方式，由用户为该项目选择「正常打开」以加载本地钩子。默认读取项目根目录的 `job.json`，使用 `.slidemuse-review`。自定义时，为 `setup`、`review` 和 `publish` 使用相同的 `--job` 和 `--work`。

- 样图阶段把 `styles/compare-4-styles.html` 和同名 PNG 一起交给 `present_files`。即使面板未打开，PNG 已可点开，钩子会说明备用入口。只发送 PNG 时直接进入备用状态。
- Page Spec / Scene 任务用 `slidemuse.py workbuddy review <project>` 实渲染并准备逐页复核。若用审阅面板导出的记录，先运行 `workbuddy review <project> --import-record <record.json>`，再运行 `workbuddy review <project>` 重新评分。审阅命令结束后只保留内部草稿数据和审阅画面，没有独立草稿 PPTX。`slidemuse.py workbuddy publish <project>` 在当前验收通过后原子写入 `final/slidemuse.pptx`，仅把这个命令返回的文件交给 `present_files`。

检查作用于启用项目钩子的 WorkBuddy `present_files`。WorkBuddy 5.11.3 会提前索引已存在的文件，项目入口通过推迟生成独立 PPTX 来避免待审稿出现附件卡片。既有外部 `.pptx` 应留在原处，用作输入或本地对照。完整重建后端的 Manifest 流程继续使用其自有的逐页验收。
