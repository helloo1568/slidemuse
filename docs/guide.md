# 使用与技术指南

[← 返回首页](../README.md) · [English guide](guide.en.md)

## 当前流程契约

提供材料即可开始。Agent 可以先阅读正文，再推荐篇幅。未指定参考风格按无参考处理，页数根据材料推荐，默认 16:9 图片版并沿用材料语言；只询问影响结果且无法判断的信息，不要求先填满需求表。状态码、日志与评分卡由 Agent 管理。

- **唯一主流程**：新材料必须先形成内容方案和图片版，再按明确授权进入可编辑还原；不另起“编辑优先”捷径。
- **内容质量自检**：先把大纲展开成逐页内容稿，审阅结论、支撑、证据、解释和页面实际展示内容；未通过先修正，不进入风格阶段。
- **两处用户决策**：展示内容方案，再给风格选择。已有对应确认、代定或代选授权时直接继续，不重复询问。内部检查不增加用户确认轮次。
- **确定的风格豁免**：只有明确要求严格沿用指定模板、跳过预览或授权代选时按规则快进，不能由 Agent 自行判断。
- **Page Spec 中间层**：图片生成时同步保存准确文字、数据、来源、稳定 ID 与结构意图，避免可编辑还原时重新 OCR 和猜测。
- **已有授权**：“跳过预览”“你代选”“其余由你决定”按其范围执行。未指定项采用上述默认值并随方案说明；默认值不需要单独授权。
- **图片重建**：识别文字、几何、图片及遮挡，重建为有稳定 ID 的元素。
- **原生导出**：文本、形状、箭头、嵌套组合、表格和五类图表；图表带内嵌数据工作簿。
- **分层素材**：按指定坐标/遮罩输出 PNG，保留来源和哈希；照片、人物和插画可单独移动或替换。
- **可复现修改**：scene.json 保存布局与内容，修改指定元素后直接重新导出。
- **验收工具**：检查导出对象、文字、表格数据、图表数据、图片几何/裁切、组合变换、层级和原始整页底图残留。
- **GPT Image 2.5 指南**：Flare 用于快速探索，Sunburst 用于精确参考编辑；依照宿主实际能力选择。
- **恢复与局部修改**：`deck-spec.md` 保存状态与授权，`scene.json` 保存可编辑页面；新指令只使受影响的选择和产物失效。

模型资料：[OpenAI 图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)。

## “每个元素可编辑”是什么意思

| 元素 | 输出形式 | 可以修改 |
|---|---|---|
| 标题、正文、标签、页码 | 原生文本框 | 文案、字体、颜色、位置 |
| 几何形状、箭头、流程节点 | 原生形状 / 组合 | 尺寸、样式，取消组合分别编辑 |
| 表格 | 原生表格 | 单元格内容与格式 |
| 柱形、条形、折线、饼图、环形图 | 原生图表 + 工作簿 | 数据与图表格式 |
| 照片、人物、复杂插画 | 独立图片对象 | 移动、缩放、裁剪、替换 |

复杂插画内部仍是像素；被遮挡的信息也不能凭空准确恢复。
**Scene 编译等基本工具不包含自动 OCR、分割模型或端到端图片理解。** 识别与必要的背景补全由宿主 Agent/视觉工具完成；可选安装的[完整重建后端](../references/editable-backend.md)额外提供本地文字尺寸提示、素材板处理及需自行配置的 OCR 接口，几何提示不等于文字识别。
不能把整页截图加几个文本框称作全部可编辑，也不能把 SVG 图片嵌入等同于原生导出。

## 快速开始

本地工具的统一入口、环境诊断和隔离解释器选择见[命令指南](cli.md)。原脚本与流程门禁继续适用。

### 推荐：让 Agent 自动安装

把下面这句话发给 Codex、Claude Code 或 OpenCode：

```text
安装 SlideMuse，仓库是 https://github.com/helloo1568/slidemuse 。
请运行仓库自带的 install.py，注册 Skill、安装隔离依赖并完成自检；如果检测到多个客户端，请用 --client 指定当前客户端。
```

### 手动安装

需要 Python 3.10+。不需要手动创建虚拟环境，也不需要全局安装依赖：

