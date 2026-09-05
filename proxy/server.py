"""Local adapter exposing Anthropic's Messages API on top of Hetzner Inference.

Claude Code speaks the Anthropic Messages API. Hetzner Inference speaks OpenAI Chat
Completions. This process listens on the loopback interface, translates each request,
and translates the reply back.
"""

import json
import os
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HOST = "127.0.0.1"
PORT = int(os.getenv("HCC_PORT", "8787"))
HETZNER_BASE = os.getenv("HETZNER_BASE_URL", "https://inference.hetzner.com/api/v1").rstrip("/")
HETZNER_MODEL = os.getenv("HETZNER_MODEL", "Qwen/Qwen3.6-35B-A3B-FP8")
HETZNER_API_KEY = os.getenv("HETZNER_API_KEY", "")
LOCAL_TOKEN = os.getenv("HCC_LOCAL_TOKEN", "")
ALLOW_OPEN_ACCESS = os.getenv("HCC_ALLOW_NO_AUTH", "") == "1"

MAX_ATTEMPTS = int(os.getenv("HCC_MAX_ATTEMPTS", "4"))
MAX_RPM = int(os.getenv("HCC_MAX_RPM", "10"))
RATE_WINDOW = float(os.getenv("HCC_RATE_WINDOW", "60"))

RETRY_STATUSES = (429, 500, 502, 503, 504)
ANTHROPIC_STOP_REASONS = ("end_turn", "max_tokens", "stop_sequence", "tool_use")
CHARS_PER_TOKEN = 4


def log(message):
    """Write diagnostics to stderr, which stays available under pythonw.exe."""
    stream = sys.stderr
    if stream:
        stream.write("[hcc] " + message + "\n")
        stream.flush()


class RateLimiter:
    """Hetzner Inference grants 10 requests per 60s per key.

    Callers queue here so the budget is spent in order and every request eventually runs.
    """

    def __init__(self, max_calls, window):
        self.max_calls = max_calls
        self.window = window
        self.calls = []
        self.lock = threading.Lock()

    def acquire(self):
        if self.max_calls <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                self.calls = [t for t in self.calls if now - t < self.window]
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                wait = self.window - (now - self.calls[0]) + 0.05
            log("rate limit reached, waiting %.1fs for the next slot" % wait)
            time.sleep(wait)


limiter = RateLimiter(MAX_RPM, RATE_WINDOW)


# --------------------------------------------------------------------------- translation

def text_from_content(content):
    """Flatten an Anthropic content value to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append("[image]")
        return "\n".join(parts)
    return ""


def _image_part(block):
    source = block.get("source") or {}
    if source.get("type") == "base64":
        url = "data:%s;base64,%s" % (source.get("media_type", "image/png"), source.get("data", ""))
        return {"type": "image_url", "image_url": {"url": url}}
    return None


def _tool_call(block):
    return {
        "id": block.get("id", "call_" + uuid.uuid4().hex[:12]),
        "type": "function",
        "function": {
            "name": block.get("name", "tool"),
            "arguments": json.dumps(block.get("input", {}), separators=(",", ":")),
        },
    }


def _tool_result(block):
    result = block.get("content", "")
    if isinstance(result, list):
        result = text_from_content(result)
    if isinstance(result, str) is False:
        result = json.dumps(result)
    return {"role": "tool", "tool_call_id": block.get("tool_use_id", ""), "content": result}


def _split_blocks(blocks):
    """Sort one message's content blocks into text parts, tool calls and tool results."""
    text_parts, tool_calls, tool_results = [], [], []
    for block in blocks:
        if isinstance(block, dict) is False:
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "image":
            part = _image_part(block)
            if part:
                text_parts.append(part)
        elif btype == "tool_use":
            tool_calls.append(_tool_call(block))
        elif btype == "tool_result":
            tool_results.append(_tool_result(block))
    return text_parts, tool_calls, tool_results


