import json

import anthropic
import httpx2 as httpx

from sales_pipeline.extract_llm import ClaudeExtractor


def test_request_shape_and_parsing(order_thread):
    seen = {}
    answer = {"is_sales_order": True, "order_code": "CBSRX09242501B-2", "total": 12500,
              "customer": {"company": "Acme Health", "email": "jane.doe@acme-health.com"},
              "items": [{"product_name": "PFAS analysis", "quantity": 1, "unit_price": 12500}]}

    def handler(request: httpx.Request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}})

    ex = ClaudeExtractor("claude-opus-5-5", ["creative-biostructure.com"], api_key="test")
    ex.client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    order = ex.extract(order_thread)

    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert "creative-biostructure.com" in body["system"]
    assert order.customer.company == "Acme Health" and order.total == 12500
