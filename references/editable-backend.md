# 完整图片转可编辑后端

S6 直接还原图片/PDF/图片版 PPTX，或需要 Scene 尚未表达的曲线、表格单元格样式、测量提示、公式和逐页恢复时读取。统一入口为 `slidemuse.py rebuild`，不用另外安装名为 `editppt` 的全局命令。

`prepare --job-dir` 只用于新建或空目录。已有任务通过其状态、派发、结果登记和恢复命令继续，重复 prepare 不会覆盖原图或清空活动任务。图片版 PPTX 的轻量提取只接受可忠实还原的可见整页图片；隐藏图片对象及其他不支持的效果需先真实渲染。

上游为 `ningzimu/image-to-editable-ppt-skill`，完整安装用源码、字段参考、提示模板和测试随技能保留。[upstream.json](../vendor/image-to-editable/upstream.json)记录固定提交、原始文件哈希及本地补丁哈希；[MIT 许可证](../vendor/image-to-editable/LICENSE)随包保留。上游 SKILL 是来源记录，当前任务仍以 SlideMuse 主入口、用户授权和宿主工具规则为准。

## 安装和选择

```sh
python install.py --client codex --with-editable
python slidemuse.py rebuild capabilities --verify-source
python slidemuse.py rebuild --help
```

额外依赖装入本技能隔离环境。普通安装也保留完整源码；需要扩展运行能力时使用 `--with-editable`，或用技能解释器安装 `requirements-editable.txt`。`capabilities` 只检查可用性和来源，不读取凭证或测试外部服务。

直接图片还原优先使用完整后端；已有 Scene、原生数据图表及数据依赖契约继续使用 Scene。两种方式均属于 S6，不改变 S1–S5 的流程。一项任务按输出格式保持单一事实源：`manifest.json` 不能直接当成 `scene.json`，上游独有属性保存在原格式中，避免转换丢失。

## 能力覆盖

| 能力 | 实现/命令 | 实际边界 |
|---|---|---|
| 图片、多页 PDF、图片版 PPTX 归一化 | `prepare` | 保留源比例、页序和备注；旧 `.ppt` 需要 Office 转换器 |
| 自动文字框、字形高度、字号提示 | `page hints`、`run hints` | 本地测量几何，不等于自动识别文字；提示可能漏检 |
| PaddleOCR-VL 文字识别 | 配置 Token 后运行 hints | 需要可用服务和用户选定的联网方式 |
| 原生文本、卡片、结构 | `page build` | 源像素坐标映射至幻灯片；不覆盖已确认 Page Spec |
| 曲线路径、虚线、端点箭头 | `shapes[].path_px` 等 | 原生路径，不是数据驱动图表 |
| 表格合并、比例与逐格样式 | `tables[]` | 边框、填充、边距和对齐；斜线表头/格内图片不支持 |
| 背景/前景拆分与来源决策 | `background_strategy`、`visual_inventory` | 复杂补全由图像工具执行，脚本不自动理解页面 |
| 透明/纯色素材板去背与区域拆分 | `image process-sheet` | 按完整对象保留断开笔画；核对 alpha 边缘 |
| 素材导入、哈希与来源 | `image import`、`imagegen-jobs.json` | 仅记录真实来源和工具输出 |
| 用户原图与受保护证据保留 | `preserve-asset` | 对照独立登记原件及 SHA-256，逐字节保留 PNG/JPEG |
| LaTeX 公式素材 | `formula render-latex` | 需 TeX/转换器；SVG/PNG/PDF，不是原生公式对象 |
| 宿主生图、OAuth/API 接口 | `builtin-imagegen` 或可选 `image generate/edit` | 优先使用宿主工具；外部接口按用户选定后端使用 |
| 逐页分派、租约与失败恢复 | `run next/dispatch/record/reset` | 真实 worker 才能登记；慢不代表失联 |
| 最终组装、内容/素材/备注验证 | `run finalize`、`page validate` | 不能替代真实 Office 渲染 |
| 原生数据图表及联动修改 | 原有 Scene 和数据绑定工具 | 继续保留可编辑工作簿和可靠数据来源 |

## 准备输入、提示与执行

```sh
python slidemuse.py rebuild --offline prepare input.pdf --job-dir work/rebuild
python slidemuse.py rebuild --offline run next work/rebuild --json
python slidemuse.py rebuild --offline page hints work/rebuild/pages/page_001
python slidemuse.py rebuild page-prompt work/rebuild --page page_001 --out worker-prompt.md
```