```sh
git clone https://github.com/helloo1568/slidemuse.git slidemuse
python slidemuse/install.py
```

安装器会检测 Codex / Claude Code / OpenCode。只检测到一个客户端时会自动选择；同时检测到多个客户端时会停止并要求通过 `--client` 明确指定，避免安装到错误的用户级 Skill 目录。之后会创建独立 `.venv`、安装依赖并运行严格 Page Spec 自检：

```sh
python slidemuse/install.py --client codex
python slidemuse/install.py --client claude
python slidemuse/install.py --client opencode
```

安装器会先在临时目录完成新版本安装和验证，失败时保留原有版本。若发现旧名称的技能目录，会提示其位置；确认 `$slidemuse` 可用后再自行移除旧目录。

安装完成后使用 `$slidemuse` 调用。任务材料和产物继续放在独立工作目录，不要写入 Skill 安装目录。

默认安装不复制演示作品。需要随技能保留 IRENA 样板时，从完整仓库运行 `python install.py --client codex --with-sample`；精简包用户可按[样板说明](editable-sample.md)单独下载。

## 运行环境

| 环境 | 生图方式 | 说明 |
|---|---|---|
| Codex（最佳推荐） | 调用 Codex 图像生成能力；可选型号时优先 GPT Image 2.5 | Flare 用于方案探索，Sunburst 用于成品与精确编辑 |
| 其他 Agent | 调用该 Agent 自身提供或已连接的图像生成/编辑能力 | 保持同一状态机、提示词和验收标准 |
| 仅 Python 环境 | 不支持端到端生图 | 只能运行图片合并、文字叠加、Scene 编译、素材裁剪和审查脚本 |

本技能不会替其他 Agent 安装生图插件、寻找 API Key 或静默切换外部服务。若当前 Agent 没有生图能力，应明确停在对应阶段。

### 对 Agent 说

```text
使用 $slidemuse 把这份报告做成 10 页可编辑 PPT。
用于项目路演，没有指定参考风格。先展示内容大纲等我确认，再给我四套幻灯片浏览视图；选定后生成图片版和 page-spec.json，再继续还原可编辑版。
```

```text
使用 $slidemuse 从现有图片开始执行 Step 3，将这些幻灯片还原成可编辑 PPTX。
保持原始文字、布局与页序，把所有需要修改的元素独立拆出。
复杂插画保留为单独图片，清理背景残影，并交付 scene.json 和素材。
```

```text
使用 $slidemuse，把附件材料做成 12 页课堂汇报 PPT，受众是同学。
只做图片版，没有参考风格。先展示内容大纲等我确认，再展示四套使用同一组内容的幻灯片浏览视图，等我选择。
```

## 唯一三步流程

```text
读取源材料与上下文，说明默认值，只澄清影响结果的缺失信息
  ↓
Step 1A 逐页内容稿 → 内容自检/修正 → 完整展示 → 缺少确认或代定授权时等待
  ↓
Step 1B 四套幻灯片浏览视图 → 等待用户选择
  ↓（严格沿用参考/跳过预览/代选按明确授权处理）
Step 2  page-spec.json → 逐页生成并验收图片 → 图片版 PPTX
  ↓ 仅在用户明确要求可编辑版时
Step 3  Page Spec + 页面图片 → scene.json → 原生可编辑 PPTX → 结构与视觉验收
```

未指定项按上述默认值处理，不额外等待。内容与风格按用户意图执行，已有对应授权不重复确认；局部修改不扩大为全阶段授权。

### 大纲要展开到什么程度

先说明受众的核心问题、材料支持的整套回答和页间推进。每页注明页面类型（`cover`、`agenda`、`section-divider`、`concept`、`process`、`comparison`、`timeline`、`data-evidence`、`architecture`、`case-study`、`summary`、`qa` 之一）。普通内容页默认 3–5 条有区别的支撑要点，并包含结论、可定位来源、解释及适用边界；图表主导、简洁聚焦和密集查阅页按[密度规则](../references/content-density.md)声明例外及理由。列明实际展示的文案和图表，避免重复标题或为条目数量堆孤立数字；图表承载的论点可通过 `display.coverage` 映射，仍须实际核对语义和必现值。可选讲稿单列，不能藏起关键证据。封面和过渡按作用处理，不设统一字数或文字占比。S5 的原图、证据合成和逐页恢复使用 [`produce`](../references/page-production.md)。