def anthropic_to_openai(body):
    """Build an OpenAI Chat Completions payload from an Anthropic Messages request."""
    messages = []

    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": text_from_content(system)})

    for message in body.get("messages", []):
        role = message.get("role", "user")
        content = message.get("content", "")

        if isinstance(content, list) is False:
            messages.append({"role": role, "content": content if content else ""})
            continue

        text_parts, tool_calls, tool_results = _split_blocks(content)

        # Tool results answer the preceding assistant turn, so they lead this message.
        messages.extend(tool_results)

        if role == "assistant" and tool_calls:
            spoken = "".join(part for part in text_parts if isinstance(part, str))
            messages.append({"role": "assistant", "content": spoken, "tool_calls": tool_calls})
        elif role in ("user", "assistant"):
            multipart = [part for part in text_parts if isinstance(part, dict)]
            if multipart:
                normalised = [p if isinstance(p, dict) else {"type": "text", "text": p} for p in text_parts]
                messages.append({"role": role, "content": normalised})
            else:
                spoken = "\n".join(text_parts)
                stands_alone = len(tool_results) == 0
                if spoken or stands_alone:
                    messages.append({"role": role, "content": spoken})

    payload = {"model": HETZNER_MODEL, "messages": messages, "stream": False}

    for key in ("temperature", "top_p", "max_tokens", "stop"):
        if body.get(key) is not None:
            payload[key] = body[key]
    if body.get("stop_sequences"):
        payload["stop"] = body["stop_sequences"]

    tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object"}),
            },
        }
        for tool in body.get("tools") or []
        if tool.get("name")
    ]
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    return payload


def openai_to_anthropic(result, requested_model):
    """Build an Anthropic Messages response from an OpenAI Chat Completions reply."""
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    blocks = []
    content = message.get("content")
    if content:
        blocks.append({"type": "text", "text": content})

    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        raw_arguments = function.get("arguments", "{}")
        try:
            arguments = json.loads(raw_arguments)
        except Exception:
            arguments = {"_raw_arguments": raw_arguments}
        if isinstance(arguments, dict) is False:
            arguments = {"_raw_arguments": arguments}
        blocks.append({
            "type": "tool_use",
            "id": call.get("id", "call_" + uuid.uuid4().hex[:12]),
            "name": function.get("name", "tool"),
            "input": arguments,
        })

    finish = choice.get("finish_reason")
    if finish == "tool_calls":
        stop_reason = "tool_use"
    elif finish == "length":
        stop_reason = "max_tokens"
    elif finish in ANTHROPIC_STOP_REASONS:
        stop_reason = finish
    else:
        stop_reason = "end_turn"

    usage = result.get("usage") or {}
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


# --------------------------------------------------------------------------- upstream

def hetzner_request(path, payload=None, timeout=600):
    """Perform one call against the Hetzner Inference API."""
    if HETZNER_API_KEY == "":
        raise RuntimeError("HETZNER_API_KEY is required")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        HETZNER_BASE + path,
        data=data,
        headers={
            "Authorization": "Bearer " + HETZNER_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hetzner-claude-code/1.1",
        },
        method="POST" if data else "GET",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def call_hetzner(payload):
    """Send a chat completion, retrying while the upstream reports transient pressure."""
    problem = "The Hetzner Inference API is unavailable."

    for attempt in range(MAX_ATTEMPTS):
        final_attempt = attempt == MAX_ATTEMPTS - 1
        wait = 1.5 * (2 ** attempt)
        try:
            limiter.acquire()
            return hetzner_request("/chat/completions", payload)

        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code in (401, 403):
                raise RuntimeError(
                    "Hetzner rejected the API key (HTTP %d). Run the installer again with a valid key."
                    % error.code
                ) from error
            if error.code == 429:
                problem = "Hetzner rate limit reached (10 requests per minute)."
                wait = max(wait, _retry_after(error, 20.0))
            else:
                problem = "Hetzner returned HTTP %d: %s" % (error.code, body[:500])
            if final_attempt or error.code not in RETRY_STATUSES:
                raise RuntimeError(problem) from error

        except URLError as error:
            problem = "The Hetzner Inference API is unreachable: %s" % (error.reason,)
            if final_attempt:
                raise RuntimeError(problem) from error

        except TimeoutError as error:
            problem = "The Hetzner Inference API timed out."
            if final_attempt:
                raise RuntimeError(problem) from error

        log("upstream busy, retrying in %.1fs (%s)" % (wait, problem[:120]))
        time.sleep(wait)

    raise RuntimeError(problem)


def _retry_after(error, fallback):
    header = error.headers.get("Retry-After") if error.headers else None
    try:
        return float(header)
    except (TypeError, ValueError):
        return fallback


