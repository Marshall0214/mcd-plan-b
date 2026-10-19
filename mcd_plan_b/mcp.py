"""Small synchronous Streamable HTTP client for the official read-only tools.

Supports JSON and SSE responses, session IDs, initialization and pagination.
No background subscription, server-initiated requests or mutating tools.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ENDPOINT = "https://mcp.mcd.cn"
READ_TOOLS = frozenset({
    "now-time-info", "query-nearby-stores", "query-meals", "query-meal-detail",
    "query-store-coupons", "calculate-price", "order-list", "query-order",
    "query-my-coupons", "list-nutrition-foods", "campaign-calendar",
})


class MCPError(ValueError):
    pass


class Client:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        if not self.token:
            raise MCPError("请通过 MCD_MCP_TOKEN 环境变量提供 Token。")
        self.session = None
        self.version = "2025-03-26"
        self.sequence = 0

    def _request(self, method, params=None, notification=False):
        self.sequence += 1
        request_id = self.sequence
        body = {"jsonrpc": "2.0", "method": method}
        if not notification:
            body["id"] = request_id
        if params is not None:
            body["params"] = params
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if method != "initialize":
            headers["MCP-Protocol-Version"] = self.version
        request = urllib.request.Request(ENDPOINT, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                self.session = response.headers.get("Mcp-Session-Id", self.session)
                if notification:
                    return None
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    data = []
                    for raw_line in response:
                        line = raw_line.decode("utf-8").rstrip("\r\n")
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip(" "))
                        elif not line and data:
                            message = json.loads("\n".join(data))
                            data = []
                            if message.get("id") == request_id:
                                return self._result(message)
                    raise MCPError("MCP 事件流结束，未收到对应结果。")
                message = json.load(response)
                if not isinstance(message, dict) or message.get("id") != request_id:
                    raise MCPError("MCP 响应 ID 与请求不匹配。")
                return self._result(message)
        except urllib.error.HTTPError as exc:
            hints = {401: "Token 无效或过期", 403: "无访问权限", 429: "触发限流，请稍后重试"}
            raise MCPError(f"MCP HTTP {exc.code}：{hints.get(exc.code, '请求失败')}。") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise MCPError("MCP 网络连接失败或超时；未自动重试。") from None

    @staticmethod
    def _result(message):
        if "error" in message:
            # Never echo arbitrary remote error text, which may contain credentials.
            raise MCPError(f"MCP 返回协议错误（代码 {message['error'].get('code', 'unknown')}）。")
        if "result" not in message:
            raise MCPError("MCP 响应缺少 result。")
        return message["result"]

    def initialize(self):
        result = self._request("initialize", {
            "protocolVersion": self.version,
            "capabilities": {},
            "clientInfo": {"name": "mcd-plan-b", "version": "0.1.0"},
        })
        self.version = result["protocolVersion"]
        self._request("notifications/initialized", notification=True)
        return result

    def tools(self):
        collected, cursor, seen = [], None, set()
        while True:
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            collected.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return collected
            if cursor in seen:
                raise MCPError("MCP 工具分页游标重复。")
            seen.add(cursor)

    def call(self, name, arguments):
        if name not in READ_TOOLS:
            raise MCPError("此 CLI 仅开放点餐规划所需的只读工具。下单请在宿主中选定方案后执行。")
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise MCPError("MCP 工具执行失败；请检查已发现的 inputSchema 与调用参数。")
        return result


def payload(result):
    """Prefer structured content; otherwise decode text JSON without guessing fields."""
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            pass
    return texts
