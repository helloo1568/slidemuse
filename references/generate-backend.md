# 完整图片生成后端

多页图片版制作需要逐页任务、子代理分派和状态登记时读取。统一入口为 `slidemuse.py generate`，不用另外安装名为 `codex-ppt` 的全局命令。

上游为 `ningzimu/codex-ppt-skill`，完整安装用源码、文档、提示模板、12 套风格参考和测试随技能保留。[upstream.json](../vendor/codex-ppt/upstream.json)记录固定提交、原始文件哈希；[MIT 许可证](../vendor/codex-ppt/LICENSE)随包保留。上游 SKILL 是来源记录，当前任务仍以 SlideMuse 主入口、用户授权和宿主工具规则为准。SlideMuse 适配在 [upstream.json](../vendor/codex-ppt/upstream.json) 的 `patches` 中声明：默认生图模型改为 gpt-image-2.6，gpt-image-2.6 沿用 GPT Image 2 尺寸规则（最大边 3840px，支持 2K/4K）；xhigh/max 质量仍限 2.5 系列。原始上游哈希保留在 `files`，补丁哈希与理由记录在 `patches`，`capabilities --verify-source` 按补丁哈希校验。

## 安装和选择

```sh
python install.py --client codex --with-generate
python slidemuse.py generate capabilities --verify-source
python slidemuse.py generate --help
```

额外依赖装入本技能隔离环境。普通安装也保留完整源码；需要扩展运行能力时使用 `--with-generate`，或用技能解释器安装 `requirements-generate.txt`。`capabilities` 只检查可用性和来源，不读取凭证或测试外部服务。

通过 `fyai-setup` 或 `generate runtime bootstrap` 配置共享 API 环境后，`generate image` 自动使用同一 `CODEX_PPT_HOME/.venv` 解释器；没有共享环境时使用当前已安装生成依赖的解释器。配置诊断与实际调用不会各用一套依赖。

**一条任务只用一个事实源。** SlideMuse 主流程用 `page-spec.json` + `slides/NN-*.png` + `build_image_ppt.py`；本后端用已确认大纲 + `prompts/slide_NN.json` + `slide_jobs.json` + `origin_image/slide_NN.png` + `assemble_ppt.py`。任务格式不能互换；`prepare --page-spec` 负责将同一批准内容投影到生成格式，稳定 ID、文字和数据仍保留。S1–S5 的门禁、内容确认和视觉选型两套流程完全相同，本后端不放宽任何门禁，也不替代内容大纲的要点密度要求（见 [content-outline.md](content-outline.md)）。

## 能力覆盖

| 能力 | 命令 | 实际边界 |
|---|---|---|
| 逐页生图任务与提示 | `prepare` | 只写 `prompts/slide_NN.json`，确定性脚本，不调用生图模型 |
| 任务与运行状态汇总 | `status` | 读取 `slide_jobs.json`/`slide_run_state.json`；不判断图片好坏 |
| 分派登记与并发额度 | `dispatch` | 需要真实 worker 与提示文件；聊天记录不构成分派 |
| 结果登记与来源校验 | `result` | 复制选中图片到最终路径，记录后端来源与哈希；拒绝本地绘制类后端 |
| 阻塞登记 | `blocker` | 已完成页面拒绝改标阻塞 |
| 图片版 PPTX 组装 | `assemble` | 按 `slide_NN` 页序充满整页，仅导出合同明确声明的讲稿；不替代真实渲染验收 |
| 纯色背景去底 | `chroma` | 本地像素处理，需核对 alpha 边缘 |
| 共享运行环境与 API 配置 | `runtime bootstrap/config/doctor` | 需要联网安装依赖并写用户级 `.env`；只在用户选定 API 后端时使用 |

## 逐页任务、分派与登记

正式制作先按[风格预览](style-options.md)登记选中总览中的完整单页参考，并实际完成一张高清代表页与选中图的对照。`prepare --page-spec` 与主 `produce` 共用参考解析：所有正式 job 都带同一选型基线，记录源图和派生图哈希；明确锁定的独立单页不会被丢弃。子代理仅接收当前页独立提示、锁定视觉规范和实际需要附上的单页图，不把完整六宫格或其他方案作为输入，也不能仅凭文字重述风格。实际独立分派才能记录 worker；无法隔离时不要声称已使用子代理。同类失败连续两次更换真实方式或阻塞，主流程可用 `produce failure` 执行门禁。

用户已明确授权并配置兼容 API 后，可通过现有图像客户端发送独立单张请求（不隐式切换服务；`--offline` 禁止）：

```sh
python slidemuse.py generate image generate --prompt-file "<request_snapshot 的实际路径>" --n 1 --no-augment --size 2560x1440 --out "<raw-page.png>"
python slidemuse.py generate image edit --prompt-file "<request_snapshot 的实际路径>" --image "<request_reference 的实际路径>" --n 1 --no-augment --size 2560x1440 --out "<raw-page.png>"
```

