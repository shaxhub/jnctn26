"""A guided school lunch proposal with live ingredient sourcing."""
import re
from datetime import date

from . import kitchen, service
from .agent import parse_need_heuristic

SCHOOL = re.compile(r"\b(?:schools?|schoolchildren|pupils|kouluruokailu)\b", re.I)
SERVINGS = re.compile(r"\b([1-9]\d{0,3})\s+(?:children|pupils|schoolchildren|servings|portions)\b", re.I)
BUDGET = re.compile(r"\b(soft|hard)\s+budget\s+(?:is\s+|of\s+)?(?:€\s*)?([\d,]+(?:\.\d{1,2})?)", re.I)
GUIDANCE = "https://www.ruokavirasto.fi/en/foodstuffs/healthy-diet/nutrition-and-food-recommendations/school-age-children-and-teenagers/"


def school_lunch(text: str, today: date, delivery_date: date | None, *, parsed=None, stock_menu=False,
                 language="en"):
    if not SCHOOL.search(text) or not re.search(r"\b(?:feed|lunch|meal|recipe|menu|ruokailu)\b", text, re.I):
        return None
    headcount = SERVINGS.search(text)
    if not headcount:
        raise service.GatewayError(422, "Include the total number of school meals, such as 200 children.")
    servings = int(headcount[1])
    if servings > 5000:
        raise service.GatewayError(422, "Plan up to 5,000 meals at a time.")
    delivery = delivery_date or (parsed.delivery_date if parsed else None) or parse_need_heuristic(text, today).delivery_date
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
    if stock_menu:
        proposal = (
            ("Lentil, potato and carrot stew", [("punainen linssi", 45, "g"), ("potato", 125, "g"),
              ("carrot", 55, "g"), ("tomaattimurska", 50, "g"), ("rapeseed oil", 5, "ml")],
             "Rinse the lentils. Simmer with diced vegetables and tomato until tender, then stir in the oil."),
            ("Cabbage, cucumber and apple salad", [("keräkaali", 25, "g"), ("cucumber", 40, "g"), ("apple", 45, "g")],
             "Wash, slice and toss. Keep chilled until service."),
            ("Oat drink", [("kaurajuoma", 200, "ml")],
             "Verify that the kitchen approves this beverage and check the exact product label."),
        )
    recipes = [kitchen.Recipe(name=name, servings=1, ingredients=[
        kitchen.Ingredient(name=item, amount=quantity, unit=unit) for item, quantity, unit in ingredients
    ]) for name, ingredients, _ in proposal]
    budgets = {match[1].lower(): float(match[2].replace(",", "")) for match in BUDGET.finditer(text)}
    if budgets.get("soft", 0) > budgets.get("hard", float("inf")):
        raise service.GatewayError(422, "The soft budget must be at or below the hard budget.")
    generated = bool(parsed and parsed.recipes and not stock_menu)
    if generated:
        recipes = parsed.recipes
    excluded = list(parsed.exclude_allergens) if parsed else []
    if peanut:
        excluded.append("peanuts")
    if lactose or re.search(r"\b(?:milk allergy|dairy.free|no dairy|without milk)\b", lower):
        excluded.append("milk")
    request = kitchen.SourceRequest(servings=servings, recipes=recipes, delivery_date=delivery,
                                    exclude_allergens=list(dict.fromkeys(excluded))[:20])
    details = {"servings": servings, "delivery_date": delivery.isoformat(), "budgets": budgets,
               "generated": generated,
               "recipes": ([{"name": recipe.name} for recipe in recipes] if generated else
                           [{"name": name, "method": method} for name, _, method in proposal]),
               "guidance_url": GUIDANCE,
               "dietary_note": "This proposal uses one shared menu for all servings to cover the stated "
                               "lactose and peanut restrictions where requested, without assuming the groups are separate.",
               "verification": "The school kitchen must verify every requested diet, exact supplier labels, "
                               "cross-contact controls and nutrition against its meal standards before ordering or serving. "
                               "The catalog does not establish legal compliance or allergen safety.",
               "serving_note": "Plan drinking water and the school’s approved meal beverage separately."}
    if language == "fi":
        details.update(
            dietary_note="Sama ruokalista on suunniteltu kaikille annoksille pyydetyt ruokarajoitteet huomioiden.",
            verification="Keittiön on tarkistettava ruokavaliot, tuotteiden pakkausmerkinnät, ristikontaminaation "
                         "ehkäisy ja ravitsemus koulun ateriaohjeiden mukaisesti ennen tilaamista tai tarjoilua.",
            serving_note="Varaa juomavesi ja keittiön hyväksymä ruokajuoma.",
        )
        if not generated:
            translated = [
                ("Linssi-peruna-porkkanapata", "Huuhtele linssit. Hauduta kasvisten kanssa kypsäksi ja lisää rypsiöljy."),
                ("Kaali-kurkku-omenasalaatti" if stock_menu else "Tomaatti-omenasalaatti",
                 "Pese, pilko ja sekoita. Säilytä kylmässä tarjoiluun asti."),
                ("Kaurajuoma" if stock_menu else "Täysjyväleipä", "Tarkista tuotteen pakkausmerkinnät ennen tarjoilua."),
            ]
            details["recipes"] = [{"name": name, "method": method} for name, method in translated]
    return request, details
