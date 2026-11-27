# CLI/API Fallback

Use this reference only after CLI/API fallback has been selected and confirmed with the user. The main `SKILL.md` owns the backend decision rules; this document owns fallback commands, runtime setup, image-input limits, editing, transparency, and troubleshooting.

Let `{skill_root}` mean the directory containing `SKILL.md`.

## Runtime Setup

CLI/API fallback commands use the shared runtime environment. Before running `scripts/assemble_ppt.py` or fallback image commands, make sure the shared runtime exists. If `~/.codex-ppt-skill/.venv/bin/python` is missing, or if importing script dependencies fails, create or refresh the environment:

```bash
python3 {skill_root}/scripts/codex_ppt_runtime.py bootstrap
```

This is an internal setup step for the skill. Do not ask the user to run it unless dependency installation fails and user approval or troubleshooting is required.

The fallback CLI loads `~/.codex-ppt-skill/.env` automatically for `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `CODEX_PPT_IMAGE_MODEL`. Do not manually parse `.env`. For API key, base URL, model, and config troubleshooting, read `image-model-configuration.md` only after the fallback CLI reports missing or invalid configuration, when the user explicitly wants to change those settings, or when a real API call reports authentication, permission, base URL, or model availability failure.

## Generate One Slide

Basic generation command:

```bash
~/.codex-ppt-skill/.venv/bin/python {skill_root}/scripts/image_gen.py generate \
  --model gpt-image-2.6 \
  --prompt-file {prompt_file} \
  --size 2560x1440 \
  --quality medium \
  --out {base_dir}/{deck_name}/origin_image/slide_01.png
```

The fallback CLI defaults to `gpt-image-2.6`. It also accepts explicitly selected provider-prefixed names and older GPT Image models for compatibility; verify provider support before using a model.

When generating from saved `prompts/slide_XX.json` files, use the job's `prompt` field only when the job does not require input images:

```bash
python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("{base_dir}/{deck_name}/prompts/slide_01.json").read_text())["prompt"])' | \
~/.codex-ppt-skill/.venv/bin/python {skill_root}/scripts/image_gen.py generate \
  --prompt-file - \
  --size 2560x1440 \
  --quality medium \
  --out {base_dir}/{deck_name}/origin_image/slide_01.png
```

Before using this text-only `generate` path, inspect the assigned `prompts/slide_XX.json`. If `input_images` is non-empty or `requires_context_images` is true, this command is not sufficient because it does not attach those images. Use a selected backend/path that can pass the required images, such as the built-in image tool with the images visible in context or a CLI/API edit/image-input path that supplies every required source image. If no such path is available, stop and ask the user whether to switch backend. Do not generate a text-only replacement for a strict input asset.

## Capabilities And Sizes

The fallback CLI supports:

- `generate`: create one or more images from a prompt.
- `edit`: edit one or more existing images, optionally with a mask.

The fallback CLI defaults to 2K 16:9 landscape output, `2560x1440`, with `medium` quality. The recommended GPT Image 2.6 path uses `low`, `medium`, `high`, or `auto`; it does not infer support for `xhigh` or `max`. Explicitly selected legacy variants retain their own validated option limits. For 4K landscape slides, use `--size 3840x2160 --quality high` only when the user asks for 4K, text-heavy slides need sharper output, or the default result is blurry. For portrait assets, use `--size 2160x3840` only if the user requests portrait output. Always inspect the actual returned dimensions and visual quality; accepted request dimensions do not prove the provider produced native 4K output.

## Editing Slides

If a slide is mostly correct but has a localized issue, use the selected backend's edit capability when available. In CLI/API fallback mode:

```bash
~/.codex-ppt-skill/.venv/bin/python {skill_root}/scripts/image_gen.py edit \
  --image {slide_path} \
  --prompt {edit_prompt} \
  --out {new_slide_path}
```

Replace the final slide only after validating the edited output. Existing output files, including downscaled copies, are checked before an API call; choose a new filename or explicitly use `--force`. Empty, incomplete, invalid-base64, and invalid-image responses fail without replacing previous outputs.

## Transparent Backgrounds

Transparent-background requests:

- For the recommended GPT Image 2.6 model, request `--background transparent --output-format png` (or `webp`) only when the selected provider confirms support. JPEG cannot preserve transparency. The current AtlasCloud adapter does not forward `background` and accepts only PNG/JPEG; do not promise native transparency through that adapter.
- Compatibility checks for explicitly selected older models remain in the CLI. Preserve the selected model unless a switch has been agreed; do not infer their capability limits from the 2.6 recommendation.
- In built-in mode, use native transparency if the tool supports it; otherwise use a flat chroma-key background and `scripts/remove_chroma_key.py` when appropriate.

## Assembly And Doctor

`assemble_ppt.py` supports `16:9` and `4:3`. Use `16:9` unless the user requests otherwise.

Run the API doctor only when troubleshooting fallback API access:

```bash
python3 {skill_root}/scripts/codex_ppt_runtime.py doctor --check-api
```