真正没有视觉参考的任务才用 generate；选型任务或明确参考图的任务使用支持图片输入的 edit，并实际附上对应图片。不要同时运行两条命令。结构化 job 的 `input_images` 或主流程请求中的 `style_reference` 不能当作纯文本吞掉：generate 会拒绝此类带图请求，edit 会核对实际附图。仅把图片路径或含路径的 JSON 写入提示不等于上传图片。实际尺寸和模型依所选后端支持设置；服务不支持参考图时说明限制，使用已授权的可用方式，不静默降级。命令只生成文件，仍须逐页实际看图、登记结果。

风格绑定任务的 `review` 还要求 `style_consistency`，对照正确参考的配色、字体层级、材质、图形语言和版式节奏，并绑定参考身份。缺失、失败、错误参考或参考字节变化都不能通过审阅/组装。工具检查记录与文件的关联，不自动证明审美一致。

- 主流程和完整后端均执行 SKILL.md 的禁止静默降级规则。生图失败时登记阻塞，不得用程序化整页排版补缺；局部精确图表、文字修正和证据合成仅可在真实生图原件基础上执行。保留调用证据与原件，登记来源不能代替真实模型调用。

```sh
python slidemuse.py generate prepare --spec "<work>/deck_spec.json" --out-dir "<work>"
python slidemuse.py generate status "<work>" --json
python slidemuse.py generate dispatch "<work>" --slide 3 --agent-id <真实worker-id> --prompt-file "<绝对提示路径>"
python slidemuse.py generate result "<work>" --slide 3 --agent-id <真实worker-id> --backend-used "built-in image tool" --selected-source "<生成图路径>" --generation-record "<实际调用记录.json>" --qa-note "<看图结论>"
python slidemuse.py generate blocker "<work>" --slide 3 --agent-id <真实worker-id> --reason "<缺失条件与证据>"
python slidemuse.py generate assemble "<base_dir>" "<deck>.pptx"
```

- 每张成品图必须由**已确认的生图后端**产出，并写入 `sample_generation_method` 让子代理沿用同一路径；`result` 会拒绝把 Pillow、SVG、HTML/CSS、python-pptx 或手工拼图登记为成品图。
- 只有真实 worker 才能 `dispatch`；`status` 的 `dispatchable_slides` 与 `dispatch_slots_available` 决定还能分派几页，慢不代表失联。
- 每页围绕批准内容（普通内容页默认 3–5 条支撑，例外见 content-density.md）写提示，标题、要点和结论必须出现在图片本身，不得只留在提示词里。
- 需要严格输入素材时，在 `required_images` 标记角色与保真要求，并在 S1 内容门禁处让用户核对素材图→页映射。
- 状态以脚本记录为准：`slide_jobs.json` 中仍有 `pending`、`dispatched` 或 `blocked` 的页面时不得组装。

新任务的 `result --generation-record` 使用与 [produce](page-production.md) 相同的七字段记录：`version`、`slide_id`、`request_sha256`、`source_sha256`、`backend`、`model`、`result_ref`。此处 `slide_id` 使用后端任务 ID（如 `slide_03`），请求哈希为实际 `prompts/slide_03.json` 的文件 SHA-256，后端名称与 `--backend-used` 一致。记录保存实际调用信息；`model` 未暴露时为 `null`。`review` 和 `assemble` 会重新核验记录及图片，不能靠手改完成状态跳过。`sample_approved` 仅用于明确带 `image_origin` 来源和图片哈希的既有导入样张，新生成样张同样登记真实调用。

样张方法明确指定 `model` 时，登记、审阅及组装均核对实际调用记录中的模型；不匹配或实际模型未暴露时拒绝。模型名只正规化已知的 `openai/gpt-image-*` 提供商前缀及 `/edit`、`/text-to-image` 后缀，不猜测不同版本等价。七字段记录不能证明生成模式、quality 或上下文处理细节；这些字段列入 `unverified_sample_method_fields`，不会仅凭后端名称相同就把整个 `sample_generation_method_matched` 设为 true，仍须按真实调用检查。

`dispatch` 在状态锁内执行 `max_concurrency` 限额，重复登记同一活动任务不额外占位。API 生成在发出请求前检查预期输出文件是否冲突；返回空结果、数量不符、不可解码图片或与显式 `WIDTHxHEIGHT` 请求不一致的实际像素会失败，并保留原输出及其预览。`--size auto` 接受服务端选择的尺寸；需要放大或其他尺寸时应重新生成或明确调整已批准规格，不能把缩略图当作请求分辨率的成功结果。

`--prompt-file` 可以指定任务目录内的自定义 worker 交接文件；分派分别记录实际交接文件和批准任务 JSON 的哈希，结果登记、审阅和组装均校验它们未变。调用记录的 `request_sha256` 始终对应批准的任务 JSON，不误用交接说明文件的哈希。

`prepare --spec` 的输入是上游格式的 `deck_spec.json`（字段示例可用 `prepare --write-template <path>` 生成）。它由已确认的大纲填写，不替代 `deck-spec.md`：页面类型与 3–5 条要点仍以内容门禁批准的版本为准。

