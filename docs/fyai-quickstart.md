# 风云AI 生图接入

SlideMuse 自带 OpenAI 兼容的 API 生图后端，不需要另建技能，也不用手动配环境变量。拿到 Key 后，把下面整段话发给你的 AI 工具（Codex / Claude Code / Qoder / WorkBuddy / Trae 等），剩下的它来做。

## 第一步：拿 Key（约 1 分钟）

1. 打开 [fyai.uk](https://fyai.uk) 注册登录。
2. 在控制台创建 API Key。
3. 分组选「GPT（福利）」或「GPT不降智」。别选「不降智claude」——该分组不支持生图。

## 第二步：把这段话发给你的 AI 工具

```text
请帮我把 SlideMuse 的生图后端接到风云AI。我是小白，不会配环境变量，全部由你来做：
1. 先问我要 API Key，我粘贴给你。
2. 在 SlideMuse 技能目录依次运行：
   python slidemuse.py generate runtime bootstrap
   python slidemuse.py generate runtime config --api-key <我的Key> --base-url https://fyai.uk/v1 --model gpt-image-2
   python slidemuse.py generate runtime doctor --check-api
3. 验证失败时把 HTTP 状态码和报错原样告诉我，别自行换服务。
以后用 SlideMuse 生图就走这个后端。规则：图片接口只填 gpt-image-2 这类图片模型，别填聊天模型；每张 0.04 元，同一需求只生成一次。
```

配置写在用户级 `.env`，Key 不会进仓库。接入后生图仍按 SlideMuse 正常流程：先确认内容、再选风格、逐页生成并核对。