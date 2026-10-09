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
    gmail_query: str = (
        '(subject:Order_ OR subject:"purchase order" OR subject:PO OR "PO number" '
        "OR subject:quote OR subject:quotation OR subject:RFQ) "
        "newer_than:30d -in:sent -category:promotions"
    )
    internal_domains: list[str] = field(default_factory=lambda: list(DEFAULT_INTERNAL_DOMAINS))
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

    email_signature: str = "Best regards,\nXinyan (Tony) Zhang, PhD\nCreative Biostructure"
    accounting_email: str = ""

    db_path: str = "sales_pipeline.db"
    auto_push: bool = False

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
            gmail_query=env("GMAIL_QUERY") or d.gmail_query,
            internal_domains=_list(env("INTERNAL_DOMAINS"), d.internal_domains),
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
            email_signature=(env("EMAIL_SIGNATURE") or d.email_signature).replace("\\n", "\n"),
            accounting_email=env("ACCOUNTING_EMAIL", ""),
            db_path=env("DB_PATH") or d.db_path,
            auto_push=_bool(env("AUTO_PUSH"), d.auto_push),
        )
