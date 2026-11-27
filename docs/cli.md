# 统一命令与环境诊断

[首页](../README.md) · [English](cli.en.md)

`slidemuse.py` 是现有本地工具的统一入口，支持 Python 3.10+。在仓库或安装的 Skill 根目录运行；也可以从其他目录传入入口的完整路径。任务路径保持相对于当前工作目录。

```sh
python slidemuse.py --help
python slidemuse.py --version
python slidemuse.py doctor
```

入口优先使用自身目录下的 `.venv/Scripts/python.exe`（Windows）或 `.venv/bin/python`（其他平台），否则使用当前解释器。路径从当前安装位置计算，搬移目录后不依赖旧 `.skill-python` 路径；虚拟环境本身仍需与操作系统及基础 Python 兼容。无需激活环境或安装 uv、pipx、新 Python 库。

## 常用命令

| 命令 | 原有工具 | 用途 |
|---|---|---|
| `init task --mode editable` | `scripts/init_deck.py` | 从已准备的规格生成任务，拒绝覆盖配置 |
| `check task/job.json task-output` | `scripts/run_deck.py --check` | 只读预检 |
| `run task/job.json task-output` | `scripts/run_deck.py` | 编译、渲染、评分或接续任务 |
| `render deck.pptx previews` | `scripts/render_deck.py` | 生成真实渲染预览 |
| `validate page-spec.json --strict` | `scripts/validate_page_spec.py` | 验证规格 |
| `style-reference page-spec.json --box x y w h --output styles/reference.png` | `scripts/style_reference.py` | 从所选图登记单页视觉参考与来源绑定 |
| `produce prepare page-spec.json` | `scripts/page_production.py` | [图片制作与恢复](../references/page-production.md)：宿主原图归档、精确证据合成、逐页审阅和坐标修改 |
| `audit deck.pptx --scene scene.json` | `scripts/audit_editability.py` | 检查原生对象 |
| `review task/job.json task-output` | `scripts/review_panel.py` | 生成审阅面板或导入记录 |
| `rebuild <命令>` | `scripts/editable_backend.py` | [完整图片重建后端](../references/editable-backend.md)：输入、文字提示、路径/表格、素材板、公式和任务恢复；扩展依赖使用 `install.py --with-editable` |
| `generate <命令>` | `scripts/generate_backend.py` | [完整图片生成后端](../references/generate-backend.md)：逐页任务与提示、分派/结果/阻塞登记、状态汇总、图片版组装和去底；扩展依赖使用 `install.py --with-generate` |

为表内命令添加 `python slidemuse.py` 前缀。各命令的参数原样交给对应脚本，`<命令> --help` 展示其原有帮助。其他高级工具仍可直接运行 `scripts/*.py`；安装版直接调用脚本时，使用 `.skill-python` 所记录的解释器或当前安装目录下的 `.venv` Python。

流水线原有退出码保持不变：0 表示本次命令成功（也可能只是保存了请求阶段），1 表示检查失败或输入阻塞，3 表示等待审阅。参数错误通常返回 2。`check` 只读，不会创建工作目录或批准素材；`run` 的 `--stop-after`、`--status` 等选项仍由原脚本解释。内容确认、风格选择和逐页视觉检查仍按 Skill 契约执行。

## 排查环境

```sh
python slidemuse.py doctor --json
python slidemuse.py doctor --require-renderer --backend powerpoint
```

诊断不安装软件、不联网、不启动 PowerPoint、不写入任务文件。它检查 Python 是否达到 3.10，以及依赖是否安装、满足最低版本、能够导入。导入探测每包最多 15 秒，缺少或损坏的依赖返回失败和修复命令。后端检查包括 PowerPoint 的 Windows 注册与 PowerShell，或 LibreOffice 和 Poppler 的 PATH；发现程序不等于真实渲染成功。

目前支持仓库的 `包名>=数字版本` 依赖格式；不确定的预发布版本或未来新增的未支持约束明确返回失败。默认缺少渲染器返回 `warning` 和退出码 0，便于仅做规格检查或编译；指定 `--require-renderer` 后缺少所选后端返回 `fail` 和退出码 1。参数错误返回 2。JSON 包含 `schema_version`、`skill_version`、`status`、`python`、`skill_root` 和逐项 `checks`。