内容自检检查目标覆盖、页间推进、要点密度与页面类型、论证深度、事实口径、可见内容完整及篇幅。记录判断依据、问题页和修正结果，阻塞项未解决时留在 S1。来源薄弱时缩小结论，不能编造机制或因果。语义自检不能由 Page Spec 校验或交付评分代替，详见[内容深度与自检](../references/content-outline.md)和[内容稿模板](../references/deck-spec-template.md)。

展示内容稿时报告大纲位置、页数、页面类型清单与素材图→页映射，并声明尚未生成任何图片与 PPTX；在此之前不创建 Page Spec、风格总览、生图提示或成品图片。之后沿用上下文中已经明确的确认或内容代定授权，不要求特定口令；单独的“继续”不自动扩大为全阶段代定。风格方案和图片页必须保留已确认的解释、正文和必要边界，排不下时按变更流程处理。

### 风格与图片制作

四套风格总览使用相同内容和任务指定画幅：不超过 8 页时展示全部，超过 8 页时选 6–8 个代表页。单页任务每套只展示该页，不补造页面。
每套总览使用横向画布与等大缩略页网格，3 页采用 2×2 网格留空一格，不制作竖向长图。`style-options.json` 只保留四个方案的当前版本，重试稿替换原编号，不能变成额外方案。选择前运行 `validate_style_options.py`，再人工核对缩略网格和内容，详见[总览验收](../references/style-options.md)。
文字连续两次不准确时，生成保留全部人物、产品和图形的无字页面，再叠加准确文字；主体拆分留到 Step 3。
如果输入本身就是页面图片或扫描版 PDF，且目标是还原可编辑 PPTX，可以直接从 Step 3 开始。已有可编辑 PPTX 的普通修改不使用本技能重做。
本技能已交付 Scene 的后续修改按[变更与恢复规则](../references/workflow-updates.md)继续 S6：保存基准版本、记录已授权差异，使受影响图片失效，避免旧基准触发重复确认。

## 工具

| 脚本 | 作用 |
|---|---|
| scripts/validate_page_spec.py | 验证内容确认、连续页序、稳定 ID、位置提示、图片路径唯一性及交付状态/画幅 |
| scripts/validate_style_options.py | 验证四套当前风格候选、代表页序、图片唯一性与横向画幅；缩略网格仍需视觉检查 |
| scripts/build_editable_ppt.py | 从 scene.json 构建原生对象并原子替换输出 |
| scripts/audit_editability.py | 复查导出的 PPTX，可选与 scene 比较，导出报告 |
| scripts/extract_assets.py | 根据已知 bbox 和可选灰度遮罩裁剪素材 |
| scripts/build_image_ppt.py | 按 Page Spec 的批准图片清单、页序与比例导出；兼容目录自然排序模式 |
| scripts/overlay_text.py | 兼容旧版：将准确文字栅格叠加到背景 |
| scripts/render_deck.py | 渲染全部 PPTX 页面，输出逐页 PNG、总览图和可选基准对照报告 |
| scripts/audit_page_content.py | 把看图或 OCR 的观察记录与 Page Spec 的准确文字、必现数字比对，并检查图片哈希 |
| scripts/plan_deck_update.py | 修改前保存批准版本，修改后列出可复用、需复查和需重做的页面 |
| scripts/evaluate_delivery.py | 汇总当前 PPTX 的内容、逐页视觉复核与可选 Scene 可编辑性审查，生成哈希绑定评分卡 |

```sh
python scripts/validate_page_spec.py work/page-spec.json --require-images --strict
python scripts/extract_assets.py work/extract.json work/assets/slide-01
python scripts/build_image_ppt.py work/page-spec.json output/image-deck.pptx
python scripts/overlay_text.py work/overlay.json
python scripts/render_deck.py output/image-deck.pptx output/image-review --page-spec work/page-spec.json
python scripts/render_deck.py output/editable.pptx output/editable-review --page-spec work/page-spec.json
python scripts/audit_page_content.py work/page-spec.json work/observations-s02.json --init --slide s02
python scripts/plan_deck_update.py snapshot work/page-spec.json work/snapshots/baseline.json
```

