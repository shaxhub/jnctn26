import {orderThread, stageName} from "./order_thread.js";
import {$, auditTrail, date, dateTime, feedback, gatewayNow, lineItems, money, node, number, pill, portalUrl, request, table, translate} from "./common.js";

const buyer = $("buyer");
export const buyerKey = () => buyer.dataset.hosted === "true" ? "" : "demo-" + buyer.value + "-client-key";
let scope = 0;
let queryVersion = 0;
let basket = null;

export function editBasket(quote) {
  basket = {id:quote.quote_id, delivery:quote.delivery_date, lines:new Map()};
  for (const line of quote.lines) {
    const previous = basket.lines.get(line.product_id);
    basket.lines.set(line.product_id, {...line, quantity:line.quantity + (previous?.quantity || 0)});
  }
  $("chat-delivery-date").value = basket.delivery;
  location.hash = "products";
  renderBasket();
}

function renderBasket() {
  const target = $("shopping-basket");
  target.hidden = !basket;
  target.replaceChildren();
  if (!basket) return;
  const state = basket;
  target.append(node("h2", tr("Selected products", "Valitut tuotteet")));
  const form = node("form", "", "workspace-form");
  for (const [sku, item] of state.lines) {
    const label = node("label", (item.name || sku) + " · " + item.sales_unit);
    const quantity = node("input");
    quantity.type = "number";
    quantity.min = "0.000001";
    quantity.max = "1000000";
    quantity.step = "any";
    quantity.required = true;
    quantity.value = item.quantity;
    quantity.addEventListener("input", () => { item.quantity = quantity.valueAsNumber; });
    const remove = node("button", tr("Remove", "Poista"));
    remove.type = "button";
    remove.addEventListener("click", () => { state.lines.delete(sku); renderBasket(); });
    label.append(quantity);
    form.append(label, remove);
  }
  const save = node("button", tr("Save draft", "Tallenna luonnos"), "primary");
  save.disabled = !state.lines.size;
  const cancel = node("button", tr("Cancel changes", "Peru muutokset"));
  cancel.type = "button";
  cancel.addEventListener("click", () => { basket = null; renderBasket(); });
  const notice = node("p", "", "feedback");
  notice.hidden = true;
  notice.setAttribute("role", "status");
  form.append(save, cancel, notice);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const delivery = $("chat-delivery-date").value || state.delivery;
    if (!delivery) {
      feedback(notice, tr("Choose a delivery date before saving.", "Valitse toimituspäivä ennen tallennusta."), true);
      return;
    }
    for (const [, item] of state.lines) {
      if (!Number.isFinite(item.quantity) || item.quantity <= 0 || item.quantity > 1_000_000) {
        feedback(notice, tr("Enter a valid quantity above 0 for each product.",
          "Syötä jokaiselle tuotteelle määrä, joka on suurempi kuin 0."), true);
        return;
      }
    }
    state.delivery = delivery;
    save.disabled = true;
    try {
      const quote = await request("/client/basket" + (state.id ? "?quote_id=" + encodeURIComponent(state.id) : ""),
        buyerKey(), {delivery_date:delivery, quantities:Object.fromEntries(
          [...state.lines].map(([sku, item]) => [sku, item.quantity])),
          exclude_allergens:[...new Set([...state.lines.values()].flatMap(item => item.excludeAllergens || []))],
          required_claims:[...new Set([...state.lines.values()].flatMap(item => item.requiredClaims || []))]});
      if (basket !== state) return;
      basket = null;
      renderBasket();
      showDraft(quote);
      window.dispatchEvent(new Event("draft-changed"));
    } catch (error) {
      feedback(notice, error.message, true);
    } finally {
      save.disabled = false;
    }
  });
  target.append(form);
}

const tr = (en, fi) => document.documentElement.lang === "fi" ? fi : en;

