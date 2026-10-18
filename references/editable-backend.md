# 完整图片转可编辑后端

S6 直接还原图片/PDF/图片版 PPTX，或需要 Scene 尚未表达的曲线、表格单元格样式、测量提示、公式和逐页恢复时读取。统一入口为 `slidemuse.py rebuild`，不用另外安装名为 `editppt` 的全局命令。

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

字段按需读取[Manifest 协议](../vendor/image-to-editable/skills/image-to-editable-ppt/references/manifest-schema.md)，对象决策读[页面重建树](../vendor/image-to-editable/skills/image-to-editable-ppt/references/page-decision-tree.md)，详细参数读[CLI 参考](../vendor/image-to-editable/skills/image-to-editable-ppt/references/cli-helper.md)。这些参考中的裸 `editppt` 命令均替换为 `python <skill-dir>/slidemuse.py rebuild`。上游要求所有前景都经生图提取的做法，不覆盖本技能受保护证据和现有透明原始素材的保留规则。

## 素材、公式与服务

```sh
python slidemuse.py rebuild image process-sheet work/rebuild/pages/page_001 --asset-sheet-source assets/sheet.png --regions regions.json
python slidemuse.py rebuild formula render-latex work/rebuild/pages/page_001 --tex "a^2+b^2=c^2" --out assets/formula.svg --box 100,100,400,100 --fragment formula-fragment.json
```

复杂图像编辑使用当前宿主的图像工具，先看源图、保持同一视觉基准，按工具返回的有效路径导入。原始证据和已有透明素材优先保留，不用生图替换精确来源。工具输出成功后仍需看图核对边缘和主体完整性。

用户选用 PaddleOCR 或外部图片 API 时，可不加 `--offline` 并配置对应服务，密钥不写入任务文件。接口接入不代表本机账号/服务可用性已实测；原生工具存在时按宿主要求使用原生工具。

## 验证与交付

完整后端 `preview.png` 是 Pillow 示意预览，不是 Office 排版。最终 PPTX 仍执行：

```sh
python slidemuse.py render <实际最终PPTX路径> work/office-review
```

实际核对文字、表格、曲线、素材、页序和备注，再抽查编辑；结构通过不等于视觉通过。交付最终 PPTX、输入/页映射、已有 Page Spec/内容契约、逐页 Manifest、引用素材、任务记录、验证报告和真实渲染预览；原生数据图表仍交付 Scene。说明公式/图像的编辑边界及低置信度项。完整接入不表示每张复杂图片都能无损还原。

## 同一批准内容的传递

可用 `rebuild --offline prepare --page-spec <approved.json> --job-dir <run>` 直接从批准图片准备重建，同时保存 `slidemuse-page-content.json`；后续 `page-prompt` 会携带对应页原文、来源、数据和稳定 ID，OCR 只辅助几何。Page Spec 需先通过 `validate --content --require-images --strict`。直接图片输入仍沿用原入口。
