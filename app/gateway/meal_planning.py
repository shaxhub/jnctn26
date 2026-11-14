"""A guided school lunch proposal with live ingredient sourcing."""
import re
from datetime import date

from . import kitchen, service
from .agent import parse_need_heuristic

SCHOOL = re.compile(r"\b(?:schools?|schoolchildren|pupils|kouluruokailu)\b", re.I)
SERVINGS = re.compile(r"\b([1-9]\d{0,3})\s+(?:children|pupils|schoolchildren|servings|portions)\b", re.I)
BUDGET = re.compile(r"\b(soft|hard)\s+budget\s+(?:is\s+|of\s+)?(?:€\s*)?([\d,]+(?:\.\d{1,2})?)", re.I)
GUIDANCE = "https://www.ruokavirasto.fi/en/foodstuffs/healthy-diet/nutrition-and-food-recommendations/school-age-children-and-teenagers/"


def school_lunch(text: str, today: date, delivery_date: date | None):
    if not SCHOOL.search(text) or not re.search(r"\b(?:feed|lunch|meal|recipe|menu|ruokailu)\b", text, re.I):
        return None
    headcount = SERVINGS.search(text)
    if not headcount:
        raise service.GatewayError(422, "Include the total number of school meals, such as 200 children.")
    servings = int(headcount[1])
    if servings > 5000:
        raise service.GatewayError(422, "Plan up to 5,000 meals at a time.")
    delivery = delivery_date or parse_need_heuristic(text, today).delivery_date
    if delivery < today:
        raise service.GatewayError(422, "Choose today or a future delivery date.")
    lower = text.casefold()
    lactose = "lactose" in lower or "laktoos" in lower
    peanut = "peanut" in lower or "maapähkin" in lower
    # The default lunch deliberately uses no dairy or peanut ingredients. Any other
    # requested diet still needs verification before this proposal can become an order.
    proposal = (
        ("Lentil, potato and carrot stew", [("red lentils", 45, "g"), ("potato", 125, "g"),
                                            ("carrot", 55, "g"), ("rapeseed oil", 5, "ml")],
         "Rinse the lentils, then simmer with diced vegetables until tender. Stir in rapeseed oil."),
        ("Tomato and apple side salad", [("tomato", 55, "g"), ("apple", 45, "g")],
         "Wash and dice the produce. Keep the salad chilled and separate until service."),
        ("Wholegrain bread", [("wholegrain bread", 30, "g")],
         "Portion the bread separately after checking the exact product label."),
    )
    recipes = [kitchen.Recipe(name=name, servings=1, ingredients=[
        kitchen.Ingredient(name=item, amount=quantity, unit=unit) for item, quantity, unit in ingredients
    ]) for name, ingredients, _ in proposal]
    budgets = {match[1].lower(): float(match[2].replace(",", "")) for match in BUDGET.finditer(text)}
    if budgets.get("soft", 0) > budgets.get("hard", float("inf")):
        raise service.GatewayError(422, "The soft budget must be at or below the hard budget.")
    excluded = ["peanuts"] if peanut else []
    if lactose or re.search(r"\b(?:milk allergy|dairy.free|no dairy|without milk)\b", lower):
        excluded.append("milk")
    request = kitchen.SourceRequest(servings=servings, recipes=recipes, delivery_date=delivery,
                                    exclude_allergens=excluded)
    details = {"servings": servings, "delivery_date": delivery.isoformat(), "budgets": budgets,
               "recipes": [{"name": name, "method": method} for name, _, method in proposal],
               "guidance_url": GUIDANCE,
               "dietary_note": "This proposal uses one shared menu for all servings to cover the stated "
                               "lactose and peanut restrictions where requested, without assuming the groups are separate.",
               "verification": "The school kitchen must verify every requested diet, exact supplier labels, "
                               "cross-contact controls and nutrition against its meal standards before ordering or serving. "
                               "The catalog does not establish legal compliance or allergen safety.",
               "serving_note": "Plan drinking water and the school’s approved meal beverage separately."}
    return request, details
