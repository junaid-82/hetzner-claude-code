# Tests

Standard library only, same as the bridge. Run them from anywhere; each test locates
`proxy/server.py` relative to its own path.

## Offline — no network, no Hetzner key

These are the ones to run after any change.

```powershell
python tests/unit_tests.py         # 22 checks on the protocol translation layer
python tests/integration_mock.py   # 32 checks against a scripted OpenAI backend
python tests/ratelimit_test.py     # the local request budget queues rather than failing
```

`integration_mock.py` starts `mock_backend.py`, a small OpenAI-compatible server that
records every payload the bridge sends upstream, so the tests assert on the exact
translation. It also scripts 503 replies to exercise retry and error handling.

Covered: routing including `?beta=true`, bearer and `x-api-key` auth, system prompts,
the `tool_use`/`tool_result` ordering of a multi-turn agent loop, image blocks,
`stop_sequences`, stop-reason mapping, SSE framing, unicode, concurrency, transient
upstream failures, and the error envelope when the upstream stays down.

## Live — needs a Hetzner key

```powershell
$env:HETZNER_API_KEY = '<your token>'
python tests/integration_tests.py   # end-to-end through the real Hetzner API
python tests/capacity_watch.py      # polls until Hetzner serves a request, then exits
```

`capacity_watch.py` is a diagnostic for the `503 ServiceUnavailable - failed to find
endpoint candidates` reply. It probes both models every five minutes and prints only
when the state changes, so it is usable as a long-running watch.

## Ports

The suites bind `8787`-`8790` and `9995`-`9999` on the loopback interface. Stop a running
bridge first with `stop.ps1`.
