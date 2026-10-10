from sales_pipeline.config import Settings
from sales_pipeline.crm import CustomerCRM, discover_customer_modules
from sales_pipeline.zoho import ZohoCRM

MODULES = [
    {"api_name": "Leads", "plural_label": "Leads", "api_supported": True},
    {"api_name": "Contacts", "plural_label": "Contacts", "api_supported": True},
    {"api_name": "Inquiries", "module_name": "CustomModule3", "plural_label": "询价", "api_supported": True},
    {"api_name": "Hidden", "plural_label": "Inquiry archive", "api_supported": False},
]
# A custom inquiries module: auto-numbered name ("Inquiry-0012345"), its own email/company/phone fields.
CUSTOM_FIELDS = [
    {"api_name": "Name", "data_type": "autonumber", "field_label": "Inquiry No"},
    {"api_name": "Customer_Email", "data_type": "email", "field_label": "Email"},
    {"api_name": "Institution", "data_type": "text", "field_label": "Institution"},
    {"api_name": "Mobile", "data_type": "phone", "field_label": "Mobile"},
]


class FakeZoho:
    def __init__(self, modules=MODULES):
        self.modules, self.searches, self.created = modules, [], []

    def list_modules(self):
        return self.modules

    def module_fields(self, module):
        return CUSTOM_FIELDS if module == "Inquiries" else []

    def find_by_email(self, module, email, fields=None):
        self.searches.append((module, fields))
        return [{"id": "c1"}] if module == "Contacts" and email == "known@x.example" else []

    def create(self, module, record, trigger=True):
        self.created.append((module, record))
        return "new1"


def test_the_inquiries_module_is_found_by_its_label_whatever_its_internal_name():
    assert discover_customer_modules(MODULES) == ["Inquiries", "Leads", "Contacts"]
    assert discover_customer_modules([{"api_name": "Contacts"}]) == ["Contacts"]
    assert discover_customer_modules([{"api_name": "Leads", "plural_label": "Inquiries"},
                                      {"api_name": "Contacts"}]) == ["Leads", "Contacts"]   # renamed Leads
    assert discover_customer_modules([]) == ["Contacts"]


def test_customers_are_searched_on_each_module_s_own_email_field():
    z = FakeZoho()
    crm = CustomerCRM(z, Settings(), tag_map={})
    assert crm.find("known@x.example") == ("Contacts", "c1")
    assert z.searches[0] == ("Inquiries", ["Customer_Email"])
    assert z.searches[1] == ("Leads", ["Email"])       # field list unavailable -> standard fields


def test_new_inquiry_fills_only_fields_the_module_has():
    z = FakeZoho()
    crm = CustomerCRM(z, Settings(), tag_map={})
    assert crm.ensure("pat@lab.example", name="Pat Lee", company="Lab U", phone="555-0100") == ("Inquiries", "new1")
    module, rec = z.created[0]
    assert module == "Inquiries"
    assert rec == {"Customer_Email": "pat@lab.example", "Institution": "Lab U", "Mobile": "555-0100"}
    assert "Name" not in rec                            # auto-numbered by Zoho


def test_explicit_module_setting_wins():
    s = Settings()
    s.zoho_customer_modules = ["Contacts"]
    z = FakeZoho()
    assert CustomerCRM(z, s, tag_map={}).modules() == ["Contacts"]


def test_email_search_across_several_fields():
    class HTTP:
        def __init__(self):
            self.params = None

        def post(self, *a, **k):
            class R:
                status_code = 200

                def json(self):
                    return {"access_token": "t", "expires_in": 3600}
            return R()

        def request(self, method, url, headers=None, timeout=None, **kw):
            self.params = kw.get("params")

            class R:
                status_code = 204
            return R()

    http = HTTP()
    z = ZohoCRM("https://accounts.zoho.com", "https://www.zohoapis.com", "c", "s", "r", session=http)
    z.find_by_email("Inquiries", "a@b.example", ["Email", "Secondary_Email"])
    assert http.params["criteria"] == "((Email:equals:a@b.example)or(Secondary_Email:equals:a@b.example))"
