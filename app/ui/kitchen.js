import {$, date, feedback, lineItems, money, node, number, request} from "./common.js";

const form = $("kitchen-form");
const panel = $("kitchen-panel");
const text = $("kitchen-text");
const format = $("kitchen-format");
const target = $("kitchen-result");
const notice = $("kitchen-status");
const buyer = $("buyer");
const examples = {
  menu: "Salmon soup\nRoasted potatoes\nTomato salad",
  recipes: "Tomato salad (4)\n520 g tomato\n80 g red onion\n12 g basil\n\nRoasted potatoes (4)\n880 g potato\n48 ml rapeseed oil",
};
let version = 0;

function reset() {
  version += 1;
  target.replaceChildren();
  feedback(notice, "");
  form.querySelector("button[type=submit]").disabled = false;
  form.removeAttribute("aria-busy");
}

function showWorkspace(mode) {
  const planning = mode === "kitchen";
  panel.hidden = !planning;
  $("product-panel").hidden = planning;
  $("products-mode").setAttribute("aria-pressed", String(!planning));
  $("kitchen-mode").setAttribute("aria-pressed", String(planning));
}

function ingredientCard(row) {
  const card = node("article", "", "ingredient");
  const header = node("div", "", "ingredient-head");
  const label = {available:"Available", partial:"Partial stock", stockout:"Stock-out",
    unmatched:"Needs a match", unverified:"Availability unverified"};
  const amount = number.format(row.quantity) + " " + row.unit;
  header.append(node("h4", row.ingredient), node("strong", amount, "ingredient-quantity"));
  card.append(header, node("p", row.dishes.join(" / ") + (row.estimated ? " · Template estimate" : " · Recipe amount"), "cell-note"));
  if (row.status) card.append(node("span", label[row.status] ?? row.status, "tag kitchen-" + row.status));
  if (row.sourcing) {
    const plan = row.sourcing.plan;
    const details = node("details", "", "ingredient-offers");
    details.append(node("summary", money.format(plan.total_net) + " excl. VAT · " +
      number.format(plan.coverage * 100) + "% of ingredient"), lineItems(plan.lines));
    card.append(details);
  }
  for (const alternative of row.alternatives ?? []) {
    const option = node("details", "", "ingredient-offers ingredient-swap");
    option.open = true;
    option.append(node("summary", "Try " + alternative.ingredient + " · " +
      number.format(alternative.suggested_quantity) + " " + alternative.unit),
      node("p", "For " + alternative.compatible_dishes.join(" / "), "cell-note"),
      node("p", alternative.culinary_note), lineItems(alternative.plan.lines),
      node("p", money.format(alternative.plan.total_net) + " excl. VAT · " +
        number.format(alternative.plan.coverage * 100) + "% coverage · Review before ordering", "cell-note"));
    card.append(option);
  }
  return card;
}

function render(result) {
  const heading = node("div", "", "ingredient-results-head");
  const available = result.ingredients.filter(row => row.status === "available").length;
  heading.append(node("h3", "Ingredient list"), node("p", result.delivery_date
    ? available + " of " + result.ingredients.length + " ingredients covered for " + date(result.delivery_date)
    : result.ingredients.length + " ingredients for " + result.servings_per_dish + " servings per dish", "muted"));
  target.append(heading);
  if (result.unresolved_dishes.length) {
    target.append(node("p", "Add recipes for " + result.unresolved_dishes.join(", ") + ".", "feedback"));
  }
  if (result.cached_offers_excluded) {
    target.append(node("p", "Recently cached offers were excluded. Try again for current stock.", "feedback"));
  }
  const grid = node("div", "", "ingredient-grid");
  for (const ingredient of result.ingredients) grid.append(ingredientCard(ingredient));
  target.append(grid);
  if (result.notes?.length) target.append(node("p", result.notes.join(" "), "cell-note"));
}

function splitList(value) {
  return value.split(",").map(part => part.trim()).filter(Boolean);
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const value = text.value.trim();
  if (!value) return;
  const current = ++version;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  form.setAttribute("aria-busy", "true");
  target.replaceChildren();
  feedback(notice, $("kitchen-date").value ? "Compiling ingredients and checking live offers…" : "Compiling ingredients…");
  try {
    const result = await request("/client/kitchen", "demo-" + buyer.value + "-client-key", {
      text: value,
      kind: format.value,
      servings: Number($("kitchen-servings").value),
      delivery_date: $("kitchen-date").value || null,
      exclude_allergens: splitList($("kitchen-allergens").value),
      unavailable_ingredients: splitList($("kitchen-stockout").value),
    });
    if (current !== version) return;
    feedback(notice, "");
    render(result);
  } catch (error) {
    if (current === version) feedback(notice, error.message, true);
  } finally {
    if (current === version) {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  }
});

function showFormat() {
  const menu = format.value === "menu";
  $("kitchen-text-label").textContent = menu ? "Dish names" : "Recipes and ingredients";
  $("kitchen-hint").textContent = menu ? "Enter one dish per line. Quantities come from demo dish templates."
    : "Start each block with Dish name (servings). Enter one ingredient per line, such as 500 g tomato.";
  text.placeholder = examples[format.value];
}
$("kitchen-example").addEventListener("click", () => {
  text.value = examples[format.value];
  text.focus();
});
format.addEventListener("change", showFormat);
buyer.addEventListener("change", reset);
$("products-mode").addEventListener("click", () => showWorkspace("products"));
$("kitchen-mode").addEventListener("click", () => showWorkspace("kitchen"));
$("open-kitchen").addEventListener("click", () => {
  showWorkspace("kitchen");
  $("kitchen-mode").focus();
  $("kitchen-workspace").scrollIntoView({block:"start"});
});
showFormat();
