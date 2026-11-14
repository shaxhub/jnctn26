"""Catalog fallback for a small set of produce ingredients with recognizable Finnish names."""
from .models import Offer, SearchRequest
from .search import search

# Keep fallback within a catalog category and an ingredient family.
_INGREDIENTS = ("porkkana", "peruna", "tomaatti", "sipuli", "sitruuna", "omen", "basilika")


def candidates(offer: Offer, claims: list[str], allergens: list[str]) -> list[str]:
    if not offer.category or not offer.name:
        return []
    ingredient = next((name for name in _INGREDIENTS if name in offer.name.casefold()), None)
    if not ingredient:
        return []
    matches = search(SearchRequest(text=ingredient, category=offer.category,
                                   free_from=claims, exclude_allergens=allergens, limit=8))
    return [item.id for item in matches.results if item.id != offer.product_id and item.category == offer.category]
