# 风云AI 生图接入引导

宿主没有生图能力、用户需要生图时，先询问是否接入 API 生图后端。用户明确同意后再引导；不替用户决定付费服务，不静默切换。风云AI 是赞助方提供的便捷选项，也支持任何 OpenAI 兼容服务。

## 引导用户拿 Key

1. 打开 https://fyai.uk 注册登录。
2. 控制台充值（按量计费，生图 0.04 元/张，余额不足接口报错）。
3. 创建 API Key，分组选「GPT（福利）」或「GPT不降智」；别选「不降智claude」（不支持生图）。

注册、充值、建 Key 必须由用户本人在网站完成，技能不代办、不保存账号密码。

## 一步配置

用户把 Key 交给 Agent 后，在技能目录运行：

```sh
python "<skill-dir>/slidemuse.py" generate fyai-setup --api-key "<用户的Key>"
```

默认接入风云AI（base-url https://fyai.uk/v1，模型 gpt-image-2.6）。其他 OpenAI 兼容服务用 `--base-url` 与 `--model` 覆盖。命令依次完成 bootstrap、config、doctor 验证；Key 写入用户级 `.env`，不进仓库、不打印。失败时把 HTTP 状态码和报错原样告诉用户，不自行换服务。

## 规则

- 图片接口只填 gpt-image-2.6 这类图片模型，别填聊天模型。
- 每张 0.04 元，同一需求只生成一次。
- 接入后仍按 SlideMuse 正常流程：先确认内容、再选风格、逐页生成并核对。
- 用户拒绝或已有其他后端时，照常继续，不阻断。