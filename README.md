# Hetzner Claude Code

Use Hetzner's OpenAI-compatible Inference API as the backend for Claude Code on Windows.

Claude Code speaks Anthropic's Messages API; Hetzner Inference exposes OpenAI-compatible Chat Completions. This project provides a small local protocol adapter that translates between the two.

## Quick install

On the Windows machine where Claude Code will run:

```powershell
irm https://raw.githubusercontent.com/junaid-82/hetzner-claude-code/main/install.ps1 | iex
```

The installer will:

1. Ask for the Hetzner Inference API key without echoing it.
2. Store the key in the current Windows user's environment.
3. Install the local adapter under `%LOCALAPPDATA%\HetznerClaudeCode`.
4. Configure Claude Code to use the local adapter.
5. Verify the adapter and Hetzner model endpoint.

Then run:

```powershell
claude
```

## Backend

Default model:

`Qwen/Qwen3.6-35B-A3B-FP8`

You can change it before starting the proxy:

```powershell
$env:HETZNER_MODEL = 'Qwen/Qwen3.8-27B'
```

## Security

- The Hetzner key is never committed to this repository.
- The proxy listens only on `127.0.0.1`.
- Request and response bodies are not logged.
- The installer stores the key in the current user's Windows environment rather than writing it into the repository.
- Use a dedicated Hetzner Inference API key with only the access required for this workload.

## Uninstall

```powershell
irm https://raw.githubusercontent.com/junaid-82/hetzner-claude-code/main/uninstall.ps1 | iex
```

Uninstall removes the local adapter and the environment variables created by this installer.

## Architecture

```text
Claude Code
    |
    | Anthropic Messages API
    v
127.0.0.1:8787
    |
    | protocol translation
    v
https://inference.hetzner.com/api/v1/chat/completions
    |
    v
Qwen/Qwen3.6-35B-A3B-FP8
```

This is intentionally a local bridge, not a public proxy. Do not expose port 8787 to a network interface.