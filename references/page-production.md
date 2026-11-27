# 可恢复的图片制作

## 独立单页请求与来源记录（2.28.0）

先按已确认内容与风格建立 Page Spec，选一个有代表性的内容页作校准（无内容页时用封面）。每次实际生成前运行：

```sh
python slidemuse.py produce request work/page-spec.json --slide s02 --route host
```

输出中 `state` 的同目录下，当前页的 `request_snapshot` 是唯一正式单页提示包；其包含当前页、锁定视觉规范、准确上屏文字和保护区，不包含预览图片、旧生成提示、其他页面或工作备注。首次没有已批准单页时，用文字视觉规范校准；生成、合成、实际看图并 accept 后，再请求后续页。若存在已批准页，`request_reference` 是独立全尺寸单页的绝对路径（优先内容页），仅作风格锚点，不复用其中的文本或构图。不要再传预览总览。用户明确锁定单页参考时，可按授权和工具能力用于首次校准。

`--route` 必须是真实方式：`host` 当前宿主，`fresh-host` 真正独立的新宿主会话，`isolated-worker` 独立子代理，`isolated-api` 已授权 API 单张请求。选择方式不代表调用已发生；宿主无法隔离时不得伪称使用了新会话或子代理。按真实工具规则执行；有参考参数则只传返回的单页锚点。

每次调用失败后保留原件/错误，登记真实证据：

```sh
python slidemuse.py produce failure work/page-spec.json --slide s02 --route host --failure-kind multi-page --evidence "真实工具结果或错误定位"
```

失败类型：`multi-page`、`style-drift`、`text`、`chart`、`tool-error`、`other`。同页同方式连续两次同类失败后，该方式不能再 request；切换真正不同且获授权的方式，或报告阻塞。文本/图表按原有局部修正规则处理。失败记录不自动证明调用真实性，不自动批准图片。不得把拼图裁切或程序整页绘制当成品。

S5 中已确认的 Page Spec 是页面文字、数据、素材和最终坐标的唯一来源。`produce` 补齐宿主生图与现有 `run` 交付流水线之间的原图登记、证据合成和逐页审阅；它不调用生图，也不填通过记录。

新增页面传给 `compose --source` 的原图必须来自真实生图调用。每次成功调用后，将实际来源保存为 JSON，使用 `--generation-record` 一并登记：

```json
{
  "version": "1.0",
  "slide_id": "s01",
  "request_sha256": "本次 request 输出的 request_sha256",
  "source_sha256": "实际生成原图文件字节的 SHA-256",
  "backend": "实际使用的工具或后端",
  "model": null,
  "result_ref": "可找回的实际调用 ID、结果 ID 或结果文件定位"
}
```

以上是字段说明，哈希与定位必须替换为本次真实结果。`model` 填实际模型名；宿主未暴露时使用 `null`，不能猜测。记录不含密钥、Token 或授权头。工具将记录与独立请求、原图字节绑定并归档；缺少记录或哈希不符会阻止合成、批准与新材料导出。这些检查保证记录一致，不能认证提供商签名或代替实际调用。不得将 SVG、HTML、Python、程序化 PPTX 或其截图登记为模型生成原图。允许以真实生成的完整主视觉为基础局部修正文字、精确数据图表及证据素材。

```sh
python slidemuse.py produce prepare work/page-spec.json
python slidemuse.py produce request work/page-spec.json --slide s01 --route host
# 按请求实际调用生图工具，保存原图和真实调用记录
python slidemuse.py produce compose work/page-spec.json --slide s01 --source work/raw/01.png --generation-record work/calls/s01.json
python slidemuse.py produce review-init work/page-spec.json --slide s01 --record work/reviews/s01-v1.json
# 实际看图、对照来源后填写记录
python slidemuse.py produce accept work/page-spec.json --slide s01 --record work/reviews/s01-v1.json
python slidemuse.py produce status work/page-spec.json
```

宿主生成页面时把 `preserve_asset.region` 留作证据位置，按原有宿主工具规则生图；本工具将已确认原图按当前区域等比合成。生成提示必须说明这些位置保持空白。合成前后仍须检查周边文字是否被覆盖，像素相同不能证明地图标签读得清。精确素材哈希改变、区域重叠、画幅不符和越界均拒绝提交。

prepare 为每页保存 `prompt_snapshot`，包含当前风格、语义、逐字可见清单和留白区域。正式调用前运行 request 并读取其 `request_snapshot`，使调用记录对应唯一请求。路径相对于制作状态目录，无需临时脚本拼接提示。已有 `generation_prompt` 保存在规格与意图记录，不转发到独立请求，以避免旧预览指令污染；区域和可见清单以当前规格为准。

每份规格对应同目录的 `.page-spec-production/`（名称随规格文件名变化），保存 `state.json`、只追加的内容寻址原图/成品/意图/审阅快照，以及自动生成的 `status.md`。当前阶段以该状态和 Page Spec 为准，`deck-spec.md` 保留需求与历史叙述，不能把旧的“待确认”段落当作当前状态。首次迁入已有任务不会自动批准旧图，须登记原图并重审。

重复 prepare/compose 不重置未变化页面的批准状态。改变单页内容或素材区域只使该页回 pending；改变整套风格或内容版本会影响全部页。状态文件原子提交后才更新成品文件和 Page Spec 的 `image_status`；写入中断时重跑 prepare 恢复已提交投影。旧成品快照保留，修改和失败不会删去历史。`status` 只读，prepare 才同步当前状态。

