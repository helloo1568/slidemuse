# 可恢复的图片制作

S5 中已确认的 Page Spec 是页面文字、数据、素材和最终坐标的唯一来源。`produce` 补齐宿主生图与现有 `run` 交付流水线之间的原图登记、证据合成和逐页审阅；它不调用生图，也不填通过记录。

```sh
python slidemuse.py produce prepare work/page-spec.json
python slidemuse.py produce compose work/page-spec.json --slide s01 --source work/raw/01.png
python slidemuse.py produce review-init work/page-spec.json --slide s01 --record work/reviews/s01-v1.json
# 实际看图、对照来源后填写记录
python slidemuse.py produce accept work/page-spec.json --slide s01 --record work/reviews/s01-v1.json
python slidemuse.py produce status work/page-spec.json
```

宿主生成页面时把 `preserve_asset.region` 留作证据位置，按原有宿主工具规则生图；本工具将已确认原图按当前区域等比合成。生成提示必须说明这些位置保持空白。合成前后仍须检查周边文字是否被覆盖，像素相同不能证明地图标签读得清。精确素材哈希改变、区域重叠、画幅不符和越界均拒绝提交。

prepare 为每页保存 `prompt_snapshot`，包含当前风格、语义、逐字可见清单和留白区域。路径相对于制作状态目录；宿主读取此文件再调用自己的生图能力，无需临时脚本拼接提示。`generation_prompt` 等已有规格提示作为页面内容一并保留，区域和可见清单以当前规格为准。

每份规格对应同目录的 `.page-spec-production/`（名称随规格文件名变化），保存 `state.json`、只追加的内容寻址原图/成品/意图/审阅快照，以及自动生成的 `status.md`。当前阶段以该状态和 Page Spec 为准，`deck-spec.md` 保留需求与历史叙述，不能把旧的“待确认”段落当作当前状态。首次迁入已有任务不会自动批准旧图，须登记原图并重审。

重复 prepare/compose 不重置未变化页面的批准状态。改变单页内容或素材区域只使该页回 pending；改变整套风格或内容版本会影响全部页。状态文件原子提交后才更新成品文件和 Page Spec 的 `image_status`；写入中断时重跑 prepare 恢复已提交投影。旧成品快照保留，修改和失败不会删去历史。`status` 只读，prepare 才同步当前状态。

只改 `speaker_notes` 或工作备注保留图片批准，重新导出 PPTX/讲稿后核对备注即可；图片审核不认证讲稿。完整输入规格仍由下游流水线检查，因此旧导出不会据此自动沿用。

坐标修改直接改 Page Spec，或使用以下受检入口，不再维护第二份生产坐标表：

`region` 同步该元素的 `bbox_hint`，避免后续重建仍用旧提示坐标。提示快照把当前保护区单独列出，旧 `generation_prompt` 仅作参考，其中旧坐标不能覆盖当前规格。

```sh
python slidemuse.py produce region work/page-spec.json --slide s01 --element map --region 70 205 940 702
python slidemuse.py produce compose work/page-spec.json --slide s01 --source work/raw/01.png
```

成品尺寸与原图尺寸分别记录。默认拒绝放大，确需统一输出尺寸时显式加 `--allow-upscale`；状态保留 `upscaled: true`，不能宣称原生高清。该开关是制作选择，不增加用户确认步骤。工具计时 `compose_seconds` 仅表示本地合成时间，不能代替生图或审阅时间。

原始临时文件丢失时，`--source` 可指向当前页或其历史记录中哈希仍匹配的 `source_snapshot`，直接用归档原图重做合成；不能把旧合成成品再次当作生成原图。

审阅记录绑定当前页面意图和图片哈希，初始化保留空文本、空观察、pending 和空审阅者。填写实际转录、实际查看尺寸、审阅者及五类观察：语义覆盖、来源准确、可读性、有效信息密度、视觉关系；每项定位到元素 ID 或 `page`。同一 Agent 制作和审阅可以如实记录，但不能声称独立盲评。文字匹配只做遗漏筛查；事实、空间关系、数字口径及画面可读性仍须看图和查源。不得从预期文本批量生成观察或批准。

全部页面通过后沿用 `init` / `run` 完成组装、真实渲染和交付检查，produce 的批准不等于 Office 渲染通过。
