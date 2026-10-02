# 可恢复的交付流水线

`run_deck.py` 面向已完成内容、风格和图片确认的 Page Spec，以及已准备好的 Scene。内容提炼、生图与用户确认仍由宿主 Agent 按 SKILL 状态机完成。流水线不自动生成图片，也不自动填写通过结论。

把 `job.json` 放在任务材料目录，工作目录另建在旁边。所有配置路径相对于 `job.json`，不能越出其所在目录。

从 2.13.0 起，可以先生成配置并运行只读预检：

```bash
python scripts/init_deck.py task --mode editable
python scripts/run_deck.py task/job.json task-output --check
python scripts/run_deck.py task/job.json task-output
```

生成器默认是 `image` 模式；可编辑任务明确指定 `--mode editable`。默认读取 `page-spec.json` 和 `scene.json`，可用 `--page-spec` / `--scene` 指定其他名称。`--output` 默认 `job.json`，已存在时拒绝覆盖；也不会修改图片状态、内容或风格确认。配置生成后仍可能以退出码 1 提示缺图或待确认：修复输入后对已生成配置再次运行 `--check`，无需重复生成。数据依赖和外部证据字段按任务需要自行补充，不自动推断。

预检逐页收集缺图、图片状态、规格/素材/页序/讲稿、工作目录和渲染环境问题。它不编译、不渲染，也不产生验收通过。Windows 环境检查读取程序路径及 PowerPoint 注册信息；这不能保证 Office 启动成功，仍需真实渲染。`--check`、`--status` 不能与执行/刷新参数混用。预检不写工作目录，结果显示在标准输出。

```json
{
  "version": "1.0",
  "mode": "editable",
  "page_spec": "page-spec.json",
  "scene": "scene.json",
  "backend": "auto",
  "width": 1600
}
```

`mode` 为 `image` 时省略 `scene`，Page Spec 的图片必须 approved。`editable` 接受 approved 图片或 revision 历史参考图，并按 Scene 编译。可选字段：`visual_review`、`observations`（非空路径数组）、`chart_observations`、`data_bindings`。指定外部审阅文件时只读取它们，不覆盖。配置只接受以上字段。

```bash
python scripts/run_deck.py task/job.json task-output --status
python scripts/run_deck.py task/job.json task-output
python scripts/run_deck.py task/job.json task-output --stop-after build
python scripts/run_deck.py task/job.json task-output
```

首次运行检查输入、编译、渲染并生成当前哈希绑定的待审模板。查看 `review.png`，实际审查后填写 `visual-review.json` 和 `content-observations.json`，再运行同一条命令。数据页还需逐项记录数值、标签、单位、几何/对齐和实际数据对象清单。模板字段与规则见 [交付评估](evaluation.md)；图表端点审查见 [图表可靠性](chart-reliability.md)。缺失、失败和待审项会集中进入 `summary.json` 的 `actions` 和 `summary.md`。

摘要和待办采用中文，保留稳定的英文 `status` / `kind` 供脚本使用。页级待办提供页码、稳定 ID、记录文件和当前渲染路径；错误保留原始诊断。`timings_seconds` 记录输入检查、编译/对象检查、渲染/模板准备和评分阶段的真实工具用时，不包括材料准备和人工审阅。指定阶段停止只表示已保存检查点，不表示完整交付通过。

核对总览的缩略页按实际画幅适配，竖版页面不会缩进固定横向框；文字较密时仍需查看待办链接的原尺寸渲染图和源图片。

| 状态 | 含义 | 退出码 |
|---|---|---|
| complete | 本次声明的检查全部通过 | 0 |
| stopped | 已保存指定阶段，可继续 | 0 |
| ready | 只读输入和缓存诊断 | 0 |
| awaiting_review | 缺失或待审证据 | 3 |
| failed / blocked | 检查失败或输入/工作目录不合法 | 1 |

`--stop-after` 可选 validate、build、render。`--status` 不执行检查阶段，不产生新通过结论；其中 `last_summary` 是历史结果。输入被拒绝时，以命令输出的 blocked 为准，旧摘要不是当前交付证据。

## 恢复与变更

2.15.0 起，可编辑任务编译后生成[原生文字溢出预警](text-layout.md)，待办定位页码、元素和表格单元格。渲染后链接当前画面；实际审阅通过后不重复待办，估算仍保留。预警不自动改变文字或字号，没有明显估算风险也不能替代真实渲染。

2.14.0 起，使用默认工作目录审阅记录时，会生成 [离线审阅面板](review-panel.md) `review-panel.html`，入口在摘要内。逐页看图并填写后下载记录，用 `review_panel.py ... --import-record` 导入，再运行原命令评分。外部审阅/观测保持只读，不提供面板编辑。导入后是待重新评分；阶段计时不含面板生成与人工填写。

- 工作目录只允许为空或由同一配置拥有；进程锁防止并发写入，进程退出后自动释放。检查点通过原子替换保存，损坏状态需保留并换用新工作目录。
- 编译产物、图片和输入均核对 SHA-256。渲染缓存按页绑定规格、Scene、源图、素材、顺序、画布、样式、宽度、脚本版本、数据契约及实际渲染后端。缓存缺失或损坏会重建。
- 修改一页时重新编译整个 PPTX，只渲染受影响页面；其余页面仅在输入和图片哈希一致时复用。有效的已记录审阅逐页迁移，修改页回到 pending。讲稿变更会重新编译并审查讲稿，可复用未变的画面。
- 整套评分每次重新计算，旧评分卡先归档，不沿用旧通过结果。`review-history` 保留被替换的审阅和评分记录。状态哈希用于检测损坏，不是数字签名，也不认证审阅者身份或原始事实。
- PowerPoint 直接按页导出；LibreOffice 仍转换整套 PDF，再只栅格化所需页。后端切换时全部页面重渲染，避免混合不同后端的旧画面。
- 字体文件、Office 和系统环境未自动做指纹。更换字体或渲染环境后，运行 `--refresh-render` 强制刷新全套画面和审阅。工具升级通常也会使旧缓存失效。

输出包括 `cache/*.pptx`、`cache/*.png`、`render-report.json`、`review.png`、`object-audit.json`（可编辑模式）、审阅模板、`scorecard.json`、`summary.json` 和 `summary.md`。具体 PPTX 路径以当次摘要的 `deck` 为准。缓存保留历次版本，不自动删除任务材料。

示例配置 [examples/data-update/job.json](../examples/data-update/job.json) 需要先补齐示例图片并完成确认。首次缺图会明确报 blocked；占位路径不能构成交付通过证据。