如果隔离环境的 Python 本身无法启动，可使用已知可运行的 Python 执行 `python scripts/doctor.py --json`，诊断该解释器；隔离环境需通过重新运行仓库安装器修复。提交问题前检查日志中的本地路径并脱敏。

诊断不探测宿主 Agent 的读材料、视觉理解或生图能力。

### 2.21.0 content and delivery checks

`validate <page-spec> --content --strict` checks current role-aware content. `generate prepare --page-spec <page-spec> --out-dir <deck>` carries the same approved content to generation; `generate review <deck> --init` creates pending observations, and `generate review <deck>` verifies the completed record before guarded assembly. `rebuild --offline prepare --page-spec <page-spec> --job-dir <run>` carries approved text/data into rebuilding prompts. See [content-density.md](../references/content-density.md).

### 独立生图与结果登记（2.28.0）

`produce request <page-spec> --slide <id> --route host` 创建独立单页包，选型任务始终附同一已登记视觉参考；旧无视觉引用任务保留已批准单页兼容路径。实际调用成功后用 `produce compose <page-spec> --slide <id> --source <原图> --generation-record <真实调用记录.json>` 登记，记录绑定本次请求和原图哈希。完整后端 `generate result` 同样要求 `--generation-record`。用户提供的既有图片在 Page Spec 声明 `image_origin`，不伪造生图调用。字段及恢复方式见[图片制作](../references/page-production.md)。

调用失败用 `produce failure <page-spec> --slide <id> --route host --failure-kind multi-page --evidence <真实结果定位>` 登记。同一方式连续两次同类失败会阻止继续分派，应切换实际可用方式或报告阻塞。`generate image generate/edit` 使用用户已授权且配置的 API，`--offline` 拒绝联网；配置过共享 API 环境时，实际调用使用同一解释器。

`install.py --json` 的标准输出只有最终 JSON；依赖安装和验证日志输出到标准错误，可直接交给 JSON 解析器。

### 局部修正与任务恢复（2.29.0）

在已记录的原件或成品上完成获授权的局部修正后，使用 `produce refine <page-spec> --slide <id> --base-image <已保留的原件或成品> --source <独立修正图> --operation <处理说明>` 登记派生成品，再重新执行 `review-init` 和 `accept`。原始调用证据保持绑定原图；修正结果另存处理记录，不把本地修改伪报成新生图。直接替换成品后创建审阅会被拒绝，使用 `refine` 登记实际修改。详见[图片制作](../references/page-production.md)。

删除页面后再次恢复同一页 ID 时，制作状态从保留的归档恢复或沿用历史。重建 `prepare --job-dir` 要求新建或空目录；已有任务使用其状态、结果登记和恢复命令继续处理。生图 `prepare --force` 的输入错误不会部分覆盖旧提示、任务或内容合同。

LibreOffice 后端需要 `soffice`、`pdftoppm` 和 `pdfinfo`。整套与指定页渲染保留隐藏页，PDF 总页数不符时停止。最终重建验证会检查实际 PPTX 的正文、图片与备注关联；仍需查看真实渲染结果。

### 保持所选风格（2.30.0）

选定总览后，用 `style-reference <page-spec> --box <x> <y> <width> <height> --output <参考PNG>` 登记其中一个实测完整单页。相对输出路径按 Page Spec 目录解析；`--single-page` 用于明确锁定的独立单页。该图只用于视觉参考，不是正式成品，详见[风格选型](../references/style-options.md)。

`produce request` 的 `request_reference` 和 `generate prepare --page-spec` 的逐页图片输入均绑定同一选型。调用图像模型时必须真正附图；带图片要求的结构化请求不能用纯文本 `generate image generate`，支持参考图的 API 使用 `generate image edit --image <实际参考>`。正式页审阅包含 `style_consistency`，必须实际对照正确参考，修改、缺失或错用参考会阻止新审阅及交付。
