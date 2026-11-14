import asyncio
from datetime import date

from httpx import ASGITransport, AsyncClient

from gateway import kitchen
from gateway.auth import principal_for_key
from gateway.models import Offer, OrderableReason


def test_menu_merges_ingredients_and_identifies_unknown_dishes():
    result = kitchen.compile_ingredients(kitchen.KitchenRequest(
        servings=10, dishes=["Salmon soup", "Roasted potatoes", "Chef's surprise"]))
    potatoes = next(item for item in result["ingredients"] if item["ingredient"] == "potato")
    assert potatoes["quantity"] == 3.9
    assert potatoes["unit"] == "KG" and potatoes["estimated"]
    assert potatoes["dishes"] == ["salmon soup", "roasted potatoes"]
    assert result["unresolved_dishes"] == ["chef's surprise"]


def test_recipe_overrides_dish_and_scales_grams_and_kilos():
    recipes = kitchen.recipes_from_text("Roasted potatoes (4)\n400 g potatoes\n0.4 kg potato\n10 ml rapeseed oil", 20)
    result = kitchen.compile_ingredients(kitchen.KitchenRequest(
        servings=20, dishes=["Roast potatoes"], recipes=recipes))
    assert [(item["quantity"], item["unit"]) for item in result["ingredients"]] == [(4, "KG"), (.05, "L")]
    assert not any(item["estimated"] for item in result["ingredients"])


def test_stockout_options_are_live_and_dish_specific(monkeypatch):
    buyer = principal_for_key("demo-hotel-lookup-key")
    monkeypatch.setattr(kitchen, "_candidate_ids", lambda name, *_: [name])
    monkeypatch.setattr(kitchen.audit, "log", lambda *args, **kwargs: None)
    good = Offer(product_id="turnip", sales_unit="KG", unit_price=2, net_weight_kg=1, available_qty=20,
                 orderable=True, reason=OrderableReason.ok)
    monkeypatch.setattr(kitchen.service, "get_offers", lambda ids, _: ([good] if "turnip" in ids else [], None))
    request = kitchen.SourceRequest(servings=10, dishes=["Roasted potatoes", "Salmon soup"],
                                    delivery_date=date(2026, 11, 16), unavailable_ingredients=["potatoes"])
    potatoes = next(row for row in kitchen.source_ingredients(buyer, request)["ingredients"] if row["ingredient"] == "potato")
    assert potatoes["status"] == "stockout"
    swap = potatoes["alternatives"][0]
    assert swap["ingredient"] == "turnip" and swap["compatible_dishes"] == ["roasted potatoes"]
    assert swap["review_required"] and swap["plan"]["coverage"] == 1
    assert swap["suggested_quantity"] == 2.2


def test_kitchen_portal_reuses_mcp_and_creates_no_orders(monkeypatch):
    from gateway.api import app
    monkeypatch.setattr(kitchen.audit, "log", lambda *args, **kwargs: None)

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            payload = {"kind": "menu", "text": "Tomato salad", "servings": 20}
            assert (await client.post("/client/kitchen", json=payload)).status_code == 401
            response = await client.post("/client/kitchen", json=payload, headers={"X-API-Key": "demo-hotel-client-key"})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["ingredients"][0]["quantity"] == 2.6
            assert "draft" not in result

    asyncio.run(run())
