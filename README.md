# Hetzner Claude Code

Run **Claude Code** on Windows using **Hetzner's free AI service**.

A small helper program sits on your PC and translates between the two. Install it once, then use Claude Code the way you normally would.

> Read [What to expect](#what-to-expect) first. Hetzner's AI service is free and experimental, so it runs slower than a paid Claude account.

---

## What you need

| | |
|---|---|
| A Windows PC | Windows 10 or 11 |
| A Hetzner account | Free at [console.hetzner.com](https://console.hetzner.com) |
| A Hetzner Inference API key | A long password-like code from your Hetzner account |
| Claude Code | Install with `npm install -g @anthropic-ai/claude-code` |

The installer adds Python for you if your PC needs it.

---

## Install it

**Step 1.** Click Start, type `powershell`, press Enter.

**Step 2.** Copy this line, paste it into the blue window, press Enter:

```powershell
irm https://raw.githubusercontent.com/junaid-82/hetzner-claude-code/main/install.ps1 | iex
```

**Step 3.** Paste your key at the prompt and press Enter. The key stays hidden while you paste, so paste and press Enter.

**Step 4.** Wait for the green **Installed successfully** message.

**Step 5.** Close the window, open a new PowerShell window, and type:

```powershell
claude
```

Claude Code now runs on Hetzner.

---

## What to expect

Hetzner's AI service is a free experiment, and it behaves like one.

**It paces itself.** Hetzner grants **10 requests per minute**. Claude Code spends roughly one request per step of its work, so a quick question answers immediately while a larger job — editing several files, running commands — moves in bursts. The helper queues each request and takes its turn automatically. A pause of 10 to 30 seconds means it is waiting for the next slot.

**It gets busy.** Hetzner is still growing this service, and its machines fill up. You may see `ServiceUnavailable` or a long wait. The helper retries on its own; if the wait continues, come back later and your setup will still be fine.

**The model is smaller.** It is a capable open-source model that trades some depth on hard programming tasks for being free.

**Best for:** trying Claude Code, small edits, questions about code, learning your way around.

---

## Everyday commands

**Start the helper** (needed after each restart):

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\HetznerClaudeCode\start.ps1"
```

**Stop the helper:**

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\HetznerClaudeCode\stop.ps1"
```

**Remove everything:**

```powershell
irm https://raw.githubusercontent.com/junaid-82/hetzner-claude-code/main/uninstall.ps1 | iex
```

Uninstalling restores whatever Claude Code settings you had beforehand.

---

## If something looks wrong

**"claude is not recognized"**
Install Claude Code with `npm install -g @anthropic-ai/claude-code`, then close and reopen PowerShell.

**Claude Code reports a connection error**
Start the helper with the command above. Windows clears it on every restart.

**"Setup stopped here" during install**
The message names the fix. A mistyped key is the usual cause, so run the installer again and re-paste it.

**Everything pauses for a while**
That is the 10-requests-per-minute budget, or Hetzner being busy. Let it run.

**Check that it works:**

```powershell
$t = [Environment]::GetEnvironmentVariable('HCC_LOCAL_TOKEN','User')
Invoke-RestMethod http://127.0.0.1:8787/verify -Headers @{Authorization="Bearer $t"}
```

`ok : True` means the helper is running and your key is valid.

---

## Choosing a model

Two models are available. Switch with this, then restart the helper:

```powershell
[Environment]::SetEnvironmentVariable('HETZNER_MODEL','Qwen3.8-27B','User')
```

See the current list at [Hetzner's docs](https://docs.hetzner.com/experiments/inference/), or ask the helper:

```powershell
$t = [Environment]::GetEnvironmentVariable('HCC_LOCAL_TOKEN','User')
(Invoke-RestMethod http://127.0.0.1:8787/verify -Headers @{Authorization="Bearer $t"}).available_models
```

---

## Your key stays yours

- The key lives in your own Windows user account and travels only to Hetzner.
- The helper listens on `127.0.0.1` alone and answers only callers holding a random token it generates during install.
- Message contents stay out of the logs.
- Create a Hetzner key for this purpose alone, so you can revoke it whenever you like.
- Keep port 8787 closed to your network and the internet.

---

## For developers

### How it works

```text
Claude Code
    |  Anthropic Messages API (POST /v1/messages)
    v
127.0.0.1:8787          <- local adapter, bearer-token protected
    |  translation, retry, rate limiting
    v
https://inference.hetzner.com/api/v1/chat/completions
```

The adapter covers system prompts, multi-turn tool calling with `tool_use`/`tool_result` ordering, image blocks, `stop_sequences`, token-count estimation, and Anthropic stop-reason mapping. Streaming requests receive a well-formed Anthropic SSE event stream while the upstream call itself is buffered for protocol reliability.

### Requirements

- Windows PowerShell 5.1 or PowerShell 7+
- Python 3.8+ (installed via winget when absent; the Store alias is skipped)
- Python standard library only

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `HETZNER_API_KEY` | — | Required. Hetzner Inference key. |
| `HCC_LOCAL_TOKEN` | — | Required. Bearer token the adapter expects from local callers. |
| `HETZNER_MODEL` | `Qwen/Qwen3.6-35B-A3B-FP8` | Upstream model id. |
| `HETZNER_BASE_URL` | `https://inference.hetzner.com/api/v1` | Upstream base URL. |
| `HCC_PORT` | `8787` | Local listen port. |
| `HCC_MAX_RPM` | `10` | Requests allowed per window; `0` runs unthrottled. |
| `HCC_RATE_WINDOW` | `60` | Window length in seconds. |
| `HCC_MAX_ATTEMPTS` | `4` | Upstream attempts for 429 and 5xx replies. |
| `HCC_ALLOW_NO_AUTH` | — | Set to `1` to open the adapter to every local program. |

### Endpoints

| Route | Purpose |
|---|---|
| `POST /v1/messages` | Anthropic Messages, streaming and buffered |
| `POST /v1/messages/count_tokens` | Local token estimate |
| `GET /health` | Adapter liveness |
| `GET /verify` | Confirms the key works and the model is offered |
| `GET /v1/models` | Advertises the configured model |

Routing ignores query strings, so `POST /v1/messages?beta=true` resolves to `/v1/messages`.

### Files

`%LOCALAPPDATA%\HetznerClaudeCode\` holds `proxy\server.py`, `start.ps1`, `stop.ps1`, `bridge.log` and `config.json`. `config.json` records the resolved Python path plus the Claude Code environment values that preceded the install, so uninstall restores them. That backup can include an earlier auth token, so treat the file as a credential file.

### Upstream limits

Hetzner Inference allows 10 requests per 60s, 4M input tokens per 60s and 100k output tokens per 60s, per key. The service is free while experimental, capacity varies, and `503 ServiceUnavailable` under load is expected and retried with exponential backoff.
