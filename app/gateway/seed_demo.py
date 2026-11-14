"""Add labelled demo history without deleting existing data; safe to rerun.

Uses current catalog products and an offer snapshot for illustrative history.
Current drafts retain the checked prices and normal two-hour quote expiry.
Run with the same DB_PATH, CATALOG_DB_PATH and SIGNING_KEY_PATH as the server:
    python -m gateway.seed_demo
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

from . import audit, service, store
from .auth import Admin, Principal
from .config import TZ, settings
from .models import Need, OffersRequest, QuoteRequest, expand_allergens
from .policy import load_mandate
from .workspace import Message, ShipmentUpdate, advance, send_message

ADMIN = Admin(actor="admin:demo-seed")


def candidates() -> dict[str, list[str]]:
    with sqlite3.connect(f"file:{settings.catalog_db_path}?mode=ro", uri=True) as db:
        return {name: [row[0] for row in db.execute(
            "SELECT id FROM products WHERE category=? "
            "ORDER BY CASE WHEN sales_unit IN ('ST','KG') THEN 0 ELSE 1 END,id LIMIT 12", (category,))]
            for name, category in (("milk", "10400"), ("potato", "17421"), ("carrot", "17431"))}


def seed(*, backup: bool = True) -> dict:
    base = store.now()
    original_clock = store.get_demo_now()
    delivery = base.date() + timedelta(days=3)
    groups = candidates()
    if not all(groups.values()):
        raise RuntimeError("The catalog needs milk, potato and carrot products. Load a catalog first.")
    snapshot, _ = service.get_offers(list(dict.fromkeys(sku for group in groups.values() for sku in group)),
                                     delivery, fresh=True)
    usable = {offer.product_id: offer for offer in snapshot if offer.orderable and offer.unit_price
              and offer.reason.value == "ok" and (offer.available_qty is None or offer.available_qty >= 5)}
    safe = lambda offer: not set(expand_allergens(["milk", "gluten"])).intersection(
        offer.allergens_contains + offer.allergens_may_contain)
    milk = next((usable[sku] for sku in groups["milk"] if sku in usable), None)
    vegetables = [usable[sku] for sku in groups["potato"] + groups["carrot"] if sku in usable and safe(usable[sku])]
    if milk is None or len(vegetables) < 2:
        raise RuntimeError("Need an orderable milk product and two milk/gluten-free vegetables; no data was seeded.")
    first = vegetables[0]
    second = next((offer for offer in vegetables if offer.category != first.category), vegetables[1])
    # Substitution evidence refers to another real product in the same category when possible.
    preferred = next((sku for sku in groups["potato"] + groups["carrot"]
                      if sku != first.product_id and service.get_products([sku])[sku].category == first.category),
                     second.product_id)
    if backup and settings.db_path.exists():
        destination = Path(str(settings.db_path) + base.strftime(".before-seed-%Y%m%d-%H%M%S.db"))
        with sqlite3.connect(settings.db_path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        print(f"Backup: {destination}")

    counts = {"created": 0, "skipped": 0}

    def checked_offers(ids, day, **_options):
        now = store.now()
        results = []
        for sku in ids:
            offer = usable[sku]
            changes = {}
            if day != delivery:
                changes = {"closing_time": datetime.combine(day - timedelta(days=1), time(18), TZ),
                           "price_valid_to": None, "available_date": day}
            results.append(offer.model_copy(update=changes))
        return results, now

    def scenario(buyer, label, items, *, at=base, day=delivery, stage=None, draft=False,
                 substitution=False, reject=False):
        name = "[Demo] " + label
        if store.fetchone("SELECT 1 FROM ticket_names WHERE name=?", (name,)):
            counts["skipped"] += 1
            return
        store.set_demo_now(at)
        principal = Principal(buyer, "client", "demo-kitchen", load_mandate(buyer))
        inquiry = audit.log("CLIENT_INQUIRY", principal.actor,
                            {"action": "draft", "text": label + ". Sample scenario for the judging demo.",
                             "demo_seed": True, "price_source": "current offer snapshot"}, buyer_id=buyer)
        token = audit.inquiry_sequence.set(inquiry["seq"])
        try:
            service.check_offers(principal, OffersRequest(product_ids=[offer.product_id for offer, _ in items],
                                                          delivery_date=day))
            need = None
            if substitution:
                need = Need(item="Potatoes for kitchen service", quantity=1, unit="KG", delivery_date=day,
                            preferred_product_ids=[preferred])
            quote = service.create_quote(principal, QuoteRequest(delivery_date=day, need=need,
                lines=[{"product_id": offer.product_id, "quantity": quantity} for offer, quantity in items]), name=name)
            if not draft:
                order = service.place_order(principal, quote.quote_id, "Labelled sample order for the judging demo.")
                if reject and order.status == "pending_approval":
                    order = service.decide_approval(ADMIN, order.approval_id, "reject", "Sample: quantity needs revision.")
                if stage and order.status == "pending_approval":
                    order = service.decide_approval(ADMIN, order.approval_id, "approve", "Sample: kitchen confirmed the quantities.")
                if stage and order.status != "confirmed":
                    raise RuntimeError(f"{name}: expected confirmation, got {order.status}")
                send_message(principal, order.order_id, Message(text="[Demo] Please use the kitchen loading entrance."))
                send_message(ADMIN, order.order_id, Message(text="[Demo] Noted. We will notify the kitchen before arrival."))
                if stage:
                    stages = ["retrieving", "on_delivery", "almost_there", "arrived"]
                    for index, state in enumerate(stages[:stages.index(stage) + 1]):
                        store.set_demo_now(at + timedelta(minutes=20 * (index + 1)))
                        advance(ADMIN, order.order_id, ShipmentUpdate(stage=state))
        finally:
            audit.inquiry_sequence.reset(token)
        counts["created"] += 1

    # Overrides apply only to this process. The running app keeps its live configuration.
    try:
        with patch.object(service, "get_offers", checked_offers), patch.dict(os.environ, {
            "GEMINI_API_KEY": "", "AIMO_FULFILLMENT_CHECKS": "0"}):
            for buyer, title in (("hotel", "Hotel"), ("hospital", "Hospital")):
                for index, days in enumerate((10, 7, 4, 2)):
                    day = base.date() - timedelta(days=days)
                    at = datetime.combine(day - timedelta(days=1), time(9), TZ)
                    if at.date() < load_mandate(buyer).issued_at:
                        continue
                    scenario(buyer, f"{title} weekly kitchen delivery {index + 1}",
                             [(first, 2 + index), (second, 1 + index)], at=at, day=day, stage="arrived")
                for index, stage in enumerate(("retrieving", "on_delivery")):
                    scenario(buyer, f"{title} {'lunch ingredients' if index == 0 else 'next kitchen delivery'}",
                             [(first, 3), (second, 2)] + ([(milk, 3)] if buyer == "hotel" else []),
                             at=base - timedelta(hours=2), stage=stage)
                scenario(buyer, f"{title} vegetable prep — ready to review", [(first, 4), (second, 2)], draft=True)
                scenario(buyer, f"{title} replacement potatoes — approval needed", [(first, 2)], substitution=True)
            scenario("hospital", "Hospital milk order — allergen rule rejection", [(milk, 2)], reject=True)
            store.set_demo_now(base)
            service.expire_pending()
            if not store.verify_chain()["ok"]:
                raise RuntimeError("Audit chain verification failed")
    finally:
        store.set_demo_now(original_clock)
    counts["orders"] = store.fetchone("SELECT count(*) AS n FROM orders")["n"]
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-backup", action="store_true", help="Skip the SQLite backup (for disposable databases).")
    args = parser.parse_args()
    print(seed(backup=not args.no_backup))


if __name__ == "__main__":
    main()