图片生成与可编辑还原之间的语义契约见 [Page Spec](../references/page-spec.md)，最终坐标、路径、支持字段与局部修改见 [场景协议](../references/scene-format.md)；
overlay.json 可参考 examples/overlay-spec.example.json，先填入实际背景路径；该旧版规格是模板，背景图未随仓库提供。
叠字时若文字超出指定框，脚本现在报错并停止该页输出；先调整文字框或字号，再重新运行。
渲染器在 Windows 优先调用已安装的 PowerPoint；否则使用 `soffice` 和 `pdftoppm`。输出目录须为空，复查同一目录时传 `--overwrite`。`review.png` 可逐页查看；指定 Page Spec 时按“基准 / 新渲染 / 像素差异”排列。`render-report.json` 给出逐页尺寸和差异均值，数值只用于定位变化，不能代替人工判断。可编辑版已授权局部修改时，历史基准可标为 `revision`，对照图会显示预期变化。
内容观察模板创建后，把图片中实际可见文字填入 `observed_text`，完整转录时设为 `complete`；运行 `audit_page_content.py ... --require-complete --output work/content-audit.json`。它会标出缺失项，图片变化时拒绝旧转录；OCR 结果不能覆盖已确认内容。变更规划命令见[变更与恢复规则](../references/workflow-updates.md)，只输出影响范围，不自动修改 Page Spec 或生成图片。
质量回归或发布时，再按[交付评测](../references/evaluation.md)对所有页面填写内容观察和渲染视觉复核，运行 `evaluate_delivery.py` 生成评分卡。只有 `pass` 且可编辑版包含 Scene 审查时，才可声称完成该版本的完整评测。
2.6.0 起，渲染和视觉复核同时绑定参考图片哈希；旧报告需重新生成并核验。图表、表格须逐元素填写 `data_reviews`，未检查的数据不能随页面视觉通过而自动通过。追加/删除页面仅重做受影响页；显示总页数或依赖整套页数构图的页面须设置 `depends_on_slide_count: true`。
Page Spec 导出自动严格验证，只使用清单中的已批准图片，目录中额外的旧稿不参与导出。默认沿用画布比例；`--width` / `--height` 可调整物理尺寸，同时指定时须保持该比例。重复图片路径、缺图、未批准图片或错误画幅会阻止导出，并保留既有输出。没有 Page Spec 的独立合并仍可使用 `python scripts/build_image_ppt.py work/slides output/image-deck.pptx`。
遮挡、透明度、背景清理见 [重建指南](../references/reconstruction.md)。
本版不提供通用 SVG 导入、合并表格单元格、自动吸附连线或富文本段内样式。

## 验证

```sh
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest tests/ -q
```

CI 覆盖 Windows / Linux、Python 3.10 / 3.12 / 3.13。
结构检查验证声明的场景对象，不能证明没有漏识别元素，也不代替 PowerPoint 渲染。
交付前逐页检查中文换行、字体、图表标签、图片边缘和移动后的残影。
作品集图片保持源页面像素尺寸；自动测试不依赖 PowerPoint。

## 来源与取舍

最近一次验证见[三页实战验收记录](acceptance-2026-09-18.md)，包含真实渲染、数据修改、对象移动和已知限制。

