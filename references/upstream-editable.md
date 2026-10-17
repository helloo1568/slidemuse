# 可编辑重建的上游参考与适配边界

在 S6 直接重建现有页面、估计文字尺寸、拆分独立素材或处理带合并单元格的表格时按需读取。

参考项目：[ningzimu/image-to-editable-ppt-skill](https://github.com/ningzimu/image-to-editable-ppt-skill)。2026-10-16 核对的版本为 `b7be494e31a0ed56ef98716891db5474606b8cdf`。重点参考 `references/page-decision-tree.md`、`references/manifest-schema.md`、`cli/editppt/runtime/native_tables.py`（均位于上游 `skills/image-to-editable-ppt/`）。Scene 路线按 Scene v1 和 python-pptx 适配；上游完整运行能力另通过[完整重建后端](editable-backend.md)统一接入。

## 测量文字，保留原文

直接还原任务以源图像素为坐标基准。优先复用已有 OCR/文字框测量，记录文字框、字形高度、字体候选和低置信度项；结合原图检查误框、漏检、同级字号与换行。字形像素高度不等于 PowerPoint 的 pt 字号，不能把 OCR 框高直接填入 `font_size`。选一段清晰文字校准后实际渲染，再将相同层级应用到其他文字。

已有 Page Spec 的文字和数字仍以 Page Spec 为准，测量只补充位置与外观，不覆盖内容。不为使用这份参考强制申请 OCR Token；可使用宿主已有视觉能力或可用本地工具，并记录测量限制。完整运行能力现已通过[完整重建后端](editable-backend.md)接入，包括离线文字尺寸提示和可选 OCR；本参考保留 Scene 路线的适配方法。

## 按完整对象拆分素材

优先使用已有透明原始素材。需要 AI 提取时保留源图的形状、边缘、阴影与配色，不自行美化。透明图或素材表应按完整语义对象划定区域；图标中的断开笔画、文字标识和主体应属于同一对象，不能仅按连通域逐块裁开。保持留白以免相邻素材互相污染。

已有 RGBA 和明确区域时使用 `extract_assets.py`，检查 alpha 边缘、断开细节和真实裁切 bbox；该工具不会自动去背。底色残留或主体缺笔时局部修复，不能反复缩 bbox 隐藏问题。不添加强制纯色抠图流程，也不自动调用外部图像服务。

## 原生表格与局部修复

结构清楚且文字可读的规则表格使用一个 `table`，不拆成大量文本框或整张截图。Scene 支持 `row_heights` 正权重和 `merges` 矩形合并；详见 [Scene 协议](scene-format.md)。合并被覆盖位置必须为空字符串，保留所有可见内容于左上角原点；不允许重叠或越界合并。

单页审查失败时只修相关 Scene 元素、表格结构或素材，复用已核验的部分；文字/合并结构不清时先放大原图核对，不猜造值。不通过结构检查的页面不能记作完成，结构通过仍须实际渲染。合并单元格的文字布局估算会标为待视觉核查，不能据此宣称排版已通过。

## License notice

Design and workflow adaptations acknowledge the upstream project above. Its MIT notice is retained here with the distributed reference:

MIT License

Copyright (c) 2026 ningzimu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
