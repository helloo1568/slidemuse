# Unified CLI and runtime diagnosis

[Homepage](../README.en.md) · [简体中文](cli.md)

`slidemuse.py` provides one entry point for existing local tools on Python 3.10+. Run it from the repository or installed skill root, or supply its full path from another directory. Task paths remain relative to your working directory.

```sh
python slidemuse.py --help
python slidemuse.py --version
python slidemuse.py doctor
```

The launcher prefers `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` elsewhere, relative to its own directory, and otherwise uses the current interpreter. It computes the path after relocation rather than trusting stale `.skill-python` contents. The environment must still match the OS and base Python. No activation, uv, pipx, or new library is required.

## Common commands

| Command | Existing tool | Purpose |
|---|---|---|
| `init task --mode editable` | `scripts/init_deck.py` | Initialize prepared specifications without overwriting a job |
| `check task/job.json task-output` | `scripts/run_deck.py --check` | Read-only preflight |
| `run task/job.json task-output` | `scripts/run_deck.py` | Build, render, evaluate or resume |
| `render deck.pptx previews` | `scripts/render_deck.py` | Render an actual PPTX |
| `style-overview --compare 01.png 02.png 03.png 04.png comparison.png --html` | `scripts/build_style_overview.py` | Combine four numbered style cards with an offline HTML preview |
| `workbuddy setup project` / `workbuddy review project` / `workbuddy publish project` | `scripts/workbuddy_delivery.py` | Configure project checks, prepare rendered reviews, and publish the approved PPTX |
| `validate page-spec.json --strict` | `scripts/validate_page_spec.py` | Validate specifications |
| `style-reference page-spec.json --box x y w h --output styles/reference.png` | `scripts/style_reference.py` | Register a style reference bound to the selected source |
| `produce prepare page-spec.json` | `scripts/page_production.py` | [Resume image production](../references/page-production.md): original snapshots, protected evidence composition, bound reviews and region updates |
| `audit deck.pptx --scene scene.json` | `scripts/audit_editability.py` | Check native objects |
| `review task/job.json task-output` | `scripts/review_panel.py` | Export a review panel or import records |
| `rebuild <command>` | `scripts/editable_backend.py` | [Complete reconstruction backend](../references/editable-backend.md); optional dependencies with `install.py --with-editable` |
| `generate <command>` | `scripts/generate_backend.py` | [Complete image-generation backend](../references/generate-backend.md): per-slide jobs and prompts, dispatch/result/blocker state, status summary, image-deck assembly, chroma-key removal; optional dependencies with `install.py --with-generate` |

Prefix each command with `python slidemuse.py`. Arguments pass through unchanged, and `<command> --help` displays the original tool's help. Advanced tools remain available as `scripts/*.py`; use the installed `.venv` interpreter or the path recorded in `.skill-python` for direct invocation.

With `--overwrite`, render outputs must use separate paths from the deck, Page Spec, and reference images. The previous results are replaced after rendering and comparison succeed. Editable jobs require the Scene and Page Spec to use the same aspect ratio. WorkBuddy checks the current render settings and page review records before publishing.

Visual pass or fail decisions require notes on every decided page in both image and editable decks. The pipeline archives a malformed default visual review and generates a pending template. For an external review, it reports the error and preserves the original file. Save the scorecard to a path separate from the inputs and render evidence. Editable audits also check the actual chart type and bar direction.

Pipeline exit codes are preserved: 0 means the requested command succeeded, possibly only saving a requested stage; 1 means failed checks or blocked input; 3 means review is pending. Invalid arguments normally return 2. `check` is read-only and never creates a workspace or approves assets. Options such as `run --stop-after` and `run --status` remain controlled by the original script. Content approval, style selection and visual review follow the existing Skill contract.

`style-overview --compare` takes four PNGs labeled with `--option` and `--name`. Add `--html` for a preview that WorkBuddy can open. `render deck.pptx previews --page-spec page-spec.json --slides 3 5 11` renders the specified original slide numbers beside their source images. Omit `--slides` for final review of the deck.

## Diagnose the environment

```sh
python slidemuse.py doctor --json
python slidemuse.py doctor --require-renderer --backend powerpoint
```

Diagnosis installs nothing, uses no network, does not launch PowerPoint, and does not write task files. It checks the Python 3.10 minimum and dependency installation, numeric minimum versions and imports. Each import probe has a 15-second limit. Missing or broken dependencies produce a failure and repair command. Renderer checks cover Windows PowerPoint registration and PowerShell, or LibreOffice and Poppler on PATH; discovery does not prove rendering succeeds.

The parser supports this repository's `package>=numeric-version` format. Ambiguous prerelease versions and unsupported future constraints explicitly fail. A missing renderer warns with exit code 0 by default, permitting specification checks and compilation; `--require-renderer` makes a missing selected backend fail with exit code 1. Invalid arguments return 2. JSON includes `schema_version`, `skill_version`, `status`, `python`, `skill_root` and individual `checks`.

