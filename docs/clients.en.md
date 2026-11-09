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

Repeat the same installation command to upgrade. The installer prepares and validates a staged version before activation, preserving or restoring the previous install on failure. Other skill directories stay independent.