本次重点参考 [Hugo He 的 PPT Master](https://github.com/hugohe3/ppt-master) 的原生导出与图片分层思路，
并调研 [banana-slides](https://github.com/Anionex/banana-slides) 和 [PPTAgent](https://github.com/icip-cas/PPTAgent)。
Scene v1 JSON 编译器为独立实现，未复制这些项目的源码。可选安装的[完整重建后端](../references/editable-backend.md)按 MIT 许可证随包保留 [ningzimu/image-to-editable-ppt-skill](https://github.com/ningzimu/image-to-editable-ppt-skill) 的固定提交源码并记录哈希。
完整来源和能力边界见 [调研记录](../references/research.md)。

早期工作流参考小黑盒作者“玩家22186848”的教程《青年大学习AI版：零基础用GPT5.6做精美可编辑PPT》，
以及 B 站 UP 主“一往无前河井”的学术 PPT 制作思路。感谢原作者与社区。

## 隐私与许可

基本 Scene 工具不发起网络请求、不需要 API Key。实际生图/视觉分析由宿主服务执行，可能上传对应材料；可选安装的完整重建后端可按用户配置调用 OCR/图像接口，`rebuild --offline` 会隔离外部配置与凭证发现。
公开产物前排除私人材料与凭证，保留需要分发的 scene 和素材。

[MIT License](../LICENSE) © 2026 风清云影（helloo1568）

## 图表可靠性（2.8.0）

数值标签与几何比例分别核对；同一几何问题连续两次检查失败就停止生图修复。精确水平条形区域可用 `build_chart_image.py` 生成，程序替换遵守宿主权限；`audit_chart_geometry.py` 检查实际观察的条形/柱状起止坐标，不负责视觉识别。详见[图表可靠性](../references/chart-reliability.md)。

完整评分使用 v1.2：逐元素填写来源/数值、标签/单位、图表几何或表格行列对应，每页填写实际数据视觉清单。旧 v1.1 复核须实际补查新增项目。原生图表的逐点颜色、负值反色、标签位置、绘图区与环形孔径等直接写入 [Scene](../references/scene-format.md)，不再为这些受支持项另写后处理。

## 讲稿与论文/长文审阅（2.9.0）

内容稿已有讲稿时，将最终文本写入 Page Spec/Scene 的 `speaker_notes`，图片版与可编辑版均保留为演讲备注。可编辑编译传 `--page-spec` 核对上游，交付评测读取实际备注；只改讲稿会重建导出而复用图片。按需用 `export_speaker_notes.py` 导出附来源的讲稿，详见[讲稿保留](../references/speaker-notes.md)。

论文审阅展开公式变量、输入/运算/输出和实验口径；长文区分目标、行动、支撑和效果，来源冲突记录后核验或缩小范围。见[按材料审阅](../references/material-reading.md)。备注保真检查不能证明大纲深度。

## 多材料评测（2.10.0）

跨材料评测先冻结材料清单与规则，再记录每次完整交付，分别汇总首次与最终成绩。缺失、过期或未审阅案例保留在分母；修改只生成新尝试。用 `evaluate_benchmark.py review-contract` 导出不含生成提示的内容合同，再核验投影与源文件绑定。客观调用事务和作者质量判断须另行分离，详见[评测记录](../references/benchmark.md)。

原生图表同时核验显示缓存和嵌入工作簿，避免演示正确而“编辑数据”恢复旧值。评测工具和软件测试不能替代实际来源、视觉与独立性审阅。

## 完整图片重建后端（2.19.0）

S6 除 Scene 路线外，可选接入[完整图片重建后端](../references/editable-backend.md)：输入归一化、本地文字尺寸提示、原生曲线与表格、素材板去背拆分、公式素材及逐页恢复，统一入口为 `slidemuse.py rebuild`。扩展依赖用 `install.py --with-editable` 安装，`rebuild --offline` 隔离外部配置与凭证。后端按 MIT 许可证随包保留上游固定提交源码并记录哈希；[上游适配边界](../references/upstream-editable.md)说明 Scene 路线如何复用其测量与表格方法。几何提示、结构检查和诊断预览都不等于文字识别或 Office 排版，最终仍须真实渲染后核对。

## 完整图片生成后端（2.20.0）

S5 除 Page Spec 主流程外，可选接入[完整图片生成后端](../references/generate-backend.md)：逐页生图任务与提示、分派/结果/阻塞登记、运行状态汇总、图片版组装和纯色去底，统一入口为 `slidemuse.py generate`。扩展依赖用 `install.py --with-generate` 安装，`generate --offline` 隔离外部配置与凭证。后端按 MIT 许可证随包保留上游固定提交源码、文档、提示模板和 12 套风格参考并记录哈希。一条任务只用一个事实源：`prepare` 生成的 `slide_jobs.json` 不能当成 `page-spec.json`。`prepare` 只写确定性任务文件，不调用生图模型；仍由宿主 Agent 生图，组装出的 PPTX 仍须真实渲染后核对。
