# 参与贡献 · Contributing

欢迎改进提示词、文档、Page Spec / Scene 协议、导出脚本与测试，也欢迎分享获准公开的作品。

## 报告问题

可复现故障请使用 [Bug 报告表单](https://github.com/helloo1568/slidemuse/issues/new?template=bug_report.yml)，功能建议使用[功能建议表单](https://github.com/helloo1568/slidemuse/issues/new?template=feature_request.yml)；使用咨询继续通过 [GitHub Discussions](https://github.com/helloo1568/slidemuse/discussions) 交流。问题报告提供：

- 使用的 Agent、操作系统、Python 和技能版本。
- 问题出现在哪个阶段，以及最短复现步骤。
- 预期结果、实际结果和相关报错。
- 脱敏后的最小 Page Spec / Scene、必要素材或截图。

请勿提交凭证、私人源材料或没有公开授权的内容。功能建议请说明具体使用场景与期望交付。

`python slidemuse.py doctor --json` 可生成本地环境报告，分享前请检查并脱敏本地路径。渲染故障附实际后端、命令和退出码；诊断只发现环境，不会代替真实渲染。

## 提交修改

1. Fork 仓库，从 `main` 创建功能分支。
2. 保持改动聚焦；面向用户的变更同步更新中英文文档和 `CHANGELOG.md`。
3. 修改脚本或协议时，针对真实风险添加回归测试，并按改动范围选择检查。
4. 提交 Pull Request，说明解决的问题、变更后的行为和验证结果；视觉变更附预览。

### 按改动范围验证

| 改动 | 提交前检查 |
|---|---|
| 文案、链接、首页图片 | 核对文字、链接或实际预览；不为文案改动运行导出回归 |
| 提示词、技能流程 | 检查已有授权、阶段衔接与参考是否一致；行为变化用实际任务验证，不能仅靠关键词测试 |
| 安装、打包、CLI | 运行 `tests/test_install.py`、`tests/test_cli.py`、`tests/test_release_package.py`；覆盖默认安装、可选功能和失败回滚 |
| 生成、渲染、数据或协议 | 运行受影响模块的测试；布局/导出变化查看真实渲染；哈希变化核验旧记录兼容 |
| 正式发布、跨模块变更 | 运行完整检查；涉及哪个后端就增加哪个后端的回归，发布验证隔离安装 |
| 声称生成质量提升 | 在固定材料、相同规则下比较新旧版本，保留失败与返修；不能用测试数量替代质量成绩 |

检查通过后不重复扩大验收，除非出现新改动、失败或未解决的问题。下面是完整检查命令，按上表选用：

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m ruff check .
python -m pytest tests/ -q
python -m pytest vendor/image-to-editable/tests/ -q
python -m pytest vendor/codex-ppt/tests/ -q
python slidemuse.py rebuild capabilities --verify-source
python slidemuse.py generate capabilities --verify-source
python scripts/validate_page_spec.py examples/page-spec.example.json --strict
```

流程变更应明确说明对内容确认、风格选择、图片生成、可编辑还原及已有文件兼容性的影响。结构测试不能替代实际渲染检查。

## English

Contributions to prompts, documentation, Page Spec / Scene contracts, exporters, tests, and authorized showcase images are welcome.

- **Bugs:** use the [bug form](https://github.com/helloo1568/slidemuse/issues/new?template=bug_report.yml) with your agent, OS, Python and skill versions, workflow stage, reproduction steps, expected/actual behavior, and a minimal sanitized example. `python slidemuse.py doctor --json` provides a local report; sanitize its paths before sharing. Include the backend, command and exit code for rendering failures.
- **Suggestions and questions:** use the [feature form](https://github.com/helloo1568/slidemuse/issues/new?template=feature_request.yml) for concrete improvements and [Discussions](https://github.com/helloo1568/slidemuse/discussions) for usage questions.
- **Changes:** fork from `main`, keep the scope focused, and update both language versions and the changelog where relevant. Match validation to the change: inspect copy/links/previews for documentation; exercise authorization and handoffs for workflow changes; run installer/CLI/package tests for packaging; run affected tests and actual renders for output changes. Run the full checks for releases or broad changes, adding vendor regressions for affected backends. Check historical records when hashing changes. Stop once the relevant checks pass unless new evidence justifies more testing.
- **Quality claims:** compare old and new versions on fixed materials under the same rubric, keeping failures and repairs. Test counts and sample reproduction do not demonstrate generation quality.
- **Pull requests:** explain the problem, resulting behavior, and validation. Include previews for visual changes and note compatibility implications for workflow changes.
- **Shared files:** exclude credentials, private documents, and content you do not have permission to publish. Structural tests do not replace rendered visual inspection.

By contributing, you agree that your contributions are provided under the repository's [MIT License](LICENSE).
