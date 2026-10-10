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


def test_tags_and_notes_use_the_v8_record_endpoints():
    http = FakeHTTP()
    z = ZohoCRM("https://accounts.zoho.com", "https://www.zohoapis.com", "cid", "sec", "rt", session=http)
    z.add_tags("Leads", "77", ["不买了"])
    z.remove_tags("Leads", "77", ["跟进中", "已报价"])
    z.add_note("Leads", "77", "Follow-up #2 (email)", "text")
    calls = [c for c in http.calls if c[0] == "POST"]
    assert calls[0][1].endswith("/crm/v8/Leads/77/actions/add_tags")
    assert calls[0][2]["json"] == {"tags": [{"name": "不买了"}], "over_write": False}
    assert calls[1][1].endswith("/crm/v8/Leads/77/actions/remove_tags")
    assert calls[1][2]["json"] == {"tags": [{"name": "跟进中"}, {"name": "已报价"}]}
    assert calls[2][1].endswith("/crm/v8/Notes")
    assert calls[2][2]["json"] == {"data": [{"Note_Title": "Follow-up #2 (email)", "Note_Content": "text",
                                            "Parent_Id": {"module": {"api_name": "Leads"}, "id": "77"}}]}
    z.add_tags("Leads", "77", [])                     # nothing to do -> no request
    assert len([c for c in http.calls if c[0] == "POST"]) == 3


def test_existing_zoho_tags_are_mapped_to_stages():
    from sales_pipeline.crm import suggest_tag_map

    m = suggest_tag_map(["VIP", "已报价", "跟进中", "已下单", "不买了", "询价", "无回复"])
    assert m == {"ordered": "已下单", "lost": "不买了", "no_response": "无回复", "quoted": "已报价",
                 "following_up": "跟进中", "inquiry": "询价"}
    assert suggest_tag_map([]) == {"ordered": "已下单", "lost": "不买了", "no_response": "No reply"}


def test_missing_api_permission_gets_a_plain_explanation():
    import pytest

    from sales_pipeline.zoho import NO_API_ACCESS, ZohoError

    class Denied(FakeHTTP):
        def request(self, method, url, headers=None, timeout=None, **kw):
            return Resp(403, {"code": "NO_PERMISSION", "details": {"permissions": ["Crm_Implied_Api_Access"]},
                              "message": "permission denied", "status": "error"})

    z = ZohoCRM("https://accounts.zoho.com", "https://www.zohoapis.com", "cid", "sec", "rt", session=Denied())
    with pytest.raises(ZohoError) as e:
        z.list_modules()
    assert str(e.value) == NO_API_ACCESS and "Profiles" in str(e.value)
