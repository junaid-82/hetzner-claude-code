"""The local limiter must queue requests instead of letting Hetzner return 429."""

import os, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = str(REPO / "proxy" / "server.py")
MOCK_BACKEND = str(REPO / "tests" / "mock_backend.py")
RECORD = os.environ.get("HCC_MOCK_RECORD", str(pathlib.Path(tempfile.gettempdir()) / "mock_requests.jsonl"))
import json, subprocess, time
import http.client

TOKEN = "t"
PORT = "8790"
MOCK = "9997"
mock = subprocess.Popen([sys.executable, MOCK_BACKEND, MOCK])
env = dict(os.environ, HCC_LOCAL_TOKEN=TOKEN, HCC_PORT=PORT,
           HETZNER_API_KEY="test-upstream-key",
           HETZNER_BASE_URL="http://127.0.0.1:" + MOCK + "/v1",
           HCC_MAX_RPM="3", HCC_RATE_WINDOW="6")
proc = subprocess.Popen([sys.executable, SERVER], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def call(path="/v1/messages", body=None, timeout=90):
    c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=timeout)
    c.request("POST" if body is not None else "GET", path,
              json.dumps(body) if body is not None else None,
              {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    r = c.getresponse()
    return r.status, r.read().decode()


for _ in range(80):
    try:
        c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=5)
        c.request("GET", "/health", None, {"Authorization": "Bearer " + TOKEN})
        if c.getresponse().status == 200:
            break
    except Exception:
        time.sleep(0.25)

msg = {"model": "m", "max_tokens": 8, "messages": [{"role": "user", "content": "x"}]}
t0 = time.time()
codes = [call(body=msg)[0] for _ in range(4)]
elapsed = time.time() - t0
ok = all(c == 200 for c in codes)
print("  4 requests with a 3-per-6s budget -> codes %s in %.1fs" % (codes, elapsed))
print("  %s  all succeeded (queued, never 429)" % ("PASS " if ok else "FAIL "))
# The 4th must have waited for the window to roll rather than failing.
queued = elapsed > 4
print("  %s  4th request was delayed by the limiter (%.1fs)" % ("PASS " if queued else "FAIL ", elapsed))
proc.terminate()
mock.terminate()
sys.exit(0 if (ok and queued) else 1)
