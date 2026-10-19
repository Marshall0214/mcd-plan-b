import io
import json
import unittest
from unittest.mock import patch
import urllib.error

from mcd_plan_b.mcp import Client, MCPError, payload


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Type": "application/json"}


def response(value, headers=None):
    return Response(json.dumps(value).encode(), headers)


class MCPTests(unittest.TestCase):
    def test_initialize_session_and_protocol_headers(self):
        requests = []
        responses = [response({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}},
                              {"Mcp-Session-Id": "session", "Content-Type": "application/json"}),
                     Response(b""), response({"id": 3, "result": {"tools": []}})]
        def send(request, timeout):
            requests.append(request)
            return responses.pop(0)
        with patch("urllib.request.urlopen", side_effect=send):
            c = Client("test-only")
            c.initialize()
            self.assertEqual(c.tools(), [])
        self.assertEqual(requests[1].get_header("Mcp-session-id"), "session")
        self.assertEqual(requests[2].get_header("Mcp-protocol-version"), "2025-03-26")
        self.assertNotIn("id", json.loads(requests[1].data))

    def test_sse_ignores_notifications_and_joins_multiline_data(self):
        stream = (b': heartbeat\n\ndata: {"method":"notifications/message"}\n\n'
                  b'data: {"jsonrpc":"2.0","id":1,\n'
                  b'data: "result":{"tools":[]}}\n\n')
        with patch("urllib.request.urlopen", return_value=Response(stream, {"Content-Type": "text/event-stream"})):
            self.assertEqual(Client("test-only").tools(), [])

    def test_pagination(self):
        c = Client("test-only")
        with patch.object(c, "_request", side_effect=[{"tools": [{"name": "a"}], "nextCursor": "next"},
                                                     {"tools": [{"name": "b"}]}]):
            self.assertEqual([t["name"] for t in c.tools()], ["a", "b"])

    def test_repeating_cursor_stops(self):
        c = Client("test-only")
        with patch.object(c, "_request", return_value={"tools": [], "nextCursor": "same"}):
            with self.assertRaises(MCPError):
                c.tools()

    def test_mutation_blocked_without_request(self):
        c = Client("test-only")
        with patch.object(c, "_request") as request:
            for name in ("create-order", "auto-bind-coupons", "draw-lottery", "cancel-order", "mall-create-order"):
                with self.assertRaises(MCPError):
                    c.call(name, {})
            request.assert_not_called()

    def test_http_error_does_not_echo_remote_text(self):
        error = urllib.error.HTTPError("https://mcp.mcd.cn", 401, "secret-material", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(MCPError) as caught:
                Client("test-only").tools()
        self.assertNotIn("secret-material", str(caught.exception))
        self.assertIn("401", str(caught.exception))

    def test_tool_errors_not_accepted(self):
        c = Client("test-only")
        with patch.object(c, "_request", return_value={"isError": True}):
            with self.assertRaises(MCPError):
                c.call("calculate-price", {})

    def test_payload_structured_and_text_json(self):
        self.assertEqual(payload({"structuredContent": {"data": 1}}), {"data": 1})
        self.assertEqual(payload({"content": [{"type": "text", "text": '{"data":2}'}]}), {"data": 2})


if __name__ == "__main__":
    unittest.main()
