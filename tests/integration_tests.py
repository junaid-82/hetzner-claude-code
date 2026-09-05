"""End-to-end tests: real bridge process + real Hetzner backend."""

import os, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = str(REPO / "proxy" / "server.py")
MOCK_BACKEND = str(REPO / "tests" / "mock_backend.py")
RECORD = os.environ.get("HCC_MOCK_RECORD", str(pathlib.Path(tempfile.gettempdir()) / "mock_requests.jsonl"))
import json, subprocess, time, threading
import http.client

TOKEN = "local-test-token-abc123"
PORT = "8787"
env = dict(os.environ, HCC_LOCAL_TOKEN=TOKEN, HCC_PORT=PORT)
proc = subprocess.Popen([sys.executable, SERVER], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
P = F = 0


def check(name, cond, detail=""):
    global P, F
    if cond:
        P += 1
        print("  PASS  " + name)
    else:
        F += 1
        print("  FAIL  " + name + "   " + str(detail)[:300])


def call(method, path, body=None, token=TOKEN, timeout=180):
    c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=timeout)
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    c.request(method, path, json.dumps(body) if body is not None else None, hdrs)
    r = c.getresponse()
    data = r.read().decode()
    return r.status, dict(r.getheaders()), (json.loads(data) if data else None)


for _ in range(60):
    try:
        if call("GET", "/health")[0] == 200:
            break
    except Exception:
        time.sleep(0.25)
else:
    print("SERVER DID NOT START")
    print(proc.stderr.read())
    sys.exit(1)

