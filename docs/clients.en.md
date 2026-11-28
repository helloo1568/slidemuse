# Client setup

[← Back to home](../README.en.md) · [简体中文](clients.md)

SlideMuse uses a standard `SKILL.md` and shared Python tools. The installer copies the complete runtime into the chosen client's skill directory, installs isolated dependencies, and validates it. The client discovers and invokes the skill.

## Choose a client

Run the matching command from the cloned repository:

| Client | Command | User-level installation |
| :--- | :--- | :--- |
| Codex | `python install.py --client codex` | `~/.agents/skills/slidemuse/` |
| Claude Code | `python install.py --client claude` | `~/.claude/skills/slidemuse/` |
| OpenCode | `python install.py --client opencode` | `~/.config/opencode/skills/slidemuse/` |
| WorkBuddy | `python install.py --client workbuddy` | `~/.workbuddy/skills/slidemuse/` |
| Trae | `python install.py --client trae` | `~/.trae/skills/slidemuse/` |
| Trae CN | `python install.py --client trae-cn` | `~/.trae-cn/skills/slidemuse/` |
| Qoder IDE / CLI | `python install.py --client qoder` | `~/.qoder/skills/slidemuse/` |
| Qoder CN | `python install.py --client qoder-cn` | `~/.qoder-cn/skills/slidemuse/` |

`~` is the current operating-system user directory. Choose the explicit regional option when both editions are present. QoderWork is a separate product; `qoder` here refers to Qoder IDE / CLI.

Without `--client`, the installer checks configuration directories and available commands. One detected client is selected automatically; multiple clients require an explicit choice. When none is detected, the existing Codex default is retained. You can explicitly select a client before its first launch.

Preview the destination with `python install.py --client workbuddy --dry-run --json`. A dry run installs nothing. `--skip-deps` copies runtime files only and does not establish that dependencies are ready. Use the default install options for regular use.

## Activate and invoke

- **WorkBuddy**: enable SlideMuse under installed skills, then select it in a new task or say "Use the slidemuse skill". See the [official skill guide](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market) for version-specific import options.
- **Trae**: find SlideMuse in skill settings or the skill picker, start a new conversation, and say "Use the slidemuse skill". The [official import guide](https://www.trae.ai/blog/trae_tutorial_0115) also describes adding skill packages.
- **Qoder**: use `/slidemuse` or choose it from the `/` suggestions. Reload an open CLI with `/skills reload`, or restart the IDE. See [IDE skills](https://docs.qoder.com/extensions/skills) and [CLI skills](https://docs.qoder.com/cli/Skills).
- **Codex / Claude Code / OpenCode**: explicitly request the slidemuse skill. Codex also accepts `$slidemuse`, and Claude Code accepts `/slidemuse`.

Regional Trae / Qoder directory conventions are also documented in the [Skills CLI client registry](https://github.com/vercel-labs/skills/blob/main/src/agents.ts).

## Capabilities and verification

All clients share the same content planning, style selection, image generation, editable reconstruction, and delivery checks. Image generation and editing use the client's native or already-connected tools; the installer does not configure an additional image service. Python alone can compile, check, and reconstruct prepared materials.

After installation, run the installed `slidemuse.py doctor --json` from a separate working directory and confirm that the client can discover `slidemuse`. Append `--with-editable --with-generate` to the selected install command when you need the complete backend dependencies.

To upgrade, first download and extract the intended new version, then run the same installation command from that source directory. The installer copies its own source tree; it does not fetch a newer GitHub version first. Reinstalling an old download installs the old version again. It prepares and validates a staged version before activation, preserving or restoring the previous install on failure. Other skill directories stay independent.

## WorkBuddy preview and style troubleshooting

If style selection only shows PNG attachment cards, follow the [style preview instructions](../references/style-options.md) to create a 2×2 HTML comparison. Pass its path first to `present_files` and check `previewed` in the result.

Ask WorkBuddy for the absolute path of the `SKILL.md` it actually read for the task, then run `python "<actual-skill-directory>/slidemuse.py" --version` from that installation. The downloaded filename alone does not establish the loaded version. `doctor --json` also reports `skill_root` and `skill_version`. The standard installer uses `~/.workbuddy/skills/slidemuse/`; other imports must be checked at their actual loaded path.

Version 2.30.0 fixes the handoff that kept only written style descriptions while dropping the chosen visual reference. Reuse the approved content and chosen preview, register a complete single-page reference with `style-reference`, then use `produce request` or `generate prepare --page-spec`. The actual image call must attach that reference; a path or JSON string in a text prompt is not an image attachment. Review `style_consistency` for each page. A preview crop is only a style input and must never be delivered as an enlarged final slide.

Compare the chosen preview, the corresponding full-page PNG/JPEG before assembly, and the final PPTX. If the PNG already differs, fix generation. If the PNG is correct and the editable version differs, fix its Scene/Manifest and compare a real render. Standard Page Spec image assembly embeds the selected original without redesigning it; do not pass a mixed folder of previews and old drafts to the legacy directory-merging entry point. Retain existing materials and the user's style choice without repeating the four-option selection.

## WorkBuddy project delivery checks

Run `python slidemuse.py workbuddy setup <project>` once and select that directory for the WorkBuddy task. It configures the project's `.workbuddy/settings.local.json` and managed review workspace. If WorkBuddy presents a trust dialog, choose normal opening for that project to load its local hooks. The defaults are `job.json` and `.slidemuse-review`; use the same `--job` and `--work` arguments for setup, review, and publication when overriding them.

- Send `styles/compare-4-styles.html` with the matching PNG to `present_files`. If the host does not confirm opening the preview, the PNG remains a clickable fallback and the hook explains how to open it. A PNG-only call reports the fallback state directly.
- For a Page Spec / Scene job, run `slidemuse.py workbuddy review <project>` for real rendering and per-slide review. To import a record downloaded from the review panel, run `workbuddy review <project> --import-record <record.json>`, then rerun `workbuddy review <project>` for scoring. When the review command exits, it retains the internal draft data and review images. After the current review passes, `slidemuse.py workbuddy publish <project>` writes `final/slidemuse.pptx` atomically. Present that returned file.

The hooks apply to `present_files` in the managed WorkBuddy project. WorkBuddy 5.11.3 can index an existing file early, so this workflow defers writing a stand-alone presentation until publication. Keep existing external `.pptx` files at their original locations for input or local reference. The manifest-based reconstruction backend continues to use its own page-level review.
