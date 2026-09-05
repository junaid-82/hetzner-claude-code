"""Full protocol test of the bridge against a deterministic OpenAI-compatible backend."""

import os, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = str(REPO / "proxy" / "server.py")
MOCK_BACKEND = str(REPO / "tests" / "mock_backend.py")
RECORD = os.environ.get("HCC_MOCK_RECORD", str(pathlib.Path(tempfile.gettempdir()) / "mock_requests.jsonl"))
import json, subprocess, time, threading
import http.client

TOKEN = "local-test-token"
PORT = "8788"
MOCK = "9999"


mock = subprocess.Popen([sys.executable, MOCK_BACKEND, MOCK])
env = dict(os.environ,
           HCC_LOCAL_TOKEN=TOKEN, HCC_PORT=PORT,
           HETZNER_API_KEY="test-upstream-key",
           HETZNER_BASE_URL="http://127.0.0.1:" + MOCK + "/v1",
           HETZNER_MODEL="Qwen/Qwen3.6-35B-A3B-FP8",
           HCC_MAX_RPM="0")  # limiter exercised separately in ratelimit_test.py
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
        print("  FAIL  " + name + "   " + str(detail)[:400])


def call(method, path, body=None, token=TOKEN, timeout=60):
    c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=timeout)
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    c.request(method, path, json.dumps(body) if body is not None else None, hdrs)
    r = c.getresponse()
    data = r.read().decode()
    return r.status, (json.loads(data) if data else None)


def sent():
    with open(RECORD) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    return lines[-1] if lines else None


for _ in range(80):
    try:
        if call("GET", "/health")[0] == 200:
            break
    except Exception:
        time.sleep(0.25)
else:
    print("BRIDGE DID NOT START")
    print(proc.stderr.read())
    sys.exit(1)

print("== routing (the shapes Claude Code actually sends) ==")
s, b = call("POST", "/v1/messages?beta=true", {"model": "claude-sonnet-4-5", "max_tokens": 32,
                                               "messages": [{"role": "user", "content": "hi"}]})
check("POST /v1/messages?beta=true accepted", s == 200, (s, b))
s, b = call("POST", "/v1/messages/count_tokens?beta=true", {"messages": [{"role": "user", "content": "hi"}]})
check("count_tokens with query string accepted", s == 200 and b.get("input_tokens", 0) > 0, (s, b))
s, b = call("GET", "/health?x=1")
check("GET /health with query string", s == 200, (s, b))
s, b = call("GET", "/verify")
check("/verify confirms key + model availability", s == 200 and b.get("ok") and b.get("model_available"), b)

print("== response translation ==")
s, b = call("POST", "/v1/messages", {"model": "claude-sonnet-4-5", "max_tokens": 32, "system": "be terse",
                                     "messages": [{"role": "user", "content": "hello there"}]})
check("non-stream 200", s == 200, b)
check("text block returned", b["content"][0]["type"] == "text" and "hello there" in b["content"][0]["text"], b["content"])
check("stop_reason mapped to end_turn (not raw 'stop')", b["stop_reason"] == "end_turn", b["stop_reason"])
check("usage mapped", b["usage"] == {"input_tokens": 11, "output_tokens": 7}, b["usage"])
up = sent()
check("system prompt forwarded as system role", up["messages"][0] == {"role": "system", "content": "be terse"}, up["messages"][0])
check("upstream model overridden to HETZNER_MODEL", up["model"] == "Qwen/Qwen3.6-35B-A3B-FP8", up["model"])

print("== streaming ==")
c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=60)
c.request("POST", "/v1/messages?beta=true",
          json.dumps({"model": "m", "max_tokens": 32, "stream": True, "messages": [{"role": "user", "content": "stream me"}]}),
          {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
r = c.getresponse()
ctype = r.getheader("Content-Type")
sse = r.read().decode()
events = [l.split(": ", 1)[1] for l in sse.splitlines() if l.startswith("event: ")]
datas = [json.loads(l.split("data: ", 1)[1]) for l in sse.splitlines() if l.startswith("data: ")]
check("stream 200 + event-stream", r.status == 200 and ctype == "text/event-stream", (r.status, ctype))
check("event order message_start..message_stop",
      events[0] == "message_start" and events[-1] == "message_stop" and "message_delta" in events, events)
check("text_delta carries the text", any(d.get("delta", {}).get("type") == "text_delta" and "stream me" in d["delta"]["text"] for d in datas), events)
check("every SSE frame is valid JSON", len(datas) == len(events), (len(datas), len(events)))
check("stream stop_reason legal",
      [d for d in datas if d.get("type") == "message_delta"][0]["delta"]["stop_reason"] in ("end_turn", "max_tokens", "stop_sequence", "tool_use"), datas[-2:])

print("== tool loop (the part that makes Claude Code usable) ==")
tools = [{"name": "get_weather", "description": "w",
          "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}]
s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 64, "tools": tools,
                                     "messages": [{"role": "user", "content": "Call the tool for Berlin"}]})
tu = [x for x in b["content"] if x["type"] == "tool_use"]
check("tool_use returned", s == 200 and bool(tu) and tu[0]["input"] == {"city": "Berlin"}, b["content"])
check("stop_reason tool_use", b["stop_reason"] == "tool_use", b["stop_reason"])

s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 64, "tools": tools, "messages": [
    {"role": "user", "content": "Call the tool for Berlin"},
    {"role": "assistant", "content": [tu[0]]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu[0]["id"], "content": "18C"}]}]})