删除页面后运行 prepare，会把该页完整制作记录移入 `archived_pages`，保留原件、调用、局部修正和审阅关联。恢复相同稳定页 ID 时，工具先校验快照：合同未变则恢复原状态；合同已变则回 pending 并保留历史供重新合成或局部修正。数据更新草稿也复制这些归档及所需快照、历史意图声明的保护素材和风格参考，不依赖旧项目目录。保护素材必须与其原声明哈希一致；历史文件已丢失、被替换或与草稿现有文件冲突时拒绝发布草稿，保留原项目供恢复，不用当前同名素材冒充旧版本。

只改 `speaker_notes` 或工作备注保留图片批准，重新导出 PPTX/讲稿后核对备注即可；图片审核不认证讲稿。完整输入规格仍由下游流水线检查，因此旧导出不会据此自动沿用。

坐标修改直接改 Page Spec，或使用以下受检入口，不再维护第二份生产坐标表：

`region` 同步该元素的 `bbox_hint`，避免后续重建仍用旧提示坐标。提示快照把当前保护区单独列出，旧 `generation_prompt` 仅作参考，其中旧坐标不能覆盖当前规格。

```sh
python slidemuse.py produce region work/page-spec.json --slide s01 --element map --region 70 205 940 702
python slidemuse.py produce compose work/page-spec.json --slide s01 --source work/raw/01.png
```

成品尺寸与原图尺寸分别记录。默认拒绝放大，确需统一输出尺寸时显式加 `--allow-upscale`；状态保留 `upscaled: true`，不能宣称原生高清。该开关是制作选择，不增加用户确认步骤。工具计时 `compose_seconds` 仅表示本地合成时间，不能代替生图或审阅时间。

原始临时文件丢失时，`--source` 可指向当前页或其历史记录中哈希仍匹配的 `source_snapshot`，直接用归档原图重做合成；不能把旧合成成品再次当作生成原图。

同一已记录原图做获授权的区域修改时，沿用该原图的既有调用记录，不重复调用模型，也不伪造新调用。更换原图必须提供对应的新请求与新记录；局部修改后的成品仍需重新看图和批准。

## 登记准确文字与局部修正（2.29.0）

Prompt 2A 叠字、局部数字修正等操作，先保留真实生图原件并完成 compose，再把局部处理结果保存为**独立的不透明 PNG**，尺寸与当前画布一致。保留处理时使用的原图或成品，不覆盖 `image_file`，然后登记：

```sh
python slidemuse.py produce refine work/page-spec.json --slide s01 --base-image work/slides/01.png --source work/corrections/01.png --operation "按已确认 Page Spec 叠加准确标题和数字，保留主视觉"
python slidemuse.py produce review-init work/page-spec.json --slide s01 --record work/reviews/s01-v2.json
# 实际查看修正后页面，核对文字、主视觉与来源，再填写新审阅记录
python slidemuse.py produce accept work/page-spec.json --slide s01 --record work/reviews/s01-v2.json
```

`--base-image` 必须与同页当前或历史中保存的原始生图/合成成品完全一致；也可直接使用状态中的相应快照路径。工具保留真实原件和调用绑定，另行归档局部处理输入、提交的 PNG、处理说明和最终图片哈希。修正成品回到 `generated`，旧审阅不能复用；保护素材像素发生变化时拒绝登记。内容修订让页面回 pending 后，也可基于该页已有历史图片进行已授权的局部处理。

修改画布后，工具根据保留原件和实际基图像素判断是否发生放大；新增放大默认拒绝，确需处理时显式添加 `--allow-upscale` 并记录 `upscaled: true`。此前已允许放大的成品，在不增加目标尺寸的后续局部修正中沿用该选择，继续保留放大标记；不能把原始低分辨率图片的派生成品称为原生高清。

`refine` 记录处理声明和文件之间的绑定，不能自动证明修改范围、调用真实性或画面质量；真实原件与结果仍须核对。不得用它将程序绘制整页冒充生图，也不把局部处理另记为一次模型调用。未登记而直接改写最终图片时，review-init 会拒绝并保留该文件；需要恢复已提交成品时运行 prepare。

## 旧任务与既有图片

升级已有 v2.27 制作任务时，若 state 或 history 已共同保留原始 request、route 和 source，可直接给该原图补 `--generation-record`，使用历史请求的原始 SHA-256 与真实历史调用定位；工具不重写旧请求，补证后回到 `generated`，需要重新 review/accept。没有保留实际 request 时，先从可信备份恢复；无法恢复则保留旧目录，在独立新项目中沿用已确认内容并真正重新生成。不能把旧图绑定到刚创建的新请求来补造证据。

用户提供的既有图片走直接导入路径：每页声明 `image_origin: {"kind": "provided", "source_ref": "实际输入或授权定位", "sha256": "图片文件 SHA-256"}`，核对后将 `image_status` 设为 `approved`。这类页面可以与新生成页面共存，不要求补造生图记录。已有生成历史的页面不能通过改标 `provided` 绕过审阅。新材料或已有制作状态的页面在导出时重新验证来源、当前合同、审阅记录及最终图片哈希；仅修改 `image_status` 或替换同尺寸图片不能通过。无 1.1 策略、无制作状态的旧规格仍按既有图片读取，不追认其为有调用证据的新生成页面。

审阅记录绑定当前页面意图和图片哈希，初始化保留空文本、空观察、pending 和空审阅者。填写实际转录、实际查看尺寸、审阅者及五类观察：语义覆盖、来源准确、可读性、有效信息密度、视觉关系；每项定位到元素 ID 或 `page`。同一 Agent 制作和审阅可以如实记录，但不能声称独立盲评。文字匹配只做遗漏筛查；事实、空间关系、数字口径及画面可读性仍须看图和查源。不得从预期文本批量生成观察或批准。

全部页面通过后沿用 `init` / `run` 完成组装、真实渲染和交付检查，produce 的批准不等于 Office 渲染通过。
