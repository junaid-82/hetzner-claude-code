# Claude Code on DeepSeek

Run **Claude Code** on Windows using **DeepSeek** instead of an Anthropic subscription.

DeepSeek serves Anthropic's own API format, so Claude Code talks to it directly. This installer just points Claude Code at DeepSeek and checks that it works — nothing runs in the background.

---

## What you need

| | |
|---|---|
| A Windows PC | Windows 10 or 11 |
| A DeepSeek API key | From [platform.deepseek.com](https://platform.deepseek.com) — pay as you go, cents per day |
| Claude Code | `npm install -g @anthropic-ai/claude-code` |

---

## Install

**1.** Press Start, type `powershell`, press Enter.

**2.** Paste this and press Enter:

```powershell
irm https://raw.githubusercontent.com/junaid-82/claude-code-deepseek/main/install.ps1 | iex
```

**3.** Paste your DeepSeek key. It stays hidden while you paste — that is normal.

**4.** Close the window, open a new PowerShell window, and run:

```powershell
claude
```

---

## What it changes

Six settings in your Windows user account:

| Setting | Value |
|---|---|
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_AUTH_TOKEN` | your DeepSeek key |
| `ANTHROPIC_MODEL` | `deepseek-v4-pro` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `deepseek-v4-pro` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `deepseek-v4-pro` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `deepseek-v4-flash` |

Anything already in those settings is saved to `%LOCALAPPDATA%\claude-code-deepseek.json` and restored when you uninstall.

---

## Undo

```powershell
irm https://raw.githubusercontent.com/junaid-82/claude-code-deepseek/main/uninstall.ps1 | iex
```

---

## If something looks wrong

**"claude is not recognized"** — run `npm install -g @anthropic-ai/claude-code`, then reopen PowerShell.

**Claude Code still uses your old account** — `ANTHROPIC_API_KEY` outranks the token this sets. Clear it:

```powershell
[Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY',$null,'User')
```

**Errors about credit** — top up at [platform.deepseek.com](https://platform.deepseek.com).

**Check it works:**

```powershell
$h = @{ Authorization = "Bearer $env:ANTHROPIC_AUTH_TOKEN"; 'anthropic-version' = '2023-06-01' }
Invoke-RestMethod "$env:ANTHROPIC_BASE_URL/v1/messages" -Method Post -Headers $h -ContentType 'application/json' `
  -Body '{"model":"deepseek-v4-flash","max_tokens":32,"messages":[{"role":"user","content":"Say PONG"}]}'
```

---

## Notes

- The key is stored in your own Windows user account and is sent only to DeepSeek.
- DeepSeek publishes no per-minute request limit, and its context window covers Claude Code's long sessions.
- Pricing is per token and cheaper off-peak; see [DeepSeek's pricing](https://api-docs.deepseek.com/quick_start/pricing).
- Model names and the endpoint come from [DeepSeek's Claude Code guide](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/).