check("tool_result turn accepted", s == 200, b)
up = sent()
roles = [m["role"] for m in up["messages"]]
print("      upstream roles: " + str(roles))
check("no empty user turn after tool_result",
      not any(m["role"] == "user" and m.get("content") == "" for m in up["messages"]), up["messages"])
check("tool message directly follows the assistant tool_call",
      roles == ["user", "assistant", "tool"], roles)
check("tool_call_id preserved", up["messages"][-1]["tool_call_id"] == tu[0]["id"], up["messages"][-1])

print("== mixed tool_result + text in one user turn ==")
s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 64, "tools": tools, "messages": [
    {"role": "user", "content": "Call the tool for Berlin"},
    {"role": "assistant", "content": [tu[0]]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu[0]["id"], "content": "18C"},
                                 {"type": "text", "text": "now summarise"}]}]})
up = sent()
roles = [m["role"] for m in up["messages"]]
check("tool result ordered before the follow-up text", roles == ["user", "assistant", "tool", "user"], roles)
check("follow-up text preserved", up["messages"][-1]["content"] == "now summarise", up["messages"][-1])

print("== stop_sequences ==")
call("POST", "/v1/messages", {"model": "m", "max_tokens": 32, "stop_sequences": ["END"],
                              "messages": [{"role": "user", "content": "hi"}]})
up = sent()
check("stop_sequences forwarded as OpenAI 'stop'", up.get("stop") == ["END"], up.get("stop"))

print("== auth ==")
check("wrong bearer -> 401", call("GET", "/health", token="nope")[0] == 401)
check("no auth -> 401", call("GET", "/health", token=None)[0] == 401)
c = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=10)
c.request("GET", "/health", None, {"x-api-key": TOKEN})
r = c.getresponse(); r.read()
check("x-api-key header also accepted", r.status == 200, r.status)


def control(n):
    c = http.client.HTTPConnection("127.0.0.1", int(MOCK), timeout=10)
    c.request("POST", "/v1/_control", json.dumps({"fail_next": n}), {"Content-Type": "application/json"})
    c.getresponse().read()


print("== transient upstream 503 is retried, not surfaced ==")
control(2)
t0 = time.time()
s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 32,
                                     "messages": [{"role": "user", "content": "retry me"}]}, timeout=120)
check("recovers from 2 transient 503s", s == 200 and "retry me" in json.dumps(b), (s, b))
print("      recovered in %.1fs" % (time.time() - t0))
control(0)

print("== error surfaces cleanly when upstream stays down ==")
control(99)
s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 32,
                                     "messages": [{"role": "user", "content": "always fails"}]}, timeout=180)
check("persistent failure -> 502 with anthropic error envelope",
      s == 502 and b.get("type") == "error" and b["error"]["type"] == "api_error", (s, b))
control(0)

print("== robustness ==")
s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 32,
                                     "messages": [{"role": "user", "content": "ünïcode ✅ 日本語"}]})
check("unicode round trip", s == 200 and "日本語" in json.dumps(b, ensure_ascii=False), b)
s, b = call("POST", "/v1/messages", {"model": "m", "max_tokens": 32, "messages": [
    {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}},
                                 {"type": "text", "text": "what is this"}]}]})
up = sent()
check("image message forwarded as multipart", s == 200 and isinstance(up["messages"][-1]["content"], list), up["messages"][-1])
res = []


def worker(i):
    try:
        res.append(call("POST", "/v1/messages", {"model": "m", "max_tokens": 16,
                                                 "messages": [{"role": "user", "content": "c%d" % i}]})[0])
    except Exception as e:
        res.append(str(e))


ths = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
check("8 concurrent requests all 200", res == [200] * 8, res)

proc.terminate()
mock.terminate()
print("\nMOCK INTEGRATION: %d passed, %d failed" % (P, F))
sys.exit(1 if F else 0)
