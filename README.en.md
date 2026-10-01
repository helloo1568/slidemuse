<div align="center">

<img src="docs/assets/hero.svg" alt="SlideMuse: from source material to polished slides and editable PPTX" width="100%">

# SlideMuse · Visual-first AI Presentation Skill

**Beautiful first. Editable when you need it.**

Turn books, PDFs, papers, and reports into a visually consistent image deck.<br>
Especially strong for **university competition presentations**—including Challenge Cup, the China International College Students' Innovation Competition, the National College Student Transportation Science and Technology Competition (交科赛), 3-Chuang, CP Cup, and innovation-training defenses—while also supporting **academic talks, thesis defenses, project pitches, course presentations, and cinematic slides**.<br>
Reconstruct slide images as native editable PowerPoint (PPTX) when needed.

[![CI](https://github.com/helloo1568/slidemuse/actions/workflows/ci.yml/badge.svg)](https://github.com/helloo1568/slidemuse/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-2.9.0-79e9d1?labelColor=14243c)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.10%2B-82b5ff?labelColor=14243c)](requirements.txt)
[![License: MIT](https://img.shields.io/badge/License-MIT-f2c98a?labelColor=14243c)](LICENSE)

[简体中文](README.md) · **English**

[Showcase](#showcase) · [Why SlideMuse](#features) · [Quick start](#quick-start) · [Guide](docs/guide.en.md) · [Contributing](CONTRIBUTING.md)

</div>

## Install in 30 seconds

**Recommended: send this one message to Codex, Claude Code, or OpenCode:**

```text
Install SlideMuse from https://github.com/helloo1568/slidemuse .
Run the repository's install.py to register the skill, install isolated dependencies, and verify the setup. If multiple clients are detected, pass --client for the one you are using.
```

Then say: `Use $slidemuse to turn this PDF into a 10-slide competition presentation.`

Manual install is also just:

```sh
git clone https://github.com/helloo1568/slidemuse.git slidemuse
python slidemuse/install.py
```

---

<a id="showcase"></a>

## See the results

One workflow, two visual directions. These are actual pages produced with this project's workflow. Click an image to view the original.

### Snowline Watch · Glacier blue & silver

An intelligent glacier inspection and ecological early-warning concept, with a consistent visual language across the story, scenarios, and technology comparison.

#### 01 / Cover

<a href="showcase/snowline-watch-01.png"><img src="showcase/preview/snowline-watch-01.webp" alt="Snowline Watch: glacier inspection cover" width="100%"></a>

#### 02 / Problem

<a href="showcase/snowline-watch-02.png"><img src="showcase/preview/snowline-watch-02.webp" alt="Snowline Watch: problem statement" width="100%"></a>

#### 03 / Solution

<a href="showcase/snowline-watch-03.png"><img src="showcase/preview/snowline-watch-03.webp" alt="Snowline Watch: solution" width="100%"></a>

#### 04 / Technology

<a href="showcase/snowline-watch-04.png"><img src="showcase/preview/snowline-watch-04.webp" alt="Snowline Watch: technology comparison" width="100%"></a>

### Glaze Reborn · Red & gold

A competition presentation that connects the problem, solution, and craft technology through a shared red-and-gold palette.

#### 02 / Problem

<a href="showcase/red-gold-competition-02.png"><img src="showcase/preview/red-gold-competition-02.webp" alt="Glaze Reborn: problem statement" width="100%"></a>

#### 03 / Solution

<a href="showcase/red-gold-competition-03.png"><img src="showcase/preview/red-gold-competition-03.webp" alt="Glaze Reborn: solution" width="100%"></a>

#### 04 / Process technology

<a href="showcase/red-gold-competition-04.png"><img src="showcase/preview/red-gold-competition-04.webp" alt="Glaze Reborn: process technology" width="100%"></a>

<sub>Images demonstrate visual output. Editability is assessed through the delivered PPTX objects and audit report. Business and technology figures in these examples are presentation content, not benchmarks for this skill.</sub>

<a id="features"></a>

## Why SlideMuse

| | What you get |
| :--- | :--- |
| **🎨 Choose a direction first** | Approve the content outline, then compare **4 slide-sorter overviews** using the same content before full production. |
| **🧩 Designed to keep editing** | Optional reconstruction into native text, shapes, tables, and **5 chart types**. Photos and complex artwork become separate, replaceable images. |
| **📝 Preserve approved content** | **Page Spec** records exact text, numbers, sources, and stable element IDs. Hash-bound visual transcripts can flag missing facts, and update plans identify affected slides. |
| **🔁 Resume and revise** | `deck-spec.md` tracks production state; `scene.json` stores layout. Update affected elements and assets, then export again. |
| **🔍 Inspect the deliverable** | Audit objects, text, table and chart data, stacking, and full-page background remnants; render every slide with a review sheet and optional source comparison, with a version-bound scorecard for regression checks. |
| **🔓 Open and adaptable** | **MIT licensed**, with support for agents that provide the required capabilities. Local Python tools make no network requests and need no API key. |

> **How it runs:** SlideMuse is an agent skill. The host reads materials, interprets images, and generates artwork; local scripts assemble, crop, compile, and audit. End-to-end production requires those host capabilities. See [runtime and model notes](references/models.md).

## What can you make?

| Use case or style | How SlideMuse helps |
| :--- | :--- |
| **Competition PPT / competition presentations** | Connect the problem, solution, technical advantages, and applications in a consistent visual story. |
| **Challenge Cup / innovation competition / transportation competition / 3-Chuang / CP Cup** | Turn proposals, papers, research reports, business plans, and competition briefs into judge-oriented presentation narratives with a consistent visual system. |
| **Cinematic PPT / cinematic slides / poster-style presentations** | Explore cinematic lighting, scene composition, and poster-style covers through four visual directions. |
| **Academic presentations / thesis defense / research slides** | Extract questions, methods, results, and conclusions from papers and PDFs while preserving data and sources. |
| **Business presentations / project updates / course presentations / book presentations** | Adapt long source materials to the audience, slide count, and speaking context. |
| **AI presentation generation / PDF to PPT / image to editable PPTX** | Generate an image deck from source material, or reconstruct existing slide images and scanned PDF pages as editable objects. |

Cinematic, technology, and red-and-gold styles are visual directions you can request. Results depend on source material, the host's image capabilities, and slide-by-slide review.

### Specific competition presentation scenarios

Use project proposals, research papers, survey reports, and the current competition brief as source material. The examples below suggest ways to organize a presentation; confirm the outline against the requirements of your track.

| Competition | Search terms | Presentation focus |
| :--- | :--- | :--- |
| [中国国际大学生创新大赛](https://hudong.moe.gov.cn/srcsite/A08/s5672/202607/t20260731_1445670.html) | **大学生创新大赛 PPT / 互联网+ PPT / innovation pitch deck** | Problem, innovation, validation, team, and development plan. |
| [“挑战杯”全国大学生课外学术科技作品竞赛](https://www.tiaozhanbei.net/focus) | **挑战杯 PPT / 大挑 PPT / Challenge Cup research presentation** | Research question, methods, novelty, results, and applications. |
| [“挑战杯”中国大学生创业计划竞赛](https://www.tiaozhanbei.net/focus) | **小挑 PPT / Challenge Cup business plan presentation** | Customer needs, product, market, business model, and execution. |
| [全国大学生交通运输科技大赛（交科赛）](http://www.nactrans.net/) | **交科赛 PPT / transportation science & technology competition** | Transportation problem, solution design, technical route, validation, and innovation value. |
| [全国大学生电子商务“创新、创意及创业”挑战赛](https://www.3chuang.net/) | **三创赛 PPT / e-commerce competition presentation** | E-commerce context, ideas, operations, project results, and value. |
| [“正大杯”全国大学生市场调查与分析大赛](https://www.china-cssc.org/show-568-1912-1.html) | **正大杯 PPT / 市调大赛 PPT / market research presentation** | Research questions, survey design, data analysis, findings, and recommendations. |

Also useful for **大创 (undergraduate innovation and entrepreneurship training projects)**: proposal defenses, progress reports, and final presentations. These are project reporting scenarios, listed separately from competitions.

## Three stages, from source to delivery

| 01 · Content & style | 02 · Image deck | 03 · Editable reconstruction (optional) |
| :--- | :--- | :--- |
| Draft each slide, review content, then approve | Save Page Spec and generate each slide | Reconstruct layers from the spec and images |
| Compare four overviews and choose a style | Review text and visuals; assemble the PPTX | Compile native objects, audit, and render |
| **Approved production plan** | **Slide images + image-only PPTX** | **Editable PPTX + Scene + assets** |

Content approval precedes style selection by default. Stage 3 requires an explicit editable-deck request. Existing slide images or scanned PDFs can enter reconstruction directly. Preview skips and delegated choices follow the [full workflow rules](docs/guide.en.md).

The outline includes a reviewable draft for each slide: its claim, support, traceable evidence, interpretation, and actual visible content. Before style selection, the agent reviews content quality, then obtains approval or explicit authority to decide the content. Image generation preserves approved analysis and necessary qualifications. Covers and transitions stay concise; there is no universal word count or text ratio. See the [content-depth reference](references/content-outline.md) (Chinese).

<a id="quick-start"></a>

## Quick start

### 1. Recommended: ask your agent to install it

Requires **Python 3.10+** and an agent with skill-file support, document reading, image generation, and local file tools.

Send this to Codex, Claude Code, or another skill-capable agent:

```text
Install the SlideMuse skill from https://github.com/helloo1568/slidemuse .
Use the repository's install.py to register the skill, install dependencies, and verify the setup.
```

### 2. Manual install: clone, then run one command

```sh
git clone https://github.com/helloo1568/slidemuse.git slidemuse
python slidemuse/install.py
```

The installer detects Codex, Claude Code, and OpenCode. It auto-selects only when exactly one client is detected; if multiple clients are present, it stops and asks you to pass `--client` so the skill is not installed into the wrong directory. It then copies the minimal runtime files, creates an isolated Python environment, installs dependencies, and validates the Page Spec example:

```sh
python slidemuse/install.py --client codex
python slidemuse/install.py --client claude
python slidemuse/install.py --client opencode
```

For upgrades, installation and validation happen in a temporary directory first. A failed upgrade keeps the previous version. If the installer finds a skill under the old name, it reports its location; remove it yourself after confirming `$slidemuse` works.

Keep source materials and deliverables in a separate working directory, not inside the installed skill.

### 3. Attach your material and ask

```text
Use $slidemuse to turn the attached report into a 10-slide project pitch.
The audience is competition judges. I have no style reference.
Show the content outline for approval, then four slide-sorter overviews for selection.
After I choose a style, create the image deck, then reconstruct an editable PPTX.
Include page-spec.json, scene.json, assets, and the editability report.
```

<details>
<summary>More examples: image-only decks / existing slide reconstruction</summary>

**Image-only classroom presentation:**

```text
Use $slidemuse to make a 12-slide classroom presentation from the attached material.
The audience is my classmates. No style reference; deliver only an image deck.
Confirm the outline first, then show four slide-sorter options for me to choose from.
```

**Make existing slide images editable:**

```text
Use $slidemuse starting at Step 3 to reconstruct all attached slide images as editable PPTX.
Preserve wording, aspect ratio, layout, and page order. Separate text, charts, and subjects.
Keep complex artwork as independent images, remove background remnants,
and deliver the Scene, assets, and editability report.
```

</details>

## What can you edit?

| Slide content | Reconstructed object | Editable properties |
| :--- | :--- | :--- |
| Headings, body text, labels, page numbers | Native text boxes | Text, font, color, position |
| Geometry, arrows, flow nodes | Native shapes, lines, groups | Size and style; ungroup to edit children |
| Tables | Native tables | Cell content and formatting |
| Column, bar, line, pie, doughnut charts | Native charts + embedded workbooks | Data and chart styling |
| Photos, people, complex illustrations | Separate image objects | Position, size, crop, replacement |

Complex artwork remains raster within each image. Recognition, segmentation, and background repair depend on host tools; the local scripts include no automatic OCR or segmentation model. Structural audits do not replace visual review or guarantee recovery of occluded information. See [capabilities and validation](docs/guide.en.md).

## Documentation & community

| Your next step | Resource |
| :--- | :--- |
| Installation, workflow, commands, and validation | [Usage & technical guide](docs/guide.en.md) |
| Agent instructions | [SKILL.md](SKILL.md) |
| Content contracts and editable objects | [Page Spec](references/page-spec.md) · [Scene v1](references/scene-format.md) · [Reconstruction](references/reconstruction.md) |
| Versions and design references | [Changelog](CHANGELOG.md) · [Research](references/research.md) |
| Bug reports, suggestions, and code contributions | [Discussions](https://github.com/helloo1568/slidemuse/discussions) · [Contributing](CONTRIBUTING.md) |

### Credits & license

Thanks to [PPT Master by Hugo He](https://github.com/hugohe3/ppt-master), [banana-slides](https://github.com/Anionex/banana-slides), and [PPTAgent](https://github.com/icip-cas/PPTAgent) for methodological inspiration, and to Xiaoheihe author 玩家22186848 and Bilibili creator 一往无前河井 for their tutorials. The scene compiler is independently implemented; see [research notes](references/research.md) for attribution and tradeoffs.

Local scripts need no API key. Host image and vision services may receive supplied materials; their own pricing and privacy terms apply.

<div align="center">

**Start your next presentation with a good idea.**

If SlideMuse helps you, give it a Star or share your work and improvements.

[MIT License](LICENSE) © 2026 风清云影（[helloo1568](https://github.com/helloo1568)）

</div>