print("== transport / auth ==")
s, h, b = call("GET", "/health")
check("GET /health 200 + model", s == 200 and b.get("ok") and b.get("model"), b)
s, _, b = call("GET", "/health", token="wrong")
check("wrong token -> 401", s == 401, s)
s, _, b = call("GET", "/health", token=None)
check("no auth header -> 401", s == 401, s)
s, _, b = call("GET", "/v1/models")
check("GET /v1/models lists model", s == 200 and b["data"][0]["id"], b)
s, _, b = call("GET", "/nope")
check("unknown GET -> 404", s == 404, s)
s, _, b = call("POST", "/nope", {})
check("unknown POST -> 404", s == 404, s)
c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=10)
c.request("POST", "/v1/messages", "{bad json", {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
r = c.getresponse()
r.read()
check("malformed JSON -> 400", r.status == 400, r.status)

print("== Claude Code URL shapes ==")
s, _, b = call("POST", "/v1/messages?beta=true",
               {"model": "claude-sonnet-4", "max_tokens": 16, "messages": [{"role": "user", "content": "say OK"}]})
check("POST /v1/messages?beta=true accepted", s == 200,
      "status=" + str(s) + " " + str(b) + "  <-- Claude Code appends ?beta=true")
s, _, b = call("POST", "/v1/messages/count_tokens", {"messages": [{"role": "user", "content": "hello world"}]})
check("count_tokens returns positive int", s == 200 and isinstance(b.get("input_tokens"), int) and b["input_tokens"] > 0, b)

print("== live inference (non-stream) ==")
t0 = time.time()
s, _, b = call("POST", "/v1/messages", {"model": "claude-sonnet-4-5", "max_tokens": 64,
                                        "system": "You are terse.",
                                        "messages": [{"role": "user", "content": "Reply with exactly: PONG"}]})
dt = time.time() - t0
check("non-stream 200", s == 200, b)
if s == 200:
    print("      latency %.1fs  text=%r" % (dt, (b["content"][0]["text"][:80] if b["content"] else None)))
    check("anthropic envelope", b.get("type") == "message" and b.get("role") == "assistant" and b["id"].startswith("msg_"), b.get("type"))
    check("stop_reason is a legal Anthropic value",
          b.get("stop_reason") in ("end_turn", "max_tokens", "stop_sequence", "tool_use"),
          "got " + repr(b.get("stop_reason")))
    check("usage tokens > 0", b["usage"]["input_tokens"] > 0 and b["usage"]["output_tokens"] > 0, b["usage"])

print("== live inference (streaming SSE) ==")
c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=180)
c.request("POST", "/v1/messages",
          json.dumps({"model": "claude-sonnet-4-5", "max_tokens": 64, "stream": True,
                      "messages": [{"role": "user", "content": "Count: 1 2 3"}]}),
          {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
r = c.getresponse()
ctype = r.getheader("Content-Type")
sse = r.read().decode()
check("stream status 200", r.status == 200, r.status)
check("Content-Type is text/event-stream", ctype == "text/event-stream", ctype)
events = [l.split(": ", 1)[1] for l in sse.splitlines() if l.startswith("event: ")]
print("      events: " + str(events))
check("message_start first", events[:1] == ["message_start"], events[:1])
check("message_stop last", events[-1:] == ["message_stop"], events[-1:])
check("has content_block_start/delta/stop",
      set(["content_block_start", "content_block_delta", "content_block_stop"]) <= set(events), events)
check("has message_delta", "message_delta" in events, events)
datas = [json.loads(l.split("data: ", 1)[1]) for l in sse.splitlines() if l.startswith("data: ")]
check("every SSE payload is valid JSON", len(datas) == len(events), str(len(datas)) + " vs " + str(len(events)))
ms = [d for d in datas if d.get("type") == "message_start"]
check("message_start carries message.id", bool(ms) and ms[0]["message"]["id"].startswith("msg_"), ms[:1])
md = [d for d in datas if d.get("type") == "message_delta"]
check("message_delta carries stop_reason", bool(md) and md[0]["delta"].get("stop_reason") is not None, md[:1])

print("== live tool use ==")
tools = [{"name": "get_weather", "description": "Get weather for a city",
          "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
s, _, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 256, "tools": tools,
                                        "messages": [{"role": "user", "content": "Use the get_weather tool for Berlin. Call the tool."}]})
check("tool request 200", s == 200, b)
tu = [x for x in (b.get("content") or []) if x.get("type") == "tool_use"] if s == 200 else []
check("model returned a tool_use block", bool(tu), (str(b.get("content")) if s == 200 else ""))
if tu:
    print("      tool_use: " + json.dumps(tu[0])[:200])
    check("tool_use has id/name/input dict",
          bool(tu[0].get("id")) and tu[0].get("name") == "get_weather" and isinstance(tu[0]["input"], dict), tu[0])
    print("== live tool-result follow-up (the agent loop) ==")
    s2, _, b2 = call("POST", "/v1/messages", {"model": "m", "max_tokens": 256, "tools": tools, "messages": [
        {"role": "user", "content": "Use the get_weather tool for Berlin. Call the tool."},
        {"role": "assistant", "content": [tu[0]]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu[0]["id"], "content": "18C and sunny"}]}]})
    check("tool_result follow-up 200 (agent loop works)", s2 == 200, b2)
    if s2 == 200:
        txt = " ".join(x.get("text", "") for x in b2.get("content", []))
        print("      follow-up text: " + txt[:150].replace("\n", " "))
        check("follow-up consumed the tool result", ("18" in txt or "sunny" in txt.lower()), txt[:200])

print("== robustness ==")
s, _, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 32,
                                        "messages": [{"role": "user", "content": "Echo back: unicode test ünïcode ✅ 日本語"}]})
check("unicode round trip", s == 200, b)
res = []


def worker():
    try:
        res.append(call("POST", "/v1/messages", {"model": "m", "max_tokens": 16,
                                                 "messages": [{"role": "user", "content": "say hi"}]})[0])
    except Exception as e:
        res.append(str(e))


ths = [threading.Thread(target=worker) for _ in range(4)]
[t.start() for t in ths]
[t.join() for t in ths]
check("4 concurrent requests all 200", res == [200] * 4, res)
s, _, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 16, "messages": []})
check("empty messages list does not 500", s in (200, 400, 502), "status=" + str(s) + " " + str(b))

proc.terminate()
print("\nINTEGRATION: %d passed, %d failed" % (P, F))
