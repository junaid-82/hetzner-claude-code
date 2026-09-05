"""A tiny OpenAI-compatible backend so the bridge can be tested without Hetzner capacity.

It records every payload it receives to a temp file so the tests can assert on
exactly what the bridge sent upstream.
"""

import os, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = str(REPO / "proxy" / "server.py")
MOCK_BACKEND = str(REPO / "tests" / "mock_backend.py")
RECORD = os.environ.get("HCC_MOCK_RECORD", str(pathlib.Path(tempfile.gettempdir()) / "mock_requests.jsonl"))
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


lock = threading.Lock()
# Scripted behaviour, popped per request: ("ok", text) | ("tool",) | ("fail", n_times)
STATE = {"fail_next": 0}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json({"object": "list", "data": [{"id": "Qwen/Qwen3.6-35B-A3B-FP8"}, {"id": "Qwen3.8-27B"}]})
        else:
            self._json({"error": "nope"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n).decode())
        if self.path.endswith("/_control"):
            STATE["fail_next"] = int(body.get("fail_next", 0))
            self._json({"ok": True})
            return
        if self.headers.get("Authorization") != "Bearer test-upstream-key":
            self._json({"error": "bad key"}, 401)
            return
        with lock:
            with open(RECORD, "a") as f:
                f.write(json.dumps(body) + "\n")

        if body.get("_fail") or STATE["fail_next"] > 0:
            STATE["fail_next"] -= 1
            self._json({"error": "inference error: ServiceUnavailable"}, 503)
            return

        last = body["messages"][-1]
        text = last.get("content") if isinstance(last.get("content"), str) else "[multipart]"

        if body.get("tools") and "call the tool" in json.dumps(body["messages"]).lower():
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_abc", "type": "function",
                 "function": {"name": body["tools"][0]["function"]["name"], "arguments": '{"city":"Berlin"}'}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": "echo:" + str(text)[:120]}
            finish = "stop"

        self._json({"id": "chatcmpl-1", "object": "chat.completion", "model": body.get("model"),
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7}})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    open(RECORD, "w").close()
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
