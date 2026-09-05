"""Offline tests of the protocol translation layer (no network)."""

import os, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = str(REPO / "proxy" / "server.py")
MOCK_BACKEND = str(REPO / "tests" / "mock_backend.py")
RECORD = os.environ.get("HCC_MOCK_RECORD", str(pathlib.Path(tempfile.gettempdir()) / "mock_requests.jsonl"))
import json
os.environ.setdefault("HETZNER_API_KEY", "dummy")
sys.path.insert(0, str(REPO / "proxy"))
import server

P = F = 0
def check(name, cond, detail=""):
    global P, F
    if cond:
        P += 1; print(f"  PASS  {name}")
    else:
        F += 1; print(f"  FAIL  {name}  {detail}")

print("== anthropic_to_openai ==")

# 1. plain user message
o = server.anthropic_to_openai({"model":"x","messages":[{"role":"user","content":"hi"}]})
check("plain user message", o["messages"] == [{"role":"user","content":"hi"}], o["messages"])

# 2. system string
o = server.anthropic_to_openai({"messages":[{"role":"user","content":"hi"}],"system":"be nice"})
check("system string -> system msg", o["messages"][0] == {"role":"system","content":"be nice"}, o["messages"])

# 3. Claude Code style system: list of blocks w/ cache_control
sysblocks = [{"type":"text","text":"A","cache_control":{"type":"ephemeral"}},{"type":"text","text":"B"}]
o = server.anthropic_to_openai({"messages":[{"role":"user","content":"hi"}],"system":sysblocks})
check("system block list flattened", o["messages"][0]["content"] == "A\nB", o["messages"][0])

# 4. assistant tool_use -> tool_calls
msgs = [{"role":"user","content":"weather?"},
        {"role":"assistant","content":[{"type":"text","text":"checking"},
                                       {"type":"tool_use","id":"toolu_1","name":"get_weather","input":{"city":"Berlin"}}]}]
o = server.anthropic_to_openai({"messages":msgs})
am = o["messages"][-1]
check("assistant tool_use -> tool_calls",
      am["role"]=="assistant" and am["tool_calls"][0]["function"]["name"]=="get_weather"
      and json.loads(am["tool_calls"][0]["function"]["arguments"])=={"city":"Berlin"}, am)

# 5. tool_result round trip  (Claude Code sends these as a USER message)
msgs = [{"role":"user","content":"weather?"},
        {"role":"assistant","content":[{"type":"tool_use","id":"toolu_1","name":"get_weather","input":{"city":"Berlin"}}]},
        {"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"18C"}]}]
o = server.anthropic_to_openai({"messages":msgs})
roles = [m["role"] for m in o["messages"]]
print("      roles:", roles)
print("      last two:", json.dumps(o["messages"][-2:]))
check("tool_result becomes role=tool", "tool" in roles, roles)
check("NO spurious empty user message after tool_result",
      not any(m["role"]=="user" and m.get("content")=="" for m in o["messages"]), o["messages"])
check("tool message is last (correct ordering)", roles[-1]=="tool", roles)

# 6. tool_result with list content
msgs=[{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":[{"type":"text","text":"ok"}]}]}]
o = server.anthropic_to_openai({"messages":msgs})
check("tool_result list content flattened", o["messages"][0]["content"]=="ok", o["messages"])

# 7. tool schema translation
o = server.anthropic_to_openai({"messages":[{"role":"user","content":"h"}],
     "tools":[{"name":"f","description":"d","input_schema":{"type":"object","properties":{"a":{"type":"string"}}}}]})
check("tools translated", o["tools"][0]["function"]["name"]=="f" and o["tool_choice"]=="auto", o.get("tools"))

# 8. image block
img={"type":"image","source":{"type":"base64","media_type":"image/png","data":"AAAA"}}
o = server.anthropic_to_openai({"messages":[{"role":"user","content":[img,{"type":"text","text":"what?"}]}]})
c = o["messages"][0]["content"]
check("image -> image_url multipart", isinstance(c,list) and any(b.get("type")=="image_url" for b in c), c)
check("text kept alongside image", isinstance(c,list) and any(isinstance(b,str) or b.get("type")=="text" for b in c), c)

# 9. thinking blocks are dropped, not crashed
o = server.anthropic_to_openai({"messages":[{"role":"assistant","content":[{"type":"thinking","thinking":"hmm","signature":"s"},{"type":"text","text":"answer"}]}]})
check("thinking block tolerated", o["messages"][0]["content"]=="answer", o["messages"])

# 10. passthrough params
o = server.anthropic_to_openai({"messages":[{"role":"user","content":"h"}],"max_tokens":100,"temperature":0.2,"stop_sequences":["X"]})
check("max_tokens/temperature passed", o["max_tokens"]==100 and o["temperature"]==0.2, o)
check("stop_sequences forwarded as stop", "stop" in o, "stop_sequences dropped -> stop sequences ignored upstream")

print("== openai_to_anthropic ==")
r = {"choices":[{"message":{"content":"hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}
a = server.openai_to_anthropic(r,"claude-sonnet-4")
check("text block built", a["content"]==[{"type":"text","text":"hello"}], a["content"])
check("stop_reason 'stop' -> 'end_turn' (valid Anthropic value)", a["stop_reason"]=="end_turn",
      f"got {a['stop_reason']!r}; Anthropic allows end_turn|max_tokens|stop_sequence|tool_use")
check("usage mapped", a["usage"]=={"input_tokens":5,"output_tokens":2}, a["usage"])

r = {"choices":[{"message":{"content":None,"tool_calls":[{"id":"c1","function":{"name":"f","arguments":'{"a":1}'}}]},"finish_reason":"tool_calls"}]}
a = server.openai_to_anthropic(r,"m")
check("tool_calls -> tool_use", a["content"][0]["type"]=="tool_use" and a["content"][0]["input"]=={"a":1}, a["content"])
check("finish_reason tool_calls -> tool_use", a["stop_reason"]=="tool_use", a["stop_reason"])

r = {"choices":[{"message":{"content":"x"},"finish_reason":"length"}]}
check("length -> max_tokens", server.openai_to_anthropic(r,"m")["stop_reason"]=="max_tokens")

r = {"choices":[{"message":{"content":None,"tool_calls":[{"id":"c1","function":{"name":"f","arguments":"NOT JSON"}}]},"finish_reason":"tool_calls"}]}
a = server.openai_to_anthropic(r,"m")
check("malformed tool args do not crash", a["content"][0]["input"]=={"_raw_arguments":"NOT JSON"}, a["content"])

a = server.openai_to_anthropic({},"m")
check("empty upstream response tolerated", a["content"]==[] , a)

print(f"\nUNIT: {P} passed, {F} failed")
