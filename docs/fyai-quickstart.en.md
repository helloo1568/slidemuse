# FengYun AI image-generation setup

SlideMuse ships an OpenAI-compatible API generation backend. Setup takes two steps: get a key on the website, then hand it to your AI tool. No separate skill to build and no environment variables to edit by hand.

Note: this guide only covers calling FengYun AI's image model **when generating PPTs with SlideMuse**. To generate images anytime in normal conversation ("draw a…", "add an illustration", "make a poster"), FengYun AI's announcement describes a more general approach: have your AI tool create a separate fyai-image skill. The two setups are independent and do not conflict — use whichever you need.

## Step 1: Get a key (about a minute)

1. Sign up and log in at [fyai.uk](https://fyai.uk).
2. Top up your balance in the console. Billing is pay-as-you-go at ¥0.04 per image; calls fail if the balance runs out.
3. Create an API key and pick the "GPT（福利）" or "GPT不降智" group. Do not pick "不降智claude" — that group does not support image generation.

## Step 2: Hand the key to your AI tool

Tell your AI tool (Codex / Claude Code / Qoder / WorkBuddy / Trae, etc.):

```text
Connect FengYun AI image generation for me. My key is <paste your key>.
```

The skill configures and verifies everything automatically (one `generate fyai-setup` command) — nothing else to copy, no environment variables. To run it yourself instead, in the skill directory:

```sh
python slidemuse.py generate fyai-setup --api-key <your-key>
```

It defaults to FengYun AI (model gpt-image-2.6); for another OpenAI-compatible provider add `--base-url` and `--model`. The config is written to a user-level `.env`; your key never enters the repository. Generation still follows SlideMuse's normal flow: confirm content, pick a style, then generate and review page by page.