export function ticketNameForm(name, url, key) {
  const form = node("form", "", "form-row");
  const label = node("label", tr("Ticket name", "Tilauksen nimi"));
  const input = node("input");
  input.value = name || "";
  input.required = true;
  input.maxLength = 100;
  const button = node("button", tr("Save name", "Tallenna nimi"));
  const notice = node("p", "", "feedback");
  notice.setAttribute("role", "status");
  label.append(input);
  form.append(label, button, notice);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    button.disabled = true;
    try {
      const updated = await request(url + "/name", key, {name:input.value});
      input.value = updated.name;
      feedback(notice, tr("Name saved.", "Nimi tallennettu."));
      window.dispatchEvent(new CustomEvent("ticket-renamed", {detail:{url, name:updated.name}}));
    } catch (error) {
      feedback(notice, error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  return form;
}


export function showDraft(quote, outcome, target = $("draft")) {
  target.classList.toggle("empty", !quote && !outcome);
  target.replaceChildren();
  if (outcome) {
    target.append(pill(outcome.status), node("p", outcome.name || outcome.order_id, "cell-note"),
      node("p", outcome.policy.reasons.join(" "), "cell-note"));
    return;
  }
  if (!quote) {
    target.append(tr("Create a ticket draft to review quantities, prices and the delivery date.",
      "Luo tilausluonnos tarkistaaksesi määrät, hinnat ja toimituspäivän."));
    return;
  }
  target.append(node("h3", quote.name || tr("Order draft", "Tilausluonnos")), node("p", tr("Delivery ", "Toimitus ") + date(quote.delivery_date)),
    node("p", "Quote expires " + dateTime(quote.expires_at), "cell-note"),
    lineItems(quote.lines), node("p", money.format(quote.total_net) + " excl. VAT", "ticket-total"));
  const proof = node("details", "", "plan-option");
  const key = node("a", "Quote verification keys");
  key.href = portalUrl("/.well-known/jwks.json");
  proof.append(node("summary", "Signed quote"), key, node("pre", quote.signature));
  target.append(proof);
  const history = node("details", "", "plan-option");
  history.append(node("summary", "Recurring order comparison"));
  history.addEventListener("toggle", async () => {
    if (!history.open || history.childElementCount > 1) return;
    const pending = node("p", "Comparing recent deliveries…", "cell-note");
    history.append(pending);
    try {
      const comparison = await request("/client/tickets/" + encodeURIComponent(quote.quote_id) + "/recurring", buyerKey());
      pending.remove();
      if (!comparison.baselines.length) {
        history.append(node("p", "A baseline needs at least three confirmed deliveries on this weekday.", "cell-note"));
        return;
      }
      history.append(table(["SKU", "Usual quantity", "Proposed quantity", "Unit price change"],
        comparison.baselines.map(item => [item.product_id, number.format(item.baseline_quantity) + " " + item.sales_unit,
          number.format(item.current_quantity) + " " + item.sales_unit,
          item.price_change_pct == null ? "—" : number.format(item.price_change_pct) + "%"])));
    } catch (error) {
      pending.textContent = error.message;
    }
  });
  target.append(history);
  if (quote.policy_preview.reasons.length) {
    target.append(node("p", quote.policy_preview.reasons.map(translate).join(" "), "cell-note"));
  }
  const button = node("button", "Submit ticket to Aimo", "primary");
  if (new Date(quote.expires_at) <= gatewayNow()) {
    button.disabled = true;
    target.append(node("p", "This draft expired. Save a revised draft to refresh the quote.", "feedback"));
  }
  const actions = node("div", "", "actions");
  const info = node("p", "", "feedback");
  info.hidden = true;
  info.setAttribute("role", "status");
  actions.append(button);
  target.append(actions, info);
  button.addEventListener("click", async () => {
    const current = scope;
    button.disabled = true;
    feedback(info, "Submitting ticket…");
    try {
      const order = await request("/client/tickets/submit", buyerKey(), {quote_id: quote.quote_id});
      if (current === scope && target.isConnected) {
        showDraft(null, order, target);
        window.dispatchEvent(new Event("ticket-submitted"));
      }
    } catch (error) {
      feedback(info, error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

function offerRows(offers, deliveryDate, need) {
  return offers.map(item => {
    const product = node("span", item.name || item.product_id);
    const provenance = item.substitution_source === "catalog_ingredient_match" ? " · Catalog suggestion" : "";
    product.append(node("small", item.product_id + " · " + item.sales_unit + (item.country ? " · " + item.country : "") + provenance, "cell-note"));
    const availability = item.orderable
      ? item.unlimited ? "Supplier stock unverified" : number.format(item.available_qty) + " " + item.sales_unit
      : item.reason.replaceAll("_", " ");
    const row = [product, item.unit_price == null ? "—" : money.format(item.unit_price),
      availability, item.available_date ? date(item.available_date) : "—",
      item.co2_per_kg == null ? "—" : number.format(item.co2_per_kg),
      item.reliability == null ? "—" : number.format(item.reliability * 100) + "%"];
    if (deliveryDate) {
      const add = node("button", tr("Add", "Lisää"));
      add.disabled = !item.orderable || item.unit_price == null || item.stale;
      add.addEventListener("click", () => {
        if (basket && basket.delivery !== deliveryDate) {
          feedback($("chat-status"), tr("Search for the basket’s delivery date before adding items.",
            "Hae tuotteita ostoskorin toimituspäivälle ennen lisäämistä."), true);
          return;
        }
        basket ||= {id:null, delivery:deliveryDate, lines:new Map()};
        const existing = basket.lines.get(item.product_id);
        const lot = item.allowed_lot_size || 1;
        basket.lines.set(item.product_id, {...item, quantity:(existing?.quantity || 0) + lot,
          excludeAllergens:[...(existing?.excludeAllergens || []), ...(need?.exclude_allergens || [])],
          requiredClaims:[...(existing?.requiredClaims || []), ...(need?.free_from || [])]});
        renderBasket();
      });
      row.push(add);
    }
    return row;
  });
}

function showResults(result, requestData) {
  const target = $("results");
  target.replaceChildren();
  if (!result.offers?.length) return;
  if (result.offers.some(offer => offer.stale) ||
      Object.values(result.alternatives ?? {}).some(group => group.some(offer => offer.stale))) {
    target.append(node("p", "Valio is temporarily unavailable. Some offers use recently cached data. Drafting requires a live check.", "feedback"));
  }
  const eta = result.delivery_estimate;
  if (eta) {
    target.append(node("p", eta.status === "estimated"
      ? "Estimated travel from Rautatientori · " + eta.travel_minutes_min + "–" + eta.travel_minutes_max + " min after dispatch"
      : "Travel estimate is unavailable for this postcode.", "feedback"));
  }
  const plans = result.plan?.plans ?? [];
  if (plans.length) target.append(node("h3", "Order plans", "results"));
  for (const plan of plans) {
    const details = node("details", "", "plan-option");
    details.open = plan.label === "best";
    const summary = node("summary", plan.label[0].toUpperCase() + plan.label.slice(1) + " · " +
      money.format(plan.total_net) + " excl. VAT · " + number.format(plan.coverage * 100) + "% coverage");
    const draftButton = node("button", "Draft this plan");
    draftButton.addEventListener("click", () => sendChat({...requestData, action: "draft",
      plan_lines: plan.lines.map(line => [line.product_id, line.quantity])}));
    details.append(summary, node("p", plan.strategy, "cell-note"), lineItems(plan.lines), draftButton);
    target.append(details);
  }
  const headings = ["Product", "Net price / unit", "Availability", "Earliest date", "kg CO₂e/kg", "Reliability"];
  const delivery = result.need?.delivery_date;
  const basketHeadings = delivery ? [...headings, tr("Basket", "Ostoskori")] : headings;
  target.append(node("h3", tr("Live offers", "Ajantasaiset tarjoukset"), "results"), table(basketHeadings, offerRows(result.offers, delivery, result.need)));
  if (result.next_delivery_options?.length) {
    target.append(node("h3", "Available on a later date", "results"),
      table(headings, offerRows(result.next_delivery_options.map(option => option.offer))));
  }
  for (const [productId, alternatives] of Object.entries(result.alternatives ?? {})) {
    if (alternatives.length) {
      target.append(node("h3", "Alternatives for " + productId, "results"),
        table(basketHeadings, offerRows(alternatives, delivery, result.need)));
    }
  }
}

function repeatForm(order, current, key, dialog) {
  const form = node("form", "", "form-row");
  const label = node("label", "New delivery date");
  const day = node("input");
  day.type = "date";
  day.required = true;
  label.append(day);
  const submit = node("button", "Create repeat draft");
  submit.type = "submit";
  const notice = node("p", "", "feedback");
  notice.hidden = true;
  notice.setAttribute("role", "status");
  form.append(label, submit, notice);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    submit.disabled = true;
    feedback(notice, "Checking current price and stock…");
    try {
      await request("/client/tickets/" + encodeURIComponent(order.order_id) +
        "/repeat?delivery_date=" + encodeURIComponent(day.value), key, {});
      if (current !== scope || !dialog.open) return;
      dialog.close();
      location.hash = "drafts";
    } catch (error) {
      feedback(notice, error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  return form;
}

export async function inspectTicket(id) {
  const dialog = $("ticket-details");
  const target = $("ticket-detail-body");
  const current = scope;
  const key = buyerKey();
  target.replaceChildren(node("p", "Loading ticket…", "empty"));
  dialog.showModal();
  try {
    const url = "/client/requests/" + encodeURIComponent(id);
    const detail = await request(url, key);
    const order = detail.order;
    if (current !== scope || !dialog.open) return;
    const name = ticketNameForm(order.name, url, key);
    target.replaceChildren(name, node("span", stageName(detail.stage, document.documentElement.lang), "tag"), node("p", order.order_id + tr(" · Delivery ", " · Toimitus ") + date(order.delivery_date),
      "cell-note"), lineItems(order.lines), node("p", money.format(order.total_net) + " excl. VAT", "ticket-total"),
      node("h3", "Policy decision", "results"), node("p", order.policy.reasons.join(" ")));
    target.append(orderThread(detail, {url, key, language:document.documentElement.lang}));
    if (order.status === "confirmed") target.append(repeatForm(order, current, key, dialog));
    const audit = await request(url + "/audit", key);
    if (current !== scope || !dialog.open) return;
    target.append(auditTrail(audit));
  } catch (error) {
    if (current === scope && dialog.open) target.append(node("p", error.message, "feedback error"));
  }
}

function showRecipe(recipe, meal) {
  const target = $("results");
  target.replaceChildren(node("h3", "Recipe ingredients", "results"));
  if (meal) {
    const heading = node("h4", "School lunch for " + number.format(meal.servings) + " · " + date(meal.delivery_date));
    const methods = node("ul");
    for (const recipe of meal.recipes) methods.append(node("li", recipe.name + (recipe.method ? " — " + recipe.method : "")));
    const guidance = node("a", "Finnish Food Authority school meal guidance");
    guidance.href = meal.guidance_url;
    const cost = meal.matched_total_net;
    const budget = meal.budgets;
    const summary = [meal.complete ? "Matched basket estimate" : "Matched items only", money.format(cost) + " excl. VAT"];
    if (budget.soft != null) summary.push("Soft budget " + money.format(budget.soft));
    if (budget.hard != null) summary.push("Hard budget " + money.format(budget.hard));
    target.append(heading, node("p", meal.dietary_note), methods, node("p", meal.serving_note),
      node("p", summary.join(" · "), "feedback"));
    if (meal.alternative) target.append(node("p", "This alternative menu was selected using stock for your delivery date.", "cell-note"));
    if (budget.hard != null && cost > budget.hard) target.append(node("p", "Matched items already exceed the hard budget.", "feedback error"));
    else if (budget.soft != null && cost > budget.soft) target.append(node("p", "Matched items already exceed the soft budget.", "feedback"));
    if (!meal.complete) target.append(node("p", "Some ingredients could not be sourced. The price shown is a subtotal.", "feedback"));
    target.append(node("p", meal.verification, "feedback"), guidance);
  }
  const data = recipe.ingredients.map(row => [
    row.product_name || row.ingredient, number.format(row.quantity) + " " + row.unit, row.dishes.join(", "),
    row.status ?? "Add a delivery date to check stock",
    row.sourcing ? lineItems(row.sourcing.plan.lines) : "—"
  ]);
  if (data.length) target.append(table(["Ingredient", "Quantity", "Used in", "Stock", "Matched products"], data));
  if (recipe.unresolved_dishes.length) target.append(node("p", "Unresolved: " + recipe.unresolved_dishes.join(", "), "feedback"));
  for (const row of recipe.ingredients) for (const option of row.alternatives ?? []) {
    const card = node("details", "", "plan-option");
    card.append(node("summary", "Alternative for " + row.ingredient + ": " + option.ingredient),
      node("p", option.compatible_dishes.join(", ") + " · " + option.culinary_note), lineItems(option.plan.lines));
    target.append(card);
  }
}

async function sendChat(requestData) {
  const current = ++queryVersion;
  const buttons = Array.from($("chat").querySelectorAll("[type=submit]"));
  buttons.forEach(button => { button.disabled = true; });
  if (requestData.action !== "lookup") showDraft(null);
  feedback($("chat-status"), "Interpreting your request and checking the catalog…");
  $("results").replaceChildren();
  try {
    const result = await request("/client/chat", buyerKey(), {...requestData, language:document.documentElement.lang === "fi" ? "fi" : "en"});
    if (current !== queryVersion) return;
    feedback($("chat-status"), document.documentElement.lang !== "fi" ? result.message :
      result.draft ? "Tilausluonnos on valmis tarkistettavaksi." :
      result.recipe ? "Ostoslista on valmis tarkistettavaksi. Tarkista saatavuus ja mahdolliset puutteet." :
      result.offers?.length ? "Tarkista saatavuus ja lisää haluamasi tuotteet ostoskoriin." : "Tuotteita ei löytynyt. Kokeile tuotenimeä tai tuotenumeroa.");
    $("assistant-mode").textContent = result.mode === "guided_meal" ? tr("School meal planning with catalog sourcing.", "Kouluaterian suunnittelu tuotevalikoiman perusteella.") :
      result.mode === "gemini-4-hydrogen" ? tr("Interpreted by Agent Dairy", "Agent Dairy tulkitsi pyynnön") :
      result.mode === "guided_fallback" ? tr("Gemini was unavailable. Guided search handled this request.", "Gemini ei ollut käytettävissä. Pyyntö käsiteltiin ohjatulla haulla.") :
      tr("Guided search handled this request.", "Pyyntö käsiteltiin ohjatulla haulla.");
    if (result.recipe) showRecipe(result.recipe, result.meal);
    else showResults(result, requestData);
    if (result.draft) showDraft(result.draft);
  } catch (error) {
    if (current === queryVersion) feedback($("chat-status"), error.message, true);
  } finally {
    if (current === queryVersion) buttons.forEach(button => { button.disabled = false; });
  }
}

$("chat-delivery-date").addEventListener("input", () => {
  if (basket && $("chat-delivery-date").value) {
    basket.delivery = $("chat-delivery-date").value;
  }
});

$("chat").addEventListener("submit", event => {
  event.preventDefault();
  const text = $("message").value.trim();
  if (!text) return;
  const delivery = $("chat-delivery-date").value || null;
  sendChat({text, action: event.submitter?.value || "shop",
    postal_code: $("postcode").value || null, delivery_date: delivery,
    include_substitutes: $("substitutes").checked});
});

$("seasonal-pick").addEventListener("click", async () => {
  const button = $("seasonal-pick");
  const target = $("seasonal-results");
  const delivery = $("chat-delivery-date").value || new Intl.DateTimeFormat("sv-SE", {
    timeZone:"Europe/Helsinki", year:"numeric", month:"2-digit", day:"2-digit",
  }).format(gatewayNow());
  if (!delivery) {
    target.textContent = "Enter a valid delivery date above.";
    $("chat-delivery-date").focus();
    return;
  }
  const current = scope;
  button.disabled = true;
  target.textContent = "Checking seasonal stock…";
  try {
    const result = await request("/client/seasonal?delivery_date=" + encodeURIComponent(delivery), buyerKey());
    if (current !== scope) return;
    target.replaceChildren(node("p", result.calendar + " · " + date(result.delivery_date), "cell-note"));
    if (!result.suggestions.length) target.append(node("p", "No seasonal products with verified stock on this date."));
    for (const group of result.suggestions) {
      target.append(node("h4", group.ingredient), table(["Product", "Net price / unit", "Stock", "Earliest date",
        "kg CO₂e/kg", "Reliability"], offerRows(group.offers)));
    }
  } catch (error) {
    if (current === scope) target.replaceChildren(node("p", error.message, "feedback error"));
  } finally {
    if (current === scope) button.disabled = false;
  }
});

buyer.addEventListener("change", () => {
  scope += 1;
  basket = null;
  renderBasket();
  queryVersion += 1;
  $("seasonal-pick").disabled = false;
  $("seasonal-results").replaceChildren();
  $("assistant-mode").textContent = "Describe your request or paste a recipe with quantities.";
  $("chat").querySelectorAll("[type=submit]").forEach(button => { button.disabled = false; });
  showDraft(null);
  $("results").replaceChildren();
  feedback($("chat-status"), "");
});
