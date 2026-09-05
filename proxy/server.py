import base64
import json
import os
import secrets
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = "127.0.0.1"
PORT = int(os.getenv("HCC_PORT", "8787"))
HETZNER_BASE = os.getenv("HETZNER_BASE_URL", "https://inference.hetzner.com/api/v1").rstrip("/")
HETZNER_MODEL = os.getenv("HETZNER_MODEL", "Qwen/Qwen3.6-35B-A3B-FP8")
HETZNER_API_KEY = os.getenv("HETZNER_API_KEY", "")
LOCAL_TOKEN = os.getenv("HCC_LOCAL_TOKEN", "")


def fail(message, code=500):
    return {"error": {"type": "proxy_error", "message": message}}, code


def text_from_content(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


def anthropic_to_openai(body):
    messages = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": text_from_content(system)})

    for m in body.get("messages", []):
        role = m.get("role", "user")
        content = m.get("content", "")
        blocks = content if isinstance(content, list) else None
        if blocks is None:
            messages.append({"role": role, "content": content})
            continue

        text_parts = []
        tool_calls = []
        for block in blocks:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "image":
                source = block.get("source", {})
                if source.get("type") == "base64":
                    media = source.get("media_type", "image/png")
                    data = source.get("data", "")
                    text_parts.append({"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}})
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", "call_" + uuid.uuid4().hex[:12]),
                    "type": "function",
                    "function": {
                        "name": block.get("name", "tool"),
                        "arguments": json.dumps(block.get("input", {}), separators=(",", ":")),
                    },
                })
            elif btype == "tool_result":
                result = block.get("content", "")
                if isinstance(result, list):
                    result = text_from_content(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": result if isinstance(result, str) else json.dumps(result),
                })

        if role == "assistant" and tool_calls:
            msg = {"role": "assistant", "content": "".join(x for x in text_parts if isinstance(x, str)), "tool_calls": tool_calls}
            messages.append(msg)
        elif role != "tool":
            if any(isinstance(x, dict) for x in text_parts):
                messages.append({"role": role, "content": text_parts})
            else:
                messages.append({"role": role, "content": "\n".join(text_parts)})

    out = {
        "model": HETZNER_MODEL,
        "messages": messages,
        "stream": False,
    }
    for key in ("temperature", "top_p", "max_tokens", "stop"):
        if key in body and body[key] is not None:
            out[key] = body[key]
    if body.get("tools"):
        tools = []
        for tool in body["tools"]:
            if tool.get("name"):
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object"}),
                    },
                })
        if tools:
            out["tools"] = tools
            out["tool_choice"] = "auto"
    return out


def call_hetzner(payload):
    if not HETZNER_API_KEY:
        raise RuntimeError("HETZNER_API_KEY is not configured")
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        HETZNER_BASE + "/chat/completions",
        data=data,
        headers={
            "Authorization": "Bearer " + HETZNER_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hetzner-claude-code/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Hetzner API returned HTTP {e.code}: {raw[:1000]}") from e
    except URLError as e:
        raise RuntimeError(f"Could not reach Hetzner Inference API: {e.reason}") from e


def openai_to_anthropic(result, requested_model):
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    blocks = []
    content = message.get("content")
    if content:
        blocks.append({"type": "text", "text": content})
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments", "{}")
        try:
            args = json.loads(args)
        except Exception:
            args = {"_raw_arguments": args}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", "call_" + uuid.uuid4().hex[:12]),
            "name": fn.get("name", "tool"),
            "input": args,
        })

    usage = result.get("usage") or {}
    stop_reason = choice.get("finish_reason")
    if stop_reason == "tool_calls":
        stop_reason = "tool_use"
    elif stop_reason == "length":
        stop_reason = "max_tokens"
    elif stop_reason not in ("stop", "tool_use", "max_tokens"):
        stop_reason = "end_turn"

    return {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message",
        "role": "assistant",
        "model": requested_model or HETZNER_MODEL,
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "HetznerClaudeCode/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[hcc] " + (fmt % args) + "\n")

    def auth_ok(self):
        if not LOCAL_TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        return secrets.compare_digest(auth, "Bearer " + LOCAL_TOKEN)

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.auth_ok():
            self.send_json({"error": {"type": "authentication_error", "message": "Unauthorized"}}, 401)
            return
        if self.path == "/health":
            self.send_json({"ok": True, "model": HETZNER_MODEL})
        elif self.path == "/v1/models":
            self.send_json({"object": "list", "data": [{"id": HETZNER_MODEL, "object": "model", "owned_by": "hetzner"}]})
        else:
            self.send_json({"error": {"type": "not_found", "message": "Not found"}}, 404)

    def do_POST(self):
        if not self.auth_ok():
            self.send_json({"error": {"type": "authentication_error", "message": "Unauthorized"}}, 401)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": {"type": "invalid_request_error", "message": "Invalid JSON"}}, 400)
            return

        if self.path == "/v1/messages/count_tokens":
            # Claude Code mainly needs a usable estimate here. The backend's exact tokenizer is not exposed by this bridge.
            text = json.dumps(body.get("messages", []), ensure_ascii=False) + json.dumps(body.get("system", ""), ensure_ascii=False)
            self.send_json({"input_tokens": max(1, len(text) // 4)})
            return

        if self.path != "/v1/messages":
            self.send_json({"error": {"type": "not_found", "message": "Not found"}}, 404)
            return

        try:
            upstream = anthropic_to_openai(body)
            result = call_hetzner(upstream)
            response = openai_to_anthropic(result, body.get("model"))
        except Exception as exc:
            self.send_json({"type": "error", "error": {"type": "api_error", "message": str(exc)}}, 502)
            return

        if body.get("stream"):
            self.send_anthropic_stream(response)
        else:
            self.send_json(response)

    def send_anthropic_stream(self, response):
        # The upstream call is buffered deliberately for protocol reliability. We still emit a valid
        # Anthropic event stream, so Claude Code can consume the response exactly as a streaming request.
        message_id = response["id"]
        usage = response.get("usage", {})
        blocks = response.get("content", [])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def event(name, data):
            raw = f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
            self.wfile.write(raw)
            self.wfile.flush()

        event("message_start", {"type": "message_start", "message": {
            "id": message_id, "type": "message", "role": "assistant", "model": response.get("model"),
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": 0}
        }})

        for index, block in enumerate(blocks):
            if block.get("type") == "text":
                event("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})
                event("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": block.get("text", "")}})
            elif block.get("type") == "tool_use":
                event("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": block.get("id"), "name": block.get("name"), "input": {}}})
                event("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block.get("input", {}), separators=(",", ":"))}})
            event("content_block_stop", {"type": "content_block_stop", "index": index})

        event("message_delta", {"type": "message_delta", "delta": {"stop_reason": response.get("stop_reason"), "stop_sequence": None}, "usage": {"output_tokens": usage.get("output_tokens", 0)}})
        event("message_stop", {"type": "message_stop"})


def main():
    if not HETZNER_API_KEY:
        print("HETZNER_API_KEY is not set.", file=sys.stderr)
        raise SystemExit(2)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hetzner Claude Code bridge listening on http://{HOST}:{PORT}")
    print(f"Backend: {HETZNER_BASE}/chat/completions")
    print(f"Model: {HETZNER_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
