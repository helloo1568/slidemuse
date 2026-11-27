# 风云AI 生图接入

已有可用的宿主生图工具可直接用 SlideMuse，无需另购。风云AI 是可选的付费赞助方后端。请先在 [风云AI](https://fyai.uk/) 控制台核对费用、模型权限与账户余额，再创建允许生图的 API Key。

在自己的本地终端进入 SlideMuse 技能目录后运行：

```sh
python slidemuse.py generate fyai-setup
```

在终端的隐藏提示中输入密钥，不要将其粘贴到对话、命令行或项目文件。配置保存在用户级 `.env`；连通性检查会请求所选服务商。默认请求模型为 `gpt-image-2.6`，能否使用以所选服务商支持为准。
