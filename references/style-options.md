# 四套风格预览

仅 S3 读取。风格阶段只负责让用户看到四套视觉方向，不执行结构校验、布局哈希或逐张验收。

## 每套预览的内容

每套默认一张独立风格卡，用配色、字体气质、材质、留白和图形语言体现方向；可以只用示意标题及少量占位，不承诺版式或事实。四套围绕同一主题以便比较。不要求页数、网格、尺寸或 16:9，也不因这些细节有偏差而重生。只有无法辨认风格或两套明显难以区分时，才处理相关方案。

## 生成与展示

- 必须实际调用已获授权的生图模型并保留原件与调用证据；禁止将程序绘制、模板排版或其截图作为新生成的风格预览。无可用生图能力时报告阻塞。

- 每套一次生图，一次输出一张风格预览；四套正常共四次。不要逐页生成高清图，也不要默认“先长图、再生图改排版”。
- 单套有瑕疵时继续生成其余方案，只处理有问题的编号。画幅有偏差但视觉方向清楚的图可标为“风格参考”，选中后以正式代表页校准。
- 生成前分配固定的 01–04 和简短名称。重试沿用原编号和名称。保留生图原件，最终用标有编号、名称的图供用户选择。
- 用 `style-overview --compare` 将四张已标号的图按 01–04 排成 2×2。在同一条消息给出一份对比预览，并列四个编号、名称和各自的一句特点。生图返回次序和附件卡片次序都可能变化，按图上的编号选。若支持聊天内嵌图，直接展示 PNG。
- WorkBuddy 使用下方命令，输出任务目录下的 `styles/compare-4-styles.png` 和同名 HTML。把返回的 `html_preview` 绝对路径放在 `present_files.files` 第一项，把 PNG 放在第二项，两项单独调用。项目钩子会核对 HTML 与备用 PNG 一致，并检查 `previewed` 是否对应这份 HTML。若面板未确认打开，按钩子给出的消息指向同一张 PNG。若备用附件也未挂上，单独给出 PNG 卡片。用户明确选定图或编号后继续制作。
- 用户以附件选款时锁定该图，数字有歧义时结合图和名称确认。选定后在 `style.option`、`style.choice` 和 `reference_images` 记录编号、名称及所选单套预览图。
- 风格选定后才进入逐页高清制作。

```sh
python slidemuse.py style-overview --compare styles/01.png styles/02.png styles/03.png styles/04.png styles/compare-4-styles.png --html
```

这里的 `01.png` 等为 `--option` 和 `--name` 已标注的图。PNG 和 HTML 复用已有图像，合成过程不调用生图。HTML 内嵌 PNG，可离线打开。后续 `style-reference` 仍用选中的独立图。

## 从选中图保留真实视觉参考

选中的预览是正式页面的视觉基准。完整六宫格不作为单页生图输入，但不能因此把全部视觉参考丢掉、仅凭风格名称或几句文字重新设计。

先查看已选 `style.tokens.reference_images[0]`。如果是独立风格卡，直接登记原像素；如果一张图包含多个版面，选一个连续、足以表达风格的区域，记录实际像素框，不发整个多页总览。局部不要求包含整页、完整文案，也不要求标准比例。不拉伸、不猜网格。

```sh
python slidemuse.py style-reference work/page-spec.json --style-sample --output styles/02-reference.png
# 如果所选图片确实是多画面总览，改用实测框：
python slidemuse.py style-reference work/page-spec.json --box 100 150 458 373 --output styles/02-reference.png
```

相对输出路径按 Page Spec 所在目录解析。工具记录 `style.generation_reference` 的所选源图、源哈希、裁切框、参考图和参考哈希，并把派生文件加入参考依赖。它不调用模型、不重新绘图，也不把低分辨率参考放大成正式页。选定方案或源图片变化后必须重新登记，不复用旧声明。用户已明确锁定独立单页时直接使用其真实图片；需要归档规范化副本可用 `--single-page`，不得对六宫格声明单页。

主 `produce request` 与完整后端 `generate prepare --page-spec` 共用这一参考。每个正式请求都携带当前页和同一选型基线，实际调用时附上返回的风格参考图；后续已有成品不能悄悄替代原选型。宿主不能附参考图时说明限制，使用已授权且真正支持附图的方式，不静默退成纯文字生成。

先完成一张有代表性的正式页，与选中图并排检查配色、字体层级、背景材质、图形语言、留白和版式节奏。`style_consistency` 记录真实观察和参考身份；风格偏移先修这页，未通过不得扩散到后续页。内容不同可以调整具体位置，不能换成另一套设计。此校准执行已有风格选择，不要求用户重新选型。正式页仍须由真实生图生成到目标画布，裁下的缩略图不能直接交付。

## 本地重排

用本地工具给总览加标题，按原比例缩放并保留全部内容。原图另存。工具同时把编号和名称写入 PNG，Page Spec 校验会比对所选图的标签。

```sh
python "<skill-dir>/scripts/build_style_overview.py" "<work>/styles/02-original.png" "<work>/styles/02-建筑图册.png" --option 2 --name 建筑图册
```

原图较大或交付要求 4K 预览时，可在加标签的命令中指定 `--width 3840`。输出报告中的 `pixels` 是成品画布尺寸，`source_pixels` 是原图尺寸。较小的原图保持原始像素并居中留白；更大的画布不代表生图模型生成了原生 4K。

只有总览排列、裁切或尺寸明显错误时，才用 `build_style_overview.py` 重排已有图片，不重新生图。工具固定 3×2、16:9，最多 6 页；可输入单页图或明确裁切框。

如果只有长图或旧总览，先查看图片，手动记录每张完整页面的像素裁切框 `[x, y, width, height]`（EXIF 校正后的坐标），不要按等分高度猜测带间距的长图。框内必须保留全部文字、图表和页脚。

在任务目录保存如下 `overview-layout.json`，其中坐标仅为格式示例，执行前换成实测值：

```json
{
  "title": "02 · 建筑图册",
  "width": 1600,
  "height": 900,
  "slide_aspect_ratio": [16, 9],
  "require_native_aspect": true,
  "slides": [
    {"slide_id": "s01", "file": "styles/initial.png", "box": [0, 0, 1600, 900], "label": "01"},
    {"slide_id": "s02", "file": "styles/initial.png", "box": [0, 920, 1600, 900], "label": "02"},
    {"slide_id": "s03", "file": "styles/initial.png", "box": [0, 1840, 1600, 900], "label": "03"}
  ]
}
```

已有独立单页文件时省略 `box`。可用 `font` 指定已安装字体路径。路径相对布局 JSON，必须在其目录范围内。工具拒绝覆盖源图，输出存在时默认拒绝覆盖，使用新版本文件名或明确传 `--overwrite`。

```sh
python "<skill-dir>/scripts/build_style_overview.py" "<work>/overview-layout.json" "<work>/styles/01-sorter-local.png"
```

输出后直接看图。重排后的总览也可用相同命令加编号和名称。选定风格后，S5 先用信息密度有代表性的实际页面完成一次目标画幅校准，检查正文、地图/图表标签、边距与页脚；该页计入正式页数。
