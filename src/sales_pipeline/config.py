"""Settings loaded from environment variables (or a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [v.strip().lower() for v in value.split(",") if v.strip()]


def _ints(value: str | None, default: list[int]) -> list[int]:
    if not value:
        return default
    return [int(v) for v in value.replace(" ", "").split(",") if v]


DEFAULT_INTERNAL_DOMAINS = [
    "creative-biostructure.com",
    "pr-abacebiology.com",
    "creative-biomart.com",
    "creative-enzymes.com",
]


@dataclass
class Settings:
    gmail_credentials_file: str = "credentials.json"
    gmail_token_file: str = "token.json"
    # The mailbox owner. Filled from the Gmail profile when left empty.
    user_email: str = ""
    # Orders, POs and quote requests ...
    gmail_query: str = (
        '(subject:Order_ OR subject:"purchase order" OR subject:PO OR "PO number" '
        "OR subject:quote OR subject:quotation OR subject:RFQ OR subject:inquiry "
        'OR subject:"Creative Biostructure (ID:" OR from:inquiry@creative-biostructure.com) '
        "newer_than:30d -category:promotions"
    )
    # ... and conversations you (or colleagues, with you in copy) are following up.
    followup_query: str = "in:sent newer_than:60d"
    internal_domains: list[str] = field(default_factory=lambda: list(DEFAULT_INTERNAL_DOMAINS))
    # External senders that are systems, not customers (e.g. the website form mailer).
    system_domains: list[str] = field(default_factory=lambda: ["cd-sciences.info"])
    order_code_regex: str = r"(?<![A-Za-z0-9])CBS[A-Z]{2}\d{8}[A-Z]?(?:-\d+)?(?![A-Za-z0-9])"

    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    use_llm: bool = True

    zoho_accounts_url: str = "https://accounts.zoho.com"
    zoho_api_domain: str = "https://www.zohoapis.com"
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_so_status: str = "Created"
    zoho_auto_create_products: bool = True
    zoho_generic_product_id: str = ""
    # Where customers live in Zoho (module API names), searched in this order; new
    # inquiries are created in the first. Empty = find them automatically: the module
    # labelled Inquiries/询价, then Leads and Contacts if your account has them.
    zoho_customer_modules: list[str] = field(default_factory=list)
    # Lifecycle tags (stage -> Zoho tag); `sales-pipeline zoho-setup --write` fills this file.
    zoho_tag_file: str = "zoho_tags.json"

    # Who the emails come from
    sender_name: str = "Tony"
    sender_phone: str = "1-631-559-9269"
    email_signature: str = "Best regards,\n\n{sender_name}"
    accounting_email: str = "accounting@creative-biomart.com"
    templates_file: str = ""

    # Follow-up cadence after the last email to the customer, in days:
    # 1st follow-up next day, 2nd in 2 days, 3rd in a week, 4th in a month.
    followup_days: list[int] = field(default_factory=lambda: [1, 2, 7, 30])
    first_reply_hours: int = 24      # answer a customer's first email the same day
    close_after_days: int = 14       # after the 4th follow-up, suggest closing (不买了)
    log_manual_replies: bool = True  # also record replies you send from Gmail in Zoho

    db_path: str = "sales_pipeline.db"
    auto_push: bool = False
    scan_interval_min: int = 15

    def signature(self) -> str:
        return self.email_signature.replace("{sender_name}", self.sender_name)

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        d = cls()
        env = os.environ.get
        return cls(
            gmail_credentials_file=env("GMAIL_CREDENTIALS_FILE", d.gmail_credentials_file),
            gmail_token_file=env("GMAIL_TOKEN_FILE", d.gmail_token_file),
            user_email=(env("USER_EMAIL") or "").lower(),
            gmail_query=env("GMAIL_QUERY") or d.gmail_query,
            followup_query=env("FOLLOWUP_QUERY") or d.followup_query,
            internal_domains=_list(env("INTERNAL_DOMAINS"), d.internal_domains),
            system_domains=_list(env("SYSTEM_DOMAINS"), d.system_domains),
            order_code_regex=env("ORDER_CODE_REGEX") or d.order_code_regex,
            anthropic_api_key=env("ANTHROPIC_API_KEY", ""),
            claude_model=env("CLAUDE_MODEL") or d.claude_model,
            use_llm=_bool(env("USE_LLM"), d.use_llm),
            zoho_accounts_url=(env("ZOHO_ACCOUNTS_URL") or d.zoho_accounts_url).rstrip("/"),
            zoho_api_domain=(env("ZOHO_API_DOMAIN") or d.zoho_api_domain).rstrip("/"),
            zoho_client_id=env("ZOHO_CLIENT_ID", ""),
            zoho_client_secret=env("ZOHO_CLIENT_SECRET", ""),
            zoho_refresh_token=env("ZOHO_REFRESH_TOKEN", ""),
            zoho_so_status=env("ZOHO_SO_STATUS") or d.zoho_so_status,
            zoho_auto_create_products=_bool(env("ZOHO_AUTO_CREATE_PRODUCTS"), d.zoho_auto_create_products),
            zoho_generic_product_id=env("ZOHO_GENERIC_PRODUCT_ID", ""),
            zoho_customer_modules=[m.strip() for m in (env("ZOHO_CUSTOMER_MODULES") or "").split(",")
                                   if m.strip()] or d.zoho_customer_modules,
            zoho_tag_file=env("ZOHO_TAG_FILE") or d.zoho_tag_file,
            sender_name=env("SENDER_NAME") or d.sender_name,
            sender_phone=env("SENDER_PHONE") if env("SENDER_PHONE") is not None else d.sender_phone,
            email_signature=(env("EMAIL_SIGNATURE") or d.email_signature).replace("\\n", "\n"),
            accounting_email=(env("ACCOUNTING_EMAIL") if env("ACCOUNTING_EMAIL") is not None
                              else d.accounting_email).lower(),
            templates_file=env("TEMPLATES_FILE", ""),
            followup_days=_ints(env("FOLLOWUP_DAYS"), d.followup_days),
            first_reply_hours=int(env("FIRST_REPLY_HOURS") or d.first_reply_hours),
            close_after_days=int(env("CLOSE_AFTER_DAYS") or d.close_after_days),
            log_manual_replies=_bool(env("LOG_MANUAL_REPLIES"), d.log_manual_replies),
            db_path=env("DB_PATH") or d.db_path,
            auto_push=_bool(env("AUTO_PUSH"), d.auto_push),
            scan_interval_min=int(env("SCAN_INTERVAL_MIN") or d.scan_interval_min),
        )
