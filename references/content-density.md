# 内容密度与画面验收

S1 确定内容密度、S5 校准代表页或 S6 核对内容保留时读取。目标是保留结论、证据和解释，同时在目标展示尺寸读得清。代码只检查声明完整性、文字覆盖和文件一致性，不证明论证成立或数据真实。

## 页面内容

普通内容页默认 3–5 条有区别的支撑要点，每页声明 `role`、`core_message`、`key_points`、`explanation`；必要限制写 `boundary`。来源只作为 `source_refs` 记录供追溯，不要求出现在页面上。设计提案和合成示例仍需在内容中明确标注，不伪装成实验结果。

`density` 可显式覆盖默认，所有例外需要 `reason`：

| mode | 支撑要点数量 | 使用条件 |
|---|---|---|
| `standard`（默认） | 3–5 | 普通概念、方案、结果、对比内容页 |
| `evidence-led` | 1–5 | 图表/表格/真实截图承担比较；写清图中关系和数据口径 |
| `brief` | 1–2 | 一个完整而聚焦的结论；必要证据和边界仍可见 |
| `detailed` | 3–8 | 明确需要的密集对照/查阅页；写清用途并验证小字可读 |

封面、目录、过渡、小结、问答按作用处理，不强制要点配额。例外理由不能授权添加新事实或绕过看图。脚本可发现完全重复及标点/大小写不同的条目；同义重复、口号和无依据因果仍需语义自检。

按页型检查：数据页包含数据口径、比较和结论边界；路线页包含输入输出、步骤关系和必要约束；对比页包含相同口径、比较维度和选择理由；概念页包含定义和具体例子。不是所有流程都有分支，不为检查发明失败路径。

## 在两个后端传递同一份内容

新材料的 Page Spec 声明顶层 `content_policy: "1.1"`，自动执行内容和流程记录校验；也可执行：

```sh
python slidemuse.py validate work/page-spec.json --strict --content
python slidemuse.py generate prepare --page-spec work/page-spec.json --out-dir work/generated
python slidemuse.py rebuild --offline prepare --page-spec work/page-spec.json --job-dir work/rebuilt
```

生成适配器把已确认文本、解释、边界和语义元素放入每页提示及 `slidemuse-content.json`；来源记录保留在 Page Spec，不进入可见文案。源图片尚未生成时只准备生成任务；重建适配需要批准图片，保存 `slidemuse-page-content.json`，`rebuild page-prompt` 将对应页原文、数据和稳定 ID 带入提示。后端 Manifest 的坐标、曲线和素材格式保持原样。直接图片重建仍可用既有入口。

含 `preserve_asset` 的精确证据继续走 Page Spec 生产和像素核验路线；生成适配器拒绝把它交给生图重绘。旧稿缺字段仍可读取，不追溯认证；新任务不能借旧兼容入口跳过检查。

## 代表页校准与成品检查

多页制作先选信息量有代表性的内容页（复用实际成品页），不只看封面：

- 内容：结论、关键数字、解释和必要边界出现在图片中，图表支撑文字；来源不上页面。
- 阅读：按预期投影/屏幕尺寸检查正文和标签；不靠缩字、满版挤排解决过载。
- 布局：证据页把空间留给真实结果和比较；效果图/插画有清楚的解释作用，不挤走证据。
- 密度：不足时补有依据的比较或解释、合并页面；过密时分层或在授权页数内重新分配，不能添加无依据条目。

不设固定图文百分比或通用字数。代表页校准沿用既有内容/风格授权，不增加确认步骤。

有效密度看每个区域提供了什么新信息。原图已包含案例注释时，正文解释比较或局限，避免再抄一遍同样的案例清单。地图和图表优先检查目标尺寸下的地名、图例、坐标和单位；必要时从原始数据导出适合投影的版本或制作有记录的局部放大图，归档原始证据，写明裁切/重绘及来源，不能默默改变证据。

## 语义与页面文字分开

1.1 按标题、已确认的文字元素与 `required_visible_values` 逐字核对。结论、解释和边界可用批准的文字和图形表达。需要记录承载关系时，可声明 `display.coverage`，把 `core_message`、`key_points/0`、`explanation`、`boundary` 等语义映射到已确认的 `element_ids`。声明映射时覆盖该页全部语义；多个论点可由同一张图表达。旧规格中有效的 `source_refs/N` 映射仍可读取，来源保留作内部记录。1.0 与旧规格在无显式映射时继续沿用原逐字规则。

```json
"display": {"coverage": [
  {"claim": "core_message", "element_ids": ["comparison-chart", "takeaway"]},
  {"claim": "key_points/0", "element_ids": ["comparison-chart"]},
  {"claim": "explanation", "element_ids": ["denominator-caption"]}
]}
```

这是字段示意，实际列表必须覆盖该页全部语义路径。采用该合同后，逐字可见清单由标题、确认的 text 元素和 `required_visible_values` 组成；语义字段保留完整传递给后端及人工审阅，不再强迫把它们各抄一遍。关键数字、单位和必须出现的边界措辞仍写入实际 text 元素或 `required_visible_values`。`produce` 的 `semantic_coverage` 审阅逐项核对映射是否成立，不能靠填写映射绕过内容确认。

生成后端观察记录绑定当前内容、提示和图片：

```sh
python slidemuse.py generate review work/generated --init
python slidemuse.py generate review work/generated
```

先实际看图，再填写 `content-review.json` 的 `observed_text` 和 `notes`，将 `evidence_accuracy`、`readability`、`density`、`visual_relationships` 逐项记为 pass/fail。初始化保留空文本和 pending，不能复制预期清单充当观察。检查拒绝漏字、待审和失效哈希；来源真实性、图表几何及阅读质量仍需对照真实材料判断。

新生成任务须通过该检查才能组装；组装还核对页序、完成状态、精确图片集合、哈希和画幅，逐字节保留嵌入图片及讲稿，失败保留旧 PPTX。旧任务没有内容合同会报告 `legacy_not_checked`，只能说明结构检查，不补造历史通过。

Page Spec 路线沿用 `audit_page_content.py`，按当前规格声明的逐字清单验收。两条路线最终都须真实渲染，分别完成图片观察和 Office 渲染检查。

## 效果验证

单元测试和合成样例验证规则及管道。实际密度提升要用同一真实材料对比内容遗漏、事实错误、目标尺寸可读性、返修次数和成本。未运行生图/真实材料评审前，不宣称成功率提升或耗时下降。
