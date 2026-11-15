from typing import Literal

from pydantic import BaseModel, Field

from . import store


class Preferences(BaseModel):
    theme: Literal["light", "dark"] = "light"
    language: Literal["en", "fi"] = "en"
    business: str = Field("", max_length=120)
    address: str = Field("", max_length=240)
    postal_code: str = Field("", pattern=r"^(?:[0-9]{5})?$")
    billing_email: str = Field("", max_length=160)
    payment_method: Literal["invoice", "bank_transfer", "purchase_order"] = "invoice"
    invoice_reference: str = Field("", max_length=80)
    agent_self_order: bool = True
    recurring_prompt: str = Field("", max_length=240)
    recurring_time: str = Field("08:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


def preferences(buyer_id: str) -> Preferences:
    row = store.fetchone("SELECT settings_json FROM workspace_preferences WHERE buyer_id=?", (buyer_id,))
    return Preferences.model_validate_json(row["settings_json"]) if row else Preferences()
