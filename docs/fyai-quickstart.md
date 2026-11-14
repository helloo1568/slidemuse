# 风云AI 生图接入

SlideMuse 自带 OpenAI 兼容的 API 生图后端。接入只需两步：去网站拿 Key，把 Key 交给你的 AI 工具。不用另建技能，也不用手动配环境变量。

说明：本教程只用于**用 SlideMuse 生成 PPT 时**调用风云AI 的生图模型。想在日常对话中随时生图（「画一张…」「配个图」「做个海报」），风云AI 公告提供了更通用的办法——让 AI 工具另建一个 fyai-image 技能。两套独立配置，互不冲突，按需选用。

## 第一步：拿 Key（约 1 分钟）

1. 打开 [fyai.uk](https://fyai.uk) 注册登录。
2. 在控制台充值。按量计费，生图 0.04 元/张，余额不足时接口会报错。
3. 创建 API Key，分组选「GPT（福利）」或「GPT不降智」。别选「不降智claude」——该分组不支持生图。

## 第二步：把 Key 交给 AI 工具

对你的 AI 工具（Codex / Claude Code / Qoder / WorkBuddy / Trae 等）说：

```text
帮我接风云AI 生图，Key 是 <粘贴你的Key>。
```

技能会自动完成配置和验证（一条 `generate fyai-setup` 命令），不用你复制别的、也不用配环境变量。想手动跑也可以，在技能目录执行：

```sh
python slidemuse.py generate fyai-setup --api-key <你的Key>
```

默认接入风云AI（模型 gpt-image-2.6）；其他 OpenAI 兼容服务加 `--base-url` 和 `--model`。配置写在用户级 `.env`，Key 不会进仓库。接入后生图仍按 SlideMuse 正常流程：先确认内容、再选风格、逐页生成并核对。