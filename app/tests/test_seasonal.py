from datetime import date

from gateway import seasonal
from gateway.auth import principal_for_key
from gateway.models import Offer, OrderableReason, ProductSummary, SearchResult
from test_portals import gateway


def test_seasonal_discovery_checks_origin_stock_freshness_and_diet(gateway, monkeypatch):
    def products(request):
        ids = ["good", "stale", "trace", "imported"] if request.text == "porkkana" else []
        return SearchResult(total_matches=len(ids), results=[
            ProductSummary(id=pid, sales_unit="KG", base_unit="KG",
                           country="se" if pid == "imported" else "fi")
            for pid in ids])

    def offers(ids, delivery):
        assert ids == ["good", "stale", "trace"]
        return [Offer(product_id=pid, sales_unit="KG", unit_price=2, orderable=True,
                      available_qty=25, country="fi", reason=OrderableReason.ok, stale=pid == "stale",
                      allergens_may_contain=["AM"] if pid == "trace" else []) for pid in ids], seasonal.store.now()

    monkeypatch.setattr(seasonal, "search", products)
    monkeypatch.setattr(seasonal.service, "get_offers", offers)
    result = seasonal.discover(principal_for_key("demo-hospital-key"), date(2026, 11, 16), [], [])
    assert result["season"] == "autumn"
    assert [item["product_id"] for item in result["suggestions"][0]["offers"]] == ["good"]
