"""Poll Hetzner until it serves a request, reporting only changes."""
import json, os, sys, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

KEY = os.environ["HETZNER_API_KEY"]
MODELS = ["Qwen/Qwen3.6-35B-A3B-FP8", "Qwen3.8-27B"]
INTERVAL = 300


def probe(model, timeout=45):
    req = Request("https://inference.hetzner.com/api/v1/chat/completions",
                  data=json.dumps({"model": model,
                                   "messages": [{"role": "user", "content": "Say PONG"}],
                                   "max_tokens": 8}).encode(),
                  headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
                  method="POST")
    try:
        with urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
            return "OK", body["choices"][0]["message"].get("content", "")[:60]
    except HTTPError as e:
        return str(e.code), e.read().decode()[:60]
    except Exception as e:
        return type(e).__name__, ""


last = {}
started = time.time()
while True:
    for model in MODELS:
        state, detail = probe(model)
        if state == "OK":
            print("CAPACITY BACK: %s answered -> %r" % (model, detail), flush=True)
            sys.exit(0)
        if last.get(model) != state:
            print("%s: %s (%s)" % (model, state, detail.strip() or "no body"), flush=True)
            last[model] = state
    hours = (time.time() - started) / 3600.0
    if hours >= 1 and int(hours * 60) % 60 < (INTERVAL / 60):
        print("still unavailable after %.1fh" % hours, flush=True)
    time.sleep(INTERVAL)
