# Page Spec v1：图片生成与可编辑还原的中间契约

[机器 Schema](page-spec.schema.json) · [示例](../examples/page-spec.example.json)

新任务在 `style.visual_spec` 保留可读说明，并填写 `style.tokens`：`palette` 的背景/正文/主色/强调色，`typography` 的中英文实际字体和标题/正文字号，`layout` 的网格、边距与间距，以及 `image_treatment`。`reference_images` 可指向任务目录内已选总览或关键参考页，路径相对 Page Spec；验证器会检查文件。旧任务缺少 `tokens` 仍可读取，恢复时可逐步补齐。

新任务还要为每页写 `slides[].role`（12 种页面类型枚举）和内容页的 `slides[].key_points`（普通内容页默认 3–5 条，密度例外按 content-density.md 声明，与逐页内容稿对应）。这两项与 `tokens` 一样：旧稿和已冻结的示例版缺少时仍可读取，不追溯补写，也不能据此声称旧任务大纲合格。

`page-spec.json` 在内容大纲已确认、视觉方向已锁定后创建。它保存已经知道的准确内容和语义结构，避免 Step 3 从整页图片重新 OCR 或猜测图表数据。

它不是 PPTX 导出场景：位置只允许写 `bbox_hint`，不要求像 Scene 一样精确；最终坐标、原生样式与素材路径仍写入 `scene.json`。

## 生命周期

正式逐页生成使用 `produce request` 单页包；`reference_images` 的选型图留在 Page Spec 中用于授权与校验，不能当成正式单页生图参考。先验收独立代表页作为锚点；后续请求只携带当前页与独立锚点。

1. Step 1 内容确认后，把页序、标题、核心结论、准确文字/数据和来源写入 `deck-spec.md`。
2. 风格锁定后进入 S5，将已确认内容与 `style` 一起写入 Page Spec，再运行验证器；不得提前写入虚假的风格授权。
3. Step 2 每完成一页，记录最终 `image_file`、`image_status`、实际提示词和更新后的布局提示。
4. 交付图片版前使用 `--require-images` 再验证一次，确保所有页面图片存在且状态为 `approved`。
5. Step 3 以 Page Spec 为语义事实源、页面图片为视觉事实源。按[变更与恢复规则](workflow-updates.md)区分已授权修改与未知冲突；仅对未知冲突请求确认，不得静默用 OCR 覆盖已确认内容。

直接还原现有页面时，将 `style.decision` 设为 `locked-reference`，`visual_spec` 写明保持原页，`authorization` 记录用户要求还原原图的指令；低置信度内容按元素标记为 `unresolved`。

## 关键字段

- `content_approved` 固定为 `true`，表示新材料任务的大纲已经确认，或直接还原任务已明确授权保留原页内容；`content_version` 与 `content_authorization` 记录对应版本和用户原话。它不代表每个模糊字符都已确认。
- 新材料用 `content_policy: "1.1"`。在 `workflow` 里记录 `content_mode`、`approved_content_version` 和 `outline_ref`。版本必须和 `content_version` 一致。定位可用消息链接、消息 ID 或可找回的版本和消息描述。
- `workflow.content_mode` 可取 `confirmed`（确认逐页大纲）、`delegated`（明确由 Agent 决定内容并已展示）、`reused`（用户明确沿用既有版本）或 `authorized-revision`（在既有版本上直接应用用户明确指定的局部修改）。沿用或局部修改时，定位可指向历史大纲、锁定页面或已记录的变更对话。
- `style.decision` 记录 `selected`、`locked-reference`、`skipped` 或 `delegated`，并在 `style.authorization` 写用户对风格阶段的原话。1.1 下，四套方案用户选定或授权代选时，还须写 `style.option`（1–4）、`style.choice`（名称）及 `style.tokens.reference_images`（所选预览放首位）。明确锁定模板或明确要求跳过预览时分别用 `locked-reference` 或 `skipped`。
- `slides[].role` 记录页面类型：`cover`、`agenda`、`section-divider`、`concept`、`process`、`comparison`、`timeline`、`data-evidence`、`architecture`、`case-study`、`summary`、`qa`。它描述页面作用，与 `deck-spec.md` 页序表一致；视觉系统仍由风格选择决定。
- `slides[].key_points` 保留该页已确认支撑，逐条与内容稿对应；普通页默认 3–5 条，声明 density 例外后按用途接受 1–8 条非空不重复文本（具体范围见 content-density.md）。要点是论证复杂度的下限，不是凑字数的理由；封面、过渡等页按各自必答内容处理，不强行填满。详见[内容大纲](content-outline.md)。
- `slides[].elements` 使用稳定 ID。准确文字写 `text`，表格/图表原始值写 `data`，来源写 `source_ref`。
- 1.1 的逐字清单由页标题、文字元素与 `required_visible_values` 组成。语义字段保留给生成和人工核对，`source_refs` 与元素的 `source_ref` 保留作追溯。明确需要上屏的引文或来源署名写成文字元素。
- 图表或图片上必须直接读出的数字、日期、单位可加入该页 `required_visible_values`；不要求把未打印在图上的底层图表数据当作可见文字。
- 页面包含总页数（如 `1/10`）、目录总量或依赖整套页数的构图时，设置 `depends_on_slide_count: true`。页数变化会使这些页面重新生成；未设置或为 `false` 时，计划按本页内容、页序和图片是否变化判断是否复用。所有实际可见的页码和总页数也应写入文字元素或 `required_visible_values`，不能只留在提示词里。
- `confirmation_status` 区分用户确认、来源可验证和未解决内容；直接还原中的低置信度文字必须标为 `unresolved` 并记录 `confidence`，不能伪装成已确认。
- `native_intent` 表示 Step 3 期望的输出：`native`、`raster` 或 `either`。
- `bbox_hint` 是 `[x, y, w, h]` 的整页画布坐标提示；它可以在图片页验收后更新，但不能冒充最终 Scene 坐标。
- `separate_asset: true` 表示该视觉对象在可编辑版中需要独立移动或替换。
- `slides[].speaker_notes` 保存已确定的可选讲稿，允许明确空字符串，新材料 1.1 缺失或空字符串均按空备注验收；旧规格缺失仍表示未声明。只有用户要求讲稿或授权保留既有讲稿才填入非空值；`notes` 工作记录不会自动导出。讲稿不参与图片提示/必现文字，但写入图片版 PPTX，重建时沿用到 Scene；见[讲稿保留](speaker-notes.md)。