If the isolated Python cannot start, use a known working Python to invoke `python scripts/doctor.py --json` directly and diagnose that interpreter. Repair the isolated installation by rerunning the repository installer. Sanitize local paths before sharing reports.

Diagnosis does not test the host agent's document reading, vision or image generation.

## Complete reconstruction backend

`python slidemuse.py rebuild <command>` runs the pinned backend without a global editppt installation. Use `install.py --with-editable` for the optional isolated dependencies, `rebuild capabilities --verify-source` for local availability/source checks, and `rebuild --offline prepare <input> --job-dir <run>` for local preparation. See the [integration guide](../references/editable-backend.md).

## Complete image-generation backend

`python slidemuse.py generate <command>` runs the pinned image-generation backend without a global codex-ppt installation. Use `install.py --with-generate` for the optional isolated dependencies, `generate capabilities --verify-source` for local availability/source checks, and `generate --offline prepare --spec <deck_spec.json> --out-dir <deck>` to write per-slide prompt jobs. See the [integration guide](../references/generate-backend.md).

### 2.21.0 content and delivery checks

`validate <page-spec> --content --strict` checks current role-aware content. `generate prepare --page-spec <page-spec> --out-dir <deck>` carries the same approved content to generation; `generate review <deck> --init` creates pending observations, and `generate review <deck>` verifies the completed record before guarded assembly. `rebuild --offline prepare --page-spec <page-spec> --job-dir <run>` carries approved text/data into rebuilding prompts. See [content-density.md](../references/content-density.md).

### Independent generation and result records (2.28.0)

`produce request <page-spec> --slide <id> --route host` creates an independent page packet with the same registered visual baseline for selected styles. Historical tasks without visual references retain the approved-page fallback. After a real call, use `produce compose <page-spec> --slide <id> --source <original> --generation-record <actual-call.json>` to bind its request and original image hashes to the actual tool, model and result locator. `generate result` requires the same record through `--generation-record`; its slide ID and request hash refer to the backend prompt job. An unexposed model is `null`. See [page production](../references/page-production.md).

Declare existing user images with Page Spec `image_origin`, using `kind: "provided"`, the actual source locator and the image SHA-256. Imported images can coexist with generated pages. Generation records do not replace visual review; current material and managed production exports recheck the approved image bytes and bound records.

Record failed calls with `produce failure <page-spec> --slide <id> --route host --failure-kind multi-page --evidence <actual-result-locator>`. Two consecutive same-kind failures on that route block another request. Use an available real alternative or report blocked. Authorized `generate image generate/edit` requests use the configured shared API interpreter when present; `--offline` rejects network calls.

`install.py --json` writes one final JSON object to stdout. Dependency installation and validation logs go to stderr.

### Local corrections and task recovery (2.29.0)

After an authorized local correction to a retained original or final image, register it with `produce refine <page-spec> --slide <id> --base-image <retained-original-or-final> --source <independent-corrected-image> --operation <description>`, then run a new `review-init` and `accept`. The original call evidence remains bound to the generated original; a separate derivation record tracks the corrected output. Creating a review after an unregistered final-image replacement is rejected. See [page production](../references/page-production.md).

Removed pages retain their production archive. Restoring a stable page ID restores the unchanged state or carries its history into the revised page. Reconstruction `prepare --job-dir` requires a new or empty directory; continue existing runs through their status, result and recovery commands. Invalid `generate prepare --force` inputs leave the previous prompts, jobs and content contract intact.

The LibreOffice backend requires `soffice`, `pdftoppm` and `pdfinfo`. Full and selected rendering include hidden slides and reject a PDF page-count mismatch. Final reconstruction validation checks the actual PPTX body, images and speaker-note relationships; inspect the real rendered pages as well.

### Preserve the chosen visual style (2.30.0)

Register a chosen standalone card with `style-reference <page-spec> --style-sample --output <reference-PNG>`. From a multi-panel overview, use the measured `--box <x> <y> <width> <height>` of one representative region; its aspect ratio does not matter. Relative output paths resolve from the Page Spec directory; use `--single-page` for an explicitly locked independent page. This image is only a visual reference, never a final slide. See [style selection](../references/style-options.md).

The `request_reference` returned by `produce request` and the per-page inputs produced by `generate prepare --page-spec` bind to the same selected visual baseline. Attach the actual image to the image model; a path in prompt text is not an attachment. Structured requests requiring images cannot use text-only `generate image generate`; compatible APIs use `generate image edit --image <actual-reference>`. Review `style_consistency` against the correct reference. Changed, missing or mismatched references block new approval and delivery.
