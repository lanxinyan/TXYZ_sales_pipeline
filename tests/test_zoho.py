from sales_pipeline.zoho import ZohoCRM


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, ""

    def json(self):
        return self._data


class FakeHTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, params=None, timeout=None):
        self.calls.append(("TOKEN", url, params))
        return Resp(200, {"access_token": "tok", "expires_in": 3600})

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url, kw, headers))
        if url.endswith("/search"):
            return Resp(204, None)
        return Resp(201, {"data": [{"status": "success", "details": {"id": "123"}}]})


def test_token_refresh_search_and_create():
    http = FakeHTTP()
    z = ZohoCRM("https://accounts.zoho.com", "https://www.zohoapis.com", "cid", "sec", "rt", session=http)
    assert z.find_sales_order("CBSRX09242501B-2") is None
    acc = z.find_or_create_account("Acme (Health), Inc", order=__import__("tests.test_pipeline",
                                                                            fromlist=["x"]).claude_order())
    assert acc == "123"
    token_calls = [c for c in http.calls if c[0] == "TOKEN"]
    assert len(token_calls) == 1  # cached
    search = http.calls[1]
    assert search[1] == "https://www.zohoapis.com/crm/v8/Sales_Orders/search"
    assert search[3]["Authorization"] == "Zoho-oauthtoken tok"
    acc_search = http.calls[2]
    assert acc_search[2]["params"]["criteria"] == r"(Account_Name:equals:Acme \(Health\)\, Inc)"
    create = http.calls[3]
    assert create[0] == "POST" and create[2]["json"]["data"][0]["Account_Name"] == "Acme (Health), Inc"