# --------------------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "HetznerClaudeCode/1.1"

    def log_message(self, fmt, *args):
        log(fmt % args)

    def route(self):
        """Return the request path, ignoring any query string."""
        return urlsplit(self.path).path.rstrip("/") or "/"

    def authorised(self):
        if LOCAL_TOKEN == "":
            return True
        header = self.headers.get("Authorization", "")
        if secrets.compare_digest(header, "Bearer " + LOCAL_TOKEN):
            return True
        return secrets.compare_digest(self.headers.get("x-api-key", ""), LOCAL_TOKEN)

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, kind, message, status):
        self.send_json({"type": "error", "error": {"type": kind, "message": message}}, status)

    def do_GET(self):
        if self.authorised() is False:
            self.send_error_json("authentication_error", "Unauthorized", 401)
            return

        path = self.route()
        if path == "/health":
            self.send_json({"ok": True, "model": HETZNER_MODEL})
        elif path == "/verify":
            self.send_json(self.verify_upstream())
        elif path == "/v1/models":
            self.send_json({
                "object": "list",
                "data": [{"id": HETZNER_MODEL, "object": "model", "owned_by": "hetzner"}],
            })
        else:
            self.send_error_json("not_found_error", "Not found", 404)

    def verify_upstream(self):
        """Confirm the configured key works and report which models it may use."""
        try:
            data = hetzner_request("/models", timeout=30)
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:300]
            if error.code in (401, 403):
                return {"ok": False, "error": "Hetzner rejected the API key."}
            return {"ok": False, "error": "Hetzner returned HTTP %d: %s" % (error.code, body)}
        except Exception as error:
            return {"ok": False, "error": "Hetzner is unreachable: %s" % (error,)}

        available = [model.get("id") for model in data.get("data") or []]
        return {
            "ok": True,
            "model": HETZNER_MODEL,
            "model_available": HETZNER_MODEL in available,
            "available_models": available,
        }

    def do_POST(self):
        if self.authorised() is False:
            self.send_error_json("authentication_error", "Unauthorized", 401)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self.send_error_json("invalid_request_error", "Invalid JSON", 400)
            return

        path = self.route()

        if path == "/v1/messages/count_tokens":
            text = (json.dumps(body.get("messages", []), ensure_ascii=False)
                    + json.dumps(body.get("system", ""), ensure_ascii=False))
            self.send_json({"input_tokens": max(1, len(text) // CHARS_PER_TOKEN)})
            return

        if path != "/v1/messages":
            self.send_error_json("not_found_error", "Not found", 404)
            return

        try:
            result = call_hetzner(anthropic_to_openai(body))
            response = openai_to_anthropic(result, body.get("model"))
        except Exception as error:
            self.send_error_json("api_error", str(error), 502)
            return

        if len(response["content"]) == 0:
            response["content"] = [{"type": "text", "text": ""}]

        if body.get("stream"):
            self.send_anthropic_stream(response)
        else:
            self.send_json(response)

    def send_anthropic_stream(self, response):
        """Emit the response as a well-formed Anthropic SSE event stream.

        The upstream call is buffered for protocol reliability, and the client sees the end
        of the stream when the connection closes.
        """
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def event(name, data):
            frame = "event: %s\ndata: %s\n\n" % (name, json.dumps(data, ensure_ascii=False))
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

        usage = response.get("usage", {})
        event("message_start", {"type": "message_start", "message": {
            "id": response["id"], "type": "message", "role": "assistant",
            "model": response.get("model"), "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": 0},
        }})

        for index, block in enumerate(response.get("content", [])):
            if block.get("type") == "text":
                event("content_block_start", {
                    "type": "content_block_start", "index": index,
                    "content_block": {"type": "text", "text": ""}})
                event("content_block_delta", {
                    "type": "content_block_delta", "index": index,
                    "delta": {"type": "text_delta", "text": block.get("text", "")}})
            elif block.get("type") == "tool_use":
                event("content_block_start", {
                    "type": "content_block_start", "index": index,
                    "content_block": {"type": "tool_use", "id": block.get("id"),
                                      "name": block.get("name"), "input": {}}})
                event("content_block_delta", {
                    "type": "content_block_delta", "index": index,
                    "delta": {"type": "input_json_delta",
                              "partial_json": json.dumps(block.get("input", {}), separators=(",", ":"))}})
            event("content_block_stop", {"type": "content_block_stop", "index": index})

        event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": response.get("stop_reason"), "stop_sequence": None},
            "usage": {"output_tokens": usage.get("output_tokens", 0)}})
        event("message_stop", {"type": "message_stop"})


def main():
    if HETZNER_API_KEY == "":
        log("Set HETZNER_API_KEY, then start the bridge again.")
        raise SystemExit(2)

    if LOCAL_TOKEN == "" and ALLOW_OPEN_ACCESS is False:
        log("Set HCC_LOCAL_TOKEN to keep the bridge private to Claude Code, "
            "or set HCC_ALLOW_NO_AUTH=1 to open it to every local program.")
        raise SystemExit(2)

    log("listening on http://%s:%d" % (HOST, PORT))
    log("backend %s/chat/completions" % HETZNER_BASE)
    log("model %s" % HETZNER_MODEL)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
