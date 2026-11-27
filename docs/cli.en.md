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
| `validate page-spec.json --strict` | `scripts/validate_page_spec.py` | Validate specifications |
| `style-reference page-spec.json --box x y w h --output styles/reference.png` | `scripts/style_reference.py` | Register a single-page visual reference bound to the selected source |
| `produce prepare page-spec.json` | `scripts/page_production.py` | [Resume image production](../references/page-production.md): original snapshots, protected evidence composition, bound reviews and region updates |
| `audit deck.pptx --scene scene.json` | `scripts/audit_editability.py` | Check native objects |
| `review task/job.json task-output` | `scripts/review_panel.py` | Export a review panel or import records |
| `rebuild <command>` | `scripts/editable_backend.py` | [Complete reconstruction backend](../references/editable-backend.md); optional dependencies with `install.py --with-editable` |
| `generate <command>` | `scripts/generate_backend.py` | [Complete image-generation backend](../references/generate-backend.md): per-slide jobs and prompts, dispatch/result/blocker state, status summary, image-deck assembly, chroma-key removal; optional dependencies with `install.py --with-generate` |

Prefix each command with `python slidemuse.py`. Arguments pass through unchanged, and `<command> --help` displays the original tool's help. Advanced tools remain available as `scripts/*.py`; use the installed `.venv` interpreter or the path recorded in `.skill-python` for direct invocation.

Pipeline exit codes are preserved: 0 means the requested command succeeded, possibly only saving a requested stage; 1 means failed checks or blocked input; 3 means review is pending. Invalid arguments normally return 2. `check` is read-only and never creates a workspace or approves assets. Options such as `run --stop-after` and `run --status` remain controlled by the original script. Content approval, style selection and visual review follow the existing Skill contract.

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

After an authorized local correction to a retained original or final image, register it with `produce refine <page-spec> --slide <id> --base-image <retained-original-or-final> --source <independent-corrected-image> --operation <description>`, then run a new `review-init` and `accept`. The original call evidence remains bound to the generated original; a separate derivation record tracks the corrected output. An unregistered final-image replacement blocks production writes, including commands for other pages. Move the correction to an independent path, restore the committed image with `prepare`, then register the correction with `refine`. See [page production](../references/page-production.md).

Removed pages retain their production archive. Restoring a stable page ID restores the unchanged state or carries its history into the revised page. Reconstruction `prepare --job-dir` requires a new or empty directory; continue existing runs through their status, result and recovery commands. Invalid `generate prepare --force` inputs leave the previous prompts, jobs and content contract intact.

The LibreOffice backend requires `soffice`, `pdftoppm` and `pdfinfo`. Full and selected rendering include hidden slides and reject a PDF page-count mismatch. Final reconstruction validation checks the actual PPTX body, images and speaker-note relationships; inspect the real rendered pages as well.

`render --overwrite` checks all render and cleanup paths against the input deck, Page Spec and reference images before invoking a renderer. Choose a separate directory when they overlap. Rendering and comparison finish in a temporary directory before publication; rendering, input-validation and publication failures preserve the previous review files. Unrelated files in the review directory remain intact.

### Preserve the chosen visual style (2.30.0)

After selecting an overview, register a measured complete single-page region with `style-reference <page-spec> --box <x> <y> <width> <height> --output <reference-PNG>`. Relative output paths resolve from the Page Spec directory; use `--single-page` for an explicitly locked independent page. This image is only a visual reference, never a final slide. See [style selection](../references/style-options.md).

The `request_reference` returned by `produce request` and the per-page inputs produced by `generate prepare --page-spec` bind to the same selected visual baseline. Attach the actual image to the image model; a path in prompt text is not an attachment. Structured requests requiring images cannot use text-only `generate image generate`; compatible APIs use `generate image edit --image <actual-reference>`. Review `style_consistency` against the correct reference. Changed, missing or mismatched references block new approval and delivery.

### Retrying a blocked image job

After resolving an actual generation blocker, run:

```sh
python slidemuse.py generate retry "<deck-directory>" --slide 3 --reason "<actual recovery reason>"
```

This requeues only the blocked page and retains its previous dispatch, failure and request snapshots. Other completed pages and active workers remain intact; the next dispatch still obeys the concurrency limit. Active or completed pages cannot be requeued with this command.

`generate prepare --force` preserves unchanged completed jobs and archives replaced work before committing new inputs. Changed content requires new review; unchanged content and image bytes retain their approval when only scheduling settings change. In native `--spec` inputs, `approved_style_reference.path` must name a local approved single-page image: preparation binds its actual hash and later gates reject a replaced reference. Save remote style references locally first; preparation does not download them.

### Provider configuration and original assets

Saved image API configuration selects its key, endpoint and model together for both `runtime doctor` and later `generate image` calls. Host environment values cannot replace or fill in fields from another provider. Without a saved provider, environment-only configuration remains supported. Changing a saved endpoint requires its corresponding `--api-key`; rotating a key for the same endpoint remains supported. This does not affect the host agent's native image tools.

Register an original user-supplied image before assigning the page worker:

```sh
python slidemuse.py rebuild --offline preserve-asset "<run>" --page 1 --source "<original.png>" --asset-id official-logo --note "<actual input source>"
```

The command retains an independent input copy and hash, copies identical bytes into the page, and returns the Manifest provenance entries. Both page and final validation verify the registered original and the actual asset; a provenance label alone is insufficient. See [editable backend](../references/editable-backend.md).

Single-page builds finish and validate their temporary PPTX before replacing an existing file. Paired PPTX/preview publication rolls back on failure. With `prepare --page-spec`, final validation also compares native text, tables and charts directly with the approved content snapshot. Content selected as `raster` or `either` keeps that choice; `visual_review_required` lists work still requiring an actual visual comparison, and does not certify those pixels.