## 验证

1.1 校验版本、授权记录和所选参考图；用本地工具加标签的预览还会校验图内记录的编号和名称。内容是否完整展示、回复是否明确授权，由 Agent 根据对话核对。旧规格（无 `content_policy` 或 1.0）沿用已有入口和逐字清单，恢复任务时保留原记录。

新材料示例中的授权字段节选：

```json
{
  "content_policy": "1.1",
  "content_approved": true,
  "content_version": "outline-v2",
  "content_authorization": "这版逐页大纲可以继续",
  "workflow": {
    "content_mode": "confirmed",
    "approved_content_version": "outline-v2",
    "outline_ref": "对话中发出的 outline-v2 逐页稿"
  }
}
```

含科研地图、实验截图或精确数据图时，按[证据素材](evidence-assets.md)给对应元素增加 `preserve_asset`：独立源文件路径、SHA256及最终PNG中的整数像素区域。该字段不同于 `bbox_hint`；最终图片检查会核对区域内真实像素，不能用文字“已保留”替代。已有规格要求保留原图的任务须落实该契约，旧稿缺失字段不追认保真。

内容与风格锁定、尚未生成图片时：

```sh
python "<skill-dir>/scripts/validate_page_spec.py" "<work>/page-spec.json" --strict
```

图片版交付前：

```sh
python "<skill-dir>/scripts/validate_page_spec.py" "<work>/page-spec.json" --require-images --strict
python "<skill-dir>/scripts/build_image_ppt.py" "<work>/page-spec.json" "<work>/output/image-deck.pptx"
```

验证器检查 Schema、有限数值、连续页码、唯一 ID、画布边界和不重复的相对图片路径。`--require-images` 还检查批准状态、文件存在性、PNG/JPEG 可读性和 EXIF 校正后的画幅比例（允许单像素取整误差）。`--strict` 拒绝未解决元素；直接还原任务可先不加 `--strict` 以保留低置信度项，但交付前必须逐项说明。验证器不检查图片中的文字是否正确，也不替代逐页视觉验收。

图片构建器以 Page Spec 为输入时会自动执行上述两项严格检查，只导出 `slides` 中声明的图片，并继承列表顺序与 `canvas` 比例。可指定 `--width` 或 `--height` 改变物理尺寸；同时指定两者时必须保持该比例。直接传图片目录仍使用旧版自然排序模式，仅适用于没有 Page Spec 的独立合并任务。

## 图片页内容核对

宿主看图或使用其已有识别能力后，可把观察到的文字填入哈希绑定模板。单页示例：

```sh
python "<skill-dir>/scripts/audit_page_content.py" "<work>/page-spec.json" "<work>/observations-s02.json" --init --slide s02
```

将 `observed_text` 填为图片中实际可见的文字，完整转录后把 `status` 从 `partial` 改为 `complete`。再运行：

```sh
python "<skill-dir>/scripts/audit_page_content.py" "<work>/page-spec.json" "<work>/observations-s02.json" --slide s02 --require-complete --output "<work>/content-audit-s02.json"
```

脚本对照已确认文本及 `required_visible_values`，标出缺失文字、数字和单位。图片文件变化会使旧观察记录失效；`partial` 不能通过完整核对。识别结果只是检查证据，不能覆盖 Page Spec。图表/表格中未明确要求显示的底层数据和识别漏字仍需人工检查。

新材料使用 `content_policy: "1.1"`，将内容页的解释和必要边界写入 `explanation`、`boundary`。旧规格可沿用原策略。`validate --content` 可强制检查页面类型和内容密度。后端传递及看图检查详见[密度规则](content-density.md)。