`--offline` 写在 `rebuild` 后，隔离 OCR/图像配置和凭证发现；本地准备、测量、素材处理、编译和组装仍可用。`prepare` 默认记录 `builtin-imagegen`，只准备输入与文字几何提示，不自动重建页面。Windows 子进程统一用 UTF-8。

图片输入先应用 EXIF 显示方向。图片版 PPTX 按实际裁剪区域归一化，并保留原始幻灯片物理尺寸；遇到无法准确提取的旋转、翻转、叠加或特殊图片效果时明确停止，先真实渲染成独立页面图片后再准备。不会把未经裁剪的原媒体图当成可见页面。

`prepare --page-spec <approved.json>` 同时保存哈希绑定的语义快照，将显式 `speaker_notes` 写入实际使用的备注清单；未声明的备注保持空。构建和最终验证分别对照快照与 PPTX 实际备注，保留空行和换行，不能用空清单绕过检查。显式 API 生成的默认模型为 `gpt-image-2.6`，用户已有的明确配置保持原值。

读取每页 `text_hints.json`/`text_hints.png`，结合源图纠正漏检、误框、换行和同级字号。已有 Page Spec 的文字、数字、来源和 ID 仍为事实源；OCR 不得静默覆盖。直接输入没有 Page Spec 时，先建立可见内容清单，记录看不清的部分。

根据 `run next` 的动作处理：单页可由主 Agent 执行，多页在环境支持且任务允许时分派真实 worker，先有 worker 再登记。`page-prompt` 只写适配提示，不伪造分派。单页本地示例：

```sh
python slidemuse.py rebuild run dispatch work/rebuild --page page_001 --agent-id main --prompt-file <绝对提示路径> --local
python slidemuse.py rebuild page build work/rebuild/pages/page_001
python slidemuse.py rebuild page validate work/rebuild/pages/page_001
python slidemuse.py rebuild run record work/rebuild --page page_001 --agent-id main
python slidemuse.py rebuild run finalize work/rebuild
```

页面重建后按真实检查填写 `page_result.json`，验证通过才可 record。错误只修相关对象或素材；重试须有实际变化，保留原证据；不能因为耗时长就 reset 活跃租约。

`page build` 先在临时位置完成 PPTX、检查 ZIP/XML，再生成本次示意预览，全部成功后才发布。输入缺失、非法 XML、预览失败或文件发布失败时，保留或恢复上一版 PPTX 与预览；两个输出路径必须是相互独立的文件路径。若文件系统也阻止回滚，错误会指出仍保留旧文件的备份目录，不能把此次构建当成成功。

字段按需读取[Manifest 协议](../vendor/image-to-editable/skills/image-to-editable-ppt/references/manifest-schema.md)，对象决策读[页面重建树](../vendor/image-to-editable/skills/image-to-editable-ppt/references/page-decision-tree.md)，详细参数读[CLI 参考](../vendor/image-to-editable/skills/image-to-editable-ppt/references/cli-helper.md)。这些参考中的裸 `editppt` 命令均替换为 `python <skill-dir>/slidemuse.py rebuild`。上游要求所有前景都经生图提取的做法，不覆盖本技能受保护证据和现有透明原始素材的保留规则。

## 按区域测量文字

如果已有确认内容、知道文字的位置，但整页 `hints` 把照片高光当文字或漏掉文字，可直接圈定可见标题、正文、图注等代表区域。用归一化后的源图坐标（左上角 x/y 与宽高 w/h），区域内只放目标文字并留出适当背景，排除旁边的插图、坐标线和边框：

```sh
python slidemuse.py rebuild --offline measure-text source.png --region title 70 235 890 179 --region label 70 415 500 120
```

该命令复用上游局部墨迹算法，输出原图坐标下的墨迹框、字形高度、行数、明暗极性和候选字号（按 `--slide-width-inches` 换算，默认 13.333333）。它不联网、不识字、不改图，不自动写 Scene，不证明辨认到了目标；低对比或空白区域不报字号。将同层字号作为起点，选正确字体后导出并实渲染，核对实际行距、字宽与基线。不要把紧贴笔画的墨迹框直接当 PowerPoint 文本容器，也不要用候选字号覆盖已核验的布局。

## 素材、公式与服务

```sh
python slidemuse.py rebuild image process-sheet work/rebuild/pages/page_001 --asset-sheet-source assets/sheet.png --regions regions.json
python slidemuse.py rebuild formula render-latex work/rebuild/pages/page_001 --tex "a^2+b^2=c^2" --out assets/formula.svg --box 100,100,400,100 --fragment formula-fragment.json
```

