# 完整图片生成后端

多页图片版制作需要逐页任务、子代理分派和状态登记时读取。统一入口为 `slidemuse.py generate`，不用另外安装名为 `codex-ppt` 的全局命令。

上游为 `ningzimu/codex-ppt-skill`，完整安装用源码、文档、提示模板、12 套风格参考和测试随技能保留。[upstream.json](../vendor/codex-ppt/upstream.json)记录固定提交、原始文件哈希；[MIT 许可证](../vendor/codex-ppt/LICENSE)随包保留。上游 SKILL 是来源记录，当前任务仍以 SlideMuse 主入口、用户授权和宿主工具规则为准。

## 安装和选择

```sh
python install.py --client codex --with-generate
python slidemuse.py generate capabilities --verify-source
python slidemuse.py generate --help
```

额外依赖装入本技能隔离环境。普通安装也保留完整源码；需要扩展运行能力时使用 `--with-generate`，或用技能解释器安装 `requirements-generate.txt`。`capabilities` 只检查可用性和来源，不读取凭证或测试外部服务。

**一条任务只用一个事实源。** SlideMuse 主流程用 `page-spec.json` + `slides/NN-*.png` + `build_image_ppt.py`；本后端用已确认大纲 + `prompts/slide_NN.json` + `slide_jobs.json` + `origin_image/slide_NN.png` + `assemble_ppt.py`。两者不混用：`slide_jobs.json` 不能当成 `page-spec.json`，反之亦然。S1–S5 的门禁、内容确认和视觉选型两套流程完全相同，本后端不放宽任何门禁，也不替代内容大纲的要点密度要求（见 [content-outline.md](content-outline.md)）。

## 能力覆盖

| 能力 | 命令 | 实际边界 |
|---|---|---|
| 逐页生图任务与提示 | `prepare` | 只写 `prompts/slide_NN.json`，确定性脚本，不调用生图模型 |
| 任务与运行状态汇总 | `status` | 读取 `slide_jobs.json`/`slide_run_state.json`；不判断图片好坏 |
| 分派登记与并发额度 | `dispatch` | 需要真实 worker 与提示文件；聊天记录不构成分派 |
| 结果登记与来源校验 | `result` | 复制选中图片到最终路径，记录后端来源与哈希；拒绝本地绘制类后端 |
| 阻塞登记 | `blocker` | 已完成页面拒绝改标阻塞 |
| 图片版 PPTX 组装 | `assemble` | 按 `slide_NN` 页序充满整页，可选写入 `speech.md` 备注；不替代真实渲染验收 |
| 纯色背景去底 | `chroma` | 本地像素处理，需核对 alpha 边缘 |
| 共享运行环境与 API 配置 | `runtime bootstrap/config/doctor` | 需要联网安装依赖并写用户级 `.env`；只在用户选定 API 后端时使用 |

## 逐页任务、分派与登记

```sh
python slidemuse.py generate prepare --spec "<work>/deck_spec.json" --out-dir "<work>"
python slidemuse.py generate status "<work>" --json
python slidemuse.py generate dispatch "<work>" --slide 3 --agent-id <真实worker-id> --prompt-file "<绝对提示路径>"
python slidemuse.py generate result "<work>" --slide 3 --agent-id <真实worker-id> --backend-used "built-in image tool" --selected-source "<生成图路径>" --qa-note "<看图结论>"
python slidemuse.py generate blocker "<work>" --slide 3 --agent-id <真实worker-id> --reason "<缺失条件与证据>"
python slidemuse.py generate assemble "<base_dir>" "<deck>.pptx"
```

- 每张成品图必须由**已确认的生图后端**产出，并写入 `sample_generation_method` 让子代理沿用同一路径；`result` 会拒绝把 Pillow、SVG、HTML/CSS、python-pptx 或手工拼图登记为成品图。
- 只有真实 worker 才能 `dispatch`；`status` 的 `dispatchable_slides` 与 `dispatch_slots_available` 决定还能分派几页，慢不代表失联。
- 每页围绕内容大纲的 3–5 条支撑要点写提示，标题、要点和结论必须出现在图片本身，不得只留在提示词里。
- 需要严格输入素材时，在 `required_images` 标记角色与保真要求，并在 S1 内容门禁处让用户核对素材图→页映射。
- 状态以脚本记录为准：`slide_jobs.json` 中仍有 `pending`、`dispatched` 或 `blocked` 的页面时不得组装。

`prepare --spec` 的输入是上游格式的 `deck_spec.json`（字段示例可用 `prepare --write-template <path>` 生成）。它由已确认的大纲填写，不替代 `deck-spec.md`：页面类型与 3–5 条要点仍以内容门禁批准的版本为准。

## 离线执行

```sh
python slidemuse.py generate --offline prepare --spec "<work>/deck_spec.json" --out-dir "<work>"
python slidemuse.py generate --offline status "<work>" --json
```

`--offline` 写在 `generate` 后，隔离配置与凭证发现，并把 `CODEX_PPT_HOME` 指向临时目录；本地任务、状态、登记、组装和去底仍可用。`runtime` 需要建虚拟环境、写用户级 `.env` 或探测 API，`--offline` 下直接拒绝。Windows 子进程统一用 UTF-8。

## 风格库与上游参考

`prepare` 生成的提示与 `references/` 中的 12 套内置风格可直接作为视觉系统输入；用户自定义风格存放在 `${CODEX_PPT_HOME:-~/.codex-ppt-skill}/references/`，与 [style-library.md](style-library.md) 描述一致。字段与工作流细节读取上游文件：

- 大纲、风格与样张：[outline-style-and-sample.md](../vendor/codex-ppt/skills/codex-ppt/docs/outline-style-and-sample.md)
- 门禁与进度：[workflow-gates-and-progress.md](../vendor/codex-ppt/skills/codex-ppt/docs/workflow-gates-and-progress.md)
- 逐页分派：[slide-generation-and-subagents.md](../vendor/codex-ppt/skills/codex-ppt/docs/slide-generation-and-subagents.md)
- 素材与组装：[user-supplied-assets.md](../vendor/codex-ppt/skills/codex-ppt/docs/user-supplied-assets.md)、[project-assembly-and-reporting.md](../vendor/codex-ppt/skills/codex-ppt/docs/project-assembly-and-reporting.md)

这些参考中的裸命令（`scripts/prepare_slide_prompts.py`、`scripts/assemble_ppt.py` 等）均替换为 `python <skill-dir>/slidemuse.py generate <子命令>`。上游允许本地绘制或叠加文字的做法不适用：成品图必须来自已确认生图后端，准确文字兜底仍用 `overlay_text.py` 并按 Step 2 验收。

## 验证与交付

组装出的图片版 PPTX 仍需真实渲染核对：

```sh
python slidemuse.py render "<实际最终PPTX路径>" "<work>/office-review"
```

核对页数、页序、画幅、文字与裁切，再交付 PPTX、已确认大纲、`slide_jobs.json`、逐页任务与提示、`speech.md`（如有）和渲染预览。结构通过不等于视觉通过；无渲染器时只写“仅完成结构验证”。完整接入不表示每张生成的图片都无需复查。
