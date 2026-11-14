"""Seasonal discovery using an explicit demo calendar and live Valio offers."""
from datetime import date

from . import audit, service, store
from .auth import Principal
from .models import SearchRequest, expand_allergens
from .search import normalize_claims, search

# Editorial demo calendar for Finnish menus. Origin is verified from each catalog item.
CALENDAR = {
    "winter": (("Potatoes", "peruna", "17421"), ("Carrots", "porkkana", "1743"), ("Beetroot", "punajuuri", "1743")),
    "spring": (("Asparagus", "parsa", "174"), ("Rhubarb", "raparperi", "174"), ("Spinach", "pinaatti", "174")),
    "summer": (("Strawberries", "mansikka", "174"), ("Tomatoes", "tomaatti", "17401"), ("Peas", "herne", "174")),
    "autumn": (("Apples", "omena", "17412"), ("Carrots", "porkkana", "1743"), ("Parsnips", "palsternakka", "1743")),
}
MONTHS = ("winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer",
          "autumn", "autumn", "autumn", "winter")


def discover(principal: Principal, delivery: date, excluded: list[str], required: list[str]) -> dict:
    if delivery < store.now().date():
        raise service.GatewayError(422, "Choose today or a future delivery date")
    season = MONTHS[delivery.month - 1]
    allergens = set(expand_allergens(excluded + principal.mandate.forbidden_allergens))
    claims = set(normalize_claims(required))
    groups = {}
    for label, keyword, category in CALENDAR[season]:
        products = search(SearchRequest(text=keyword, category=category, exclude_allergens=sorted(allergens),
                                        free_from=required, limit=12)).results
        groups[label] = [product.id for product in products if (product.country or "").casefold() == "fi"]
    ids = list(dict.fromkeys(pid for group in groups.values() for pid in group))
    checked, at = service.get_offers(ids, delivery) if ids else ([], store.now())
    eligible = {offer.product_id: offer for offer in checked if offer.orderable and not offer.stale
                and offer.available_qty is not None and offer.available_qty > 0
                and not offer.unlimited and not allergens.intersection(offer.allergens_contains + offer.allergens_may_contain)
                and claims.issubset(offer.claims) and (principal.mandate.allowed_categories is None or any(
                    (offer.category or "").startswith(code) for code in principal.mandate.allowed_categories))}
    suggestions = []
    for label, matches in groups.items():
        offers = [eligible[pid] for pid in matches if pid in eligible]
        if offers:
            ranked = sorted(offers, key=lambda offer: (offer.reliability is None, -(offer.reliability or 0),
                                                       offer.unit_price, offer.product_id))
            suggestions.append({"ingredient": label, "offers": [item.model_dump(mode="json") for item in ranked[:3]]})
    audit.log("SEASONAL_DISCOVERY", principal.actor, {"season": season, "delivery_date": delivery.isoformat(),
                                                       "ingredients": [item["ingredient"] for item in suggestions]},
              buyer_id=principal.buyer_id)
    return {"season": season, "delivery_date": delivery.isoformat(), "checked_at": at.isoformat(),
            "calendar": "Demo Finnish seasonal calendar", "suggestions": suggestions}