复杂图像编辑使用当前宿主的图像工具，先看源图、保持同一视觉基准，按工具返回的有效路径导入。原始证据和已有透明素材优先保留，不用生图替换精确来源。工具输出成功后仍需看图核对边缘和主体完整性。

需要原样保留用户提供的标志、照片或证据图时，由任务主 Agent 在派发该页前登记实际原件；这沿用已有用户授权，不新增确认步骤：

```sh
python slidemuse.py rebuild --offline preserve-asset work/rebuild --page 1 --source materials/official-logo.png --asset-id official-logo --note "用户提供的原始透明标志"
```

命令将 PNG/JPEG 原件及其 SHA-256 登记到 `input/preserved-originals/<asset-id>/`，把相同字节复制到页内 `assets/`，并返回 `asset_provenance` 和 `visual_inventory` 的条目。将条目分别加入 Manifest 中对应的数组，再为 `images[]` 填写返回的 `path` 和页面位置。登记副本属于任务输入，不在页 worker 的可写范围内。相同 ID 只能复用相同原件；原件改变时使用新的 ID。

页级与最终验证均要求来源路径指向该独立登记原件，并核对登记哈希、原件和使用素材的实际字节。仅写 `source_type: "user-provided"`、自行声明一个哈希或把 `source` 指回素材自身不能通过。不得把页截图的裁片重新命名为用户原件；命令拒绝直接从任务页输出登记原图，整页位图加重复可编辑文字的原有限制继续适用。原件登记证明复用的是哪一份输入，不能代替对来源说明、证据含义和显示效果的核查。

用户选用 PaddleOCR 或外部图片 API 时，可不加 `--offline` 并配置对应服务，密钥不写入任务文件。接口接入不代表本机账号/服务可用性已实测；原生工具存在时按宿主要求使用原生工具。

## 验证与交付

`run finalize` 使用 `run record` 已登记并核验的页面文件，支持 `page_result.json` 指定的自定义 Manifest 和输出路径。最终验证按实际幻灯片顺序核对正文、对象、图片媒体及页面关联的备注；页级旧报告不能代替最终包检查。

使用 `prepare --page-spec` 时，最终验证还独立读取哈希绑定的批准内容，对照最终 PPTX 的原生正文，而不只检查 worker 的 Manifest 是否自洽。批准为 `native` 的文字必须在实际文本对象中出现；同一文本框内的 runs、段落、换行及空白拆分可以合并匹配，标点、数值、正负号和单位仍须相同。不同对象的数字不会被拼接成一个批准值。原生表格核对行、列和逐格内容；数值 `10` 可对应数值等价的 `10.0`。批准的原生图表核对实际类别、系列和数值缓存；完整后端不能构建所需原生数据图表时，应使用 Scene 图表通路。

报告中的 `approved_content_errors` 非空会阻止最终发布，`approved_content_checks` 记录逐页核对范围。明确选择 `raster`/`either` 的内容及受保护图片保持原来的编辑性选择；无法从原生对象验证的内容列入 `visual_review_required`。这个列表表示**仍需完成视觉核查**，不表示机器已经看过图片或批准其内容；即使结构 `passed: true`，也必须在下面的真实渲染中核对这些项。语义概括不会被误当成必须逐字展示的正文，备注继续由独立备注契约检查。

完整后端 `preview.png` 是 Pillow 示意预览，不是 Office 排版。最终 PPTX 仍执行：

```sh
python slidemuse.py render <实际最终PPTX路径> work/office-review
```

实际核对文字、表格、曲线、素材、页序和备注，再抽查编辑；结构通过不等于视觉通过。交付最终 PPTX、输入/页映射、已有 Page Spec/内容契约、逐页 Manifest、引用素材、任务记录、验证报告和真实渲染预览；原生数据图表仍交付 Scene。说明公式/图像的编辑边界及低置信度项。完整接入不表示每张复杂图片都能无损还原。

## 同一批准内容的传递

可用 `rebuild --offline prepare --page-spec <approved.json> --job-dir <run>` 直接从批准图片准备重建，同时保存 `slidemuse-page-content.json`；后续 `page-prompt` 会携带对应页原文、数据、来源记录和稳定 ID，OCR 只辅助几何。Page Spec 需先通过 `validate --content --require-images --strict`。直接图片输入仍沿用原入口。
