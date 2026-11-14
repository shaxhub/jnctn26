"""Demo dish templates and culinary substitutions, reviewed by the buyer before purchasing."""

# Amounts per serving in grams, millilitres, or whole items.
# Ingredient names are shared with the catalogue aliases and substitution rules.
DISHES = {
    "roasted potatoes": [("potato", 220, "g"), ("rapeseed oil", 12, "ml")],
    "mashed potatoes": [("potato", 200, "g"), ("milk", 35, "ml"), ("butter", 10, "g")],
    "roasted carrots": [("carrot", 150, "g"), ("rapeseed oil", 10, "ml")],
    "tomato salad": [("tomato", 130, "g"), ("red onion", 20, "g"), ("basil", 3, "g")],
    "green salad": [("lettuce", 75, "g"), ("cucumber", 50, "g"), ("tomato", 60, "g")],
    "cucumber salad": [("cucumber", 150, "g"), ("dill", 2, "g")],
    "tomato soup": [("tomato", 220, "g"), ("onion", 35, "g"), ("cream", 25, "ml"), ("basil", 3, "g")],
    "carrot soup": [("carrot", 200, "g"), ("potato", 60, "g"), ("onion", 25, "g"), ("cream", 25, "ml")],
    "vegetable soup": [("potato", 120, "g"), ("carrot", 90, "g"), ("onion", 30, "g"), ("leek", 40, "g")],
    "salmon soup": [("salmon", 120, "g"), ("potato", 170, "g"), ("leek", 35, "g"), ("cream", 45, "ml"), ("dill", 3, "g")],
    "baked salmon": [("salmon", 180, "g"), ("lemon", 20, "g"), ("dill", 3, "g")],
    "mushroom risotto": [("risotto rice", 80, "g"), ("mushroom", 110, "g"), ("onion", 30, "g"), ("butter", 12, "g")],
    "pasta primavera": [("pasta", 95, "g"), ("zucchini", 85, "g"), ("bell pepper", 65, "g"), ("tomato", 70, "g")],
    "greek salad": [("tomato", 100, "g"), ("cucumber", 80, "g"), ("red onion", 20, "g"), ("feta", 50, "g")],
    "fruit salad": [("apple", 70, "g"), ("pear", 60, "g"), ("orange", 70, "g")],
    "apple crumble": [("apple", 150, "g"), ("oats", 35, "g"), ("butter", 20, "g"), ("sugar", 18, "g")],
}

DISH_ALIASES = {"roast potatoes": "roasted potatoes", "finnish salmon soup": "salmon soup",
                "lohikeitto": "salmon soup", "tomaattikeitto": "tomato soup", "perunamuusi": "mashed potatoes"}

# Catalog terms are Finnish stems. English remains available for unlisted recipe ingredients.
SEARCH_TERMS = {
    "potato": "peruna", "carrot": "porkkana", "tomato": "tomaatti", "onion": "sipuli",
    "red onion": "punasipuli", "shallot": "salottisipuli", "leek": "purjo", "basil": "basilika",
    "dill": "tilli", "parsley": "persilja", "cucumber": "kurkku", "lettuce": "salaatti",
    "zucchini": "kesäkurpitsa", "bell pepper": "paprika", "apple": "omena", "pear": "päärynä",
    "orange": "appelsiini", "lemon": "sitruuna", "salmon": "lohi", "milk": "maito",
    "butter": "voi", "cream": "kerma", "rapeseed oil": "rypsiöljy", "mushroom": "herkkusieni",
    "risotto rice": "risotto", "pasta": "pasta", "feta": "feta", "oats": "kaurahiutale", "sugar": "sokeri",
    "parsnip": "palsternakka", "turnip": "nauris", "spinach": "pinaatti", "lime": "lime",
}
INGREDIENT_ALIASES = {"potatoes": "potato", "tomatoes": "tomato", "carrots": "carrot",
                      "onions": "onion", "apples": "apple", "lemons": "lemon",
                      "cucumbers": "cucumber", "mushrooms": "mushroom", "pears": "pear",
                      "spring onions": "spring onion", "courgette": "zucchini"}
# Restrict cross-ingredient swaps to known dish uses. Every swap needs buyer review.
SWAPS = {
    ("roasted potatoes", "potato"): ("turnip", "Roasts well. Expect a lighter texture and a sharper flavour."),
    ("roasted carrots", "carrot"): ("parsnip", "Roast with the same method. Parsnip is sweeter and softer."),
    ("carrot soup", "carrot"): ("parsnip", "Blends to a similar texture. Rebalance the sweetness."),
    ("vegetable soup", "leek"): ("onion", "Sauté first. The onion flavour will be stronger."),
    ("tomato salad", "red onion"): ("shallot", "Slice thinly. It gives a milder allium flavour."),
    ("tomato salad", "basil"): ("parsley", "Use as a fresh garnish. The aroma will change."),
    ("baked salmon", "lemon"): ("lime", "Use for acidity. Start with less juice and adjust to taste."),
    ("green salad", "lettuce"): ("spinach", "Use fresh baby leaves for a similar role. The flavour is stronger."),
    ("apple crumble", "apple"): ("pear", "Choose firm pears and reduce added sugar if needed."),
    ("fruit salad", "apple"): ("pear", "Use firm pears cut to the same size."),
}
