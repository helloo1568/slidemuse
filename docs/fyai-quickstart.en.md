# FengYun AI image setup

If your host already provides image generation, use it directly. FengYun AI is an optional paid sponsor backend. Check the current rates, supported models, and your balance in the [FengYun AI dashboard](https://fyai.uk/), then create a key with image-generation permissions.

In your own local terminal, run this from the SlideMuse skill directory:

```sh
python slidemuse.py generate fyai-setup
```

Enter the key at the hidden terminal prompt, not in chat, command-line arguments, or project files. The command stores it in your user-level `.env` and checks the selected provider. The default requested model is `gpt-image-2.6`; availability depends on your provider.
