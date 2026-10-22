# 完整可编辑样板

默认安装和核心发布包不携带此演示。从 [GitHub Releases](https://github.com/helloo1568/slidemuse/releases) 下载独立的 `sample.zip`（2.23.0 发布后提供），或使用下方已有的仓库 ZIP，解压到自己的任务目录即可复现。完整仓库用户可用 `python install.py --client codex --with-sample` 选择随技能安装。

IRENA 六页统计导读提供原版可编辑成品、图片版、四种修改练习和固定运行时的完整下载包。

[查看样板和复现说明](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/README.md) · [离线浏览器](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/index.html) · [English](editable-sample.en.md)

<p align="center">
<a href="https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/previews/editable-03.webp"><img src="https://raw.githubusercontent.com/helloo1568/slidemuse/main/showcase/editable-irena/previews/editable-03.webp" alt="原版原生图表：太阳能452 GW" width="49%"></a>
<a href="https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/previews/chart-edit.webp"><img src="https://raw.githubusercontent.com/helloo1568/slidemuse/main/showcase/editable-irena/previews/chart-edit.webp" alt="合成修改练习：太阳能460 GW，相关说明同步" width="49%"></a>
</p>

- [下载原版可编辑 PPTX](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/decks/editable.pptx?raw=true)
- [下载图片版 PPTX](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/decks/image.pptx?raw=true)
- [下载完整样板 ZIP](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/sample.zip?raw=true)
- [观看修改演示 MP4](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/demo.mp4?raw=true)
- [源报告和逐页引用](https://github.com/helloo1568/slidemuse/blob/main/showcase/editable-irena/source/source.json)

完整 ZIP 解压后运行：

```sh
python -m pip install -r runtime/requirements.txt
python reproduce.py --verify
```

生成图片版、原版可编辑版和四套独立练习版，并核对对象、图表嵌入工作簿与演讲备注。Windows PowerPoint 环境可加上 `--render --backend powerpoint` 导出全部36页。

样板使用2024年统计和2025年报告时点情景。表格、图表的修改页显著标明合成练习值，原版保留官方数据。原生版的刻度、平面填色等与图片版有已说明的外观差异。源报告 © IRENA 2025，分享条件见报告PDF第2页。
