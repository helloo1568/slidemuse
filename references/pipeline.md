# 可恢复的交付流水线

`run_deck.py` 面向已完成内容、风格和图片确认的 Page Spec，以及已准备好的 Scene。内容提炼、生图与用户确认仍由宿主 Agent 按 SKILL 状态机完成。流水线不自动生成图片，也不自动填写通过结论。

把 `job.json` 放在任务材料目录，工作目录另建在旁边。所有配置路径相对于 `job.json`，不能越出其所在目录。

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

| 状态 | 含义 | 退出码 |
|---|---|---|
| complete | 本次声明的检查全部通过 | 0 |
| stopped | 已保存指定阶段，可继续 | 0 |
| ready | 只读输入和缓存诊断 | 0 |
| awaiting_review | 缺失或待审证据 | 3 |
| failed / blocked | 检查失败或输入/工作目录不合法 | 1 |

`--stop-after` 可选 validate、build、render。`--status` 不执行检查阶段，不产生新通过结论；其中 `last_summary` 是历史结果。输入被拒绝时，以命令输出的 blocked 为准，旧摘要不是当前交付证据。

## 恢复与变更

- 工作目录只允许为空或由同一配置拥有；进程锁防止并发写入，进程退出后自动释放。检查点通过原子替换保存，损坏状态需保留并换用新工作目录。
- 编译产物、图片和输入均核对 SHA-256。渲染缓存按页绑定规格、Scene、源图、素材、顺序、画布、样式、宽度、脚本版本、数据契约及实际渲染后端。缓存缺失或损坏会重建。
- 修改一页时重新编译整个 PPTX，只渲染受影响页面；其余页面仅在输入和图片哈希一致时复用。有效的已记录审阅逐页迁移，修改页回到 pending。讲稿变更会重新编译并审查讲稿，可复用未变的画面。
- 整套评分每次重新计算，旧评分卡先归档，不沿用旧通过结果。`review-history` 保留被替换的审阅和评分记录。状态哈希用于检测损坏，不是数字签名，也不认证审阅者身份或原始事实。
- PowerPoint 直接按页导出；LibreOffice 仍转换整套 PDF，再只栅格化所需页。后端切换时全部页面重渲染，避免混合不同后端的旧画面。
- 字体文件、Office 和系统环境未自动做指纹。更换字体或渲染环境后，运行 `--refresh-render` 强制刷新全套画面和审阅。工具升级通常也会使旧缓存失效。

输出包括 `cache/*.pptx`、`cache/*.png`、`render-report.json`、`review.png`、`object-audit.json`（可编辑模式）、审阅模板、`scorecard.json`、`summary.json` 和 `summary.md`。具体 PPTX 路径以当次摘要的 `deck` 为准。缓存保留历次版本，不自动删除任务材料。

示例配置 [examples/data-update/job.json](../examples/data-update/job.json) 需要先补齐示例图片并完成确认。首次缺图会明确报 blocked；占位路径不能构成交付通过证据。
