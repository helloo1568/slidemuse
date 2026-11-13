# FengYun AI image-generation setup

SlideMuse ships an OpenAI-compatible API generation backend — no separate skill to build and no environment variables to edit by hand. Once you have a key, paste the block below to your AI tool (Codex / Claude Code / Qoder / WorkBuddy / Trae, etc.) and it does the rest.

## Step 1: Get a key (about a minute)

1. Sign up and log in at [fyai.uk](https://fyai.uk).
2. Top up your balance in the console. Billing is pay-as-you-go at ¥0.04 per image; calls fail if the balance runs out.
3. Create an API key and pick the "GPT（福利）" or "GPT不降智" group. Do not pick "不降智claude" — that group does not support image generation.

## Step 2: Paste this to your AI tool

```text
Please connect SlideMuse's image-generation backend to FengYun AI. I'm a beginner and won't configure environment variables — do everything for me:
1. Ask me for the API key first; I'll paste it to you.
2. In the SlideMuse skill directory, run in order:
   python slidemuse.py generate runtime bootstrap
   python slidemuse.py generate runtime config --api-key <my-key> --base-url https://fyai.uk/v1 --model gpt-image-2.6
   python slidemuse.py generate runtime doctor --check-api
3. If verification fails, show me the HTTP status and the raw error; don't switch services on your own.
Use this backend for SlideMuse image generation from now on. Rules: only image models like gpt-image-2.6 on the image endpoint, never chat models; ¥0.04 per image, generate once per request.
```

The config is written to a user-level `.env`; your key never enters the repository. The model is pinned to gpt-image-2.6 instead of the backend's default gpt-image-2.5-flare. Generation still follows SlideMuse's normal flow: confirm content, pick a style, then generate and review page by page.