`prepare` 先完整验证和构造所有页的 prompt、jobs、内容合同及显式讲稿，再在同一任务锁中提交。输入错误不会改动旧文件；提交中断时，下一次 `status`、`prepare`、登记、审阅或组装先恢复上一组完整文件。`--force` 只允许替换没有活动 worker 的任务；仍有 `dispatched` 页时，先登记其结果或明确记录 blocker，避免覆盖正在执行的输入。图片引用中的 URI 原样保留，只有相对本地路径按规格文件目录解析。

所有新任务默认空备注；讲稿仅从输入中显式声明的 `speaker_notes` 导出，不自动吸收工作目录遗留的 `speech.md`。Page Spec 的 `canvas` 同时传入任务、提示词与组装，4:3 等画幅不会被提示词固定为 16:9。显式画布要求正整数像素；审阅和组装拒绝任一边小于该画布的原图，既有导入样张也执行相同要求。组装时用 `--aspect-ratio 4:3` 等实际画幅参数，比例不符时拒绝拉伸。

随包保留的 AtlasCloud `generate-batch` 客户端在取得 prediction ID 后，轮询或下载重试会继续读取同一任务，并保留批内已完成图片；不因查询超时重新提交整组生成。尚未取得 ID 的提交错误与后续查询错误分开处理。公开 `generate image` 入口仍只支持单次 `generate` / `edit`。

## 离线执行

```sh
python slidemuse.py generate --offline prepare --spec "<work>/deck_spec.json" --out-dir "<work>"
python slidemuse.py generate --offline status "<work>" --json
```

`--offline` 写在 `generate` 后，隔离配置与凭证发现，并把 `CODEX_PPT_HOME` 指向临时目录；本地任务、状态、登记、组装和去底仍可用。`runtime` 需要建虚拟环境、写用户级 `.env` 或探测 API，`--offline` 下直接拒绝。Windows 子进程统一用 UTF-8。

## 风格库与上游参考

`prepare` 生成的提示与 `references/` 中的 12 套内置风格可直接作为视觉系统输入；用户自定义风格存放在 `${CODEX_PPT_HOME:-~/.codex-ppt-skill}/references/`，与 [style-library.md](style-library.md) 描述一致。字段与工作流细节读取上游文件：

- 大纲、风格与样张：[outline-style-and-sample.md](../vendor/codex-ppt/skills/codex-ppt/docs/outline-style-and-sample.md)
- 门禁与进度：[workflow-gates-and-progress.md](../vendor/codex-ppt/skills/codex-ppt/docs/workflow-gates-and-progress.md)
- 逐页分派：[slide-generation-and-subagents.md](../vendor/codex-ppt/skills/codex-ppt/docs/slide-generation-and-subagents.md)
- 素材与组装：[user-supplied-assets.md](../vendor/codex-ppt/skills/codex-ppt/docs/user-supplied-assets.md)、[project-assembly-and-reporting.md](../vendor/codex-ppt/skills/codex-ppt/docs/project-assembly-and-reporting.md)

这些参考中的裸命令（`scripts/prepare_slide_prompts.py`、`scripts/assemble_ppt.py` 等）均替换为 `python <skill-dir>/slidemuse.py generate <子命令>`。上游允许本地绘制或叠加文字的做法不适用：成品图必须来自已确认生图后端，准确文字兜底仍用 `overlay_text.py` 并按 Step 2 验收。

## 验证与交付

组装出的图片版 PPTX 仍需真实渲染核对：

```sh
python slidemuse.py render "<实际最终PPTX路径>" "<work>/office-review"
```

核对页数、页序、画幅、文字与裁切，再交付 PPTX、已确认大纲、`slide_jobs.json`、逐页任务与提示、`speech.md`（如有）和渲染预览。结构通过不等于视觉通过；无渲染器时只写“仅完成结构验证”。完整接入不表示每张生成的图片都无需复查。

## 2.21.0 内容与交付适配

`prepare` 在写任务前执行当前内容检查：普通内容页默认 3–5 条，例外带理由；内容页同时保留结论、解释和来源记录。`prepare --write-template <path>` 生成当前完整示例；不覆盖已有模板。也可直接使用 `prepare --page-spec <approved.json> --out-dir <deck>`，可见内容与稳定 ID 完整进入提示和 `slidemuse-content.json`。这是一份内容的适配投影，不把两种任务文件混为同一格式。

新任务在 `result` 登记后先运行 `generate review <deck> --init`，实际看图填写 `content-review.json` 并运行同一命令核对。组装检查当前合同、提示、观察和图片哈希、页面集合/顺序、完成状态、画幅及已声明的画布分辨率。普通图片直接保留原图字节，不自动压缩；带 EXIF 旋转或镜像的图片用无损 PNG 正规化后嵌入，原始图片及其来源哈希保持不变，最终包另核对派生媒体哈希。失败不会替换已有 PPTX。旧任务无内容合同会报告 `legacy_not_checked`，不意味着已通过新内容验收。详细命令及例外见[内容密度与画面验收](content-density.md)。
