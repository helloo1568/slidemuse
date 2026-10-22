# Complete editable sample

The default installation and core archive omit this demo. Download `sample.zip` separately from [GitHub Releases](https://github.com/helloo1568/slidemuse/releases) after 2.23.0 is published, or use the existing repository ZIP below. Extract it into a task directory. From a full checkout, `python install.py --client codex --with-sample` includes it with the skill.

The six-slide Chinese IRENA statistics overview includes finished native/image decks, four independent edit exercises and a complete ZIP with a pinned runtime.

[Sample and reproduction guide](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/README.en.md) · [Offline viewer](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/index.html) · [中文](editable-sample.md)

<p align="center">
<a href="https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/previews/editable-03.webp"><img src="https://raw.githubusercontent.com/helloo1568/slidemuse/main/showcase/editable-irena/previews/editable-03.webp" alt="Original native chart: solar 452 GW" width="49%"></a>
<a href="https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/previews/chart-edit.webp"><img src="https://raw.githubusercontent.com/helloo1568/slidemuse/main/showcase/editable-irena/previews/chart-edit.webp" alt="Synthetic edit: solar 460 GW with updated explanations" width="49%"></a>
</p>

- [Editable PPTX](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/decks/editable.pptx?raw=true)
- [Image PPTX](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/decks/image.pptx?raw=true)
- [Complete sample ZIP](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/sample.zip?raw=true)
- [Edit demonstration MP4](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/demo.mp4?raw=true)
- [Source metadata and cited pages](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/source/source.json)

After extracting the ZIP:

```sh
python -m pip install -r runtime/requirements.txt
python reproduce.py --verify
```

This produces six decks and verifies native objects, embedded chart workbooks and speaker notes. On Windows with PowerPoint, add `--render --backend powerpoint` to export all 36 pages.

The sample covers selected 2024 statistics and the original 2025 report-time scenario. Edited data pages identify their synthetic practice values; the original preserves official data. Native chart ticks and flat fills differ from the image version as documented. The source report remains © IRENA 2025; PDF page 2 specifies reuse terms.
