import {orderThread, stageName} from "./order_thread.js";
import {$, date, feedback, lineItems, money, node, number, pill, portalUrl, request, table} from "./common.js";

const buyer = $("buyer");
export const buyerKey = () => buyer.dataset.hosted === "true" ? "" : "demo-" + buyer.value + "-client-key";
let scope = 0;
let queryVersion = 0;
let seasonalVersion = 0;

function connection() {
  $("mcp-command").textContent = 'claude mcp add --transport http agent-dairy ' + portalUrl("/mcp") +
    ' --header "Authorization: Bearer demo-' + buyer.value + '-key"';
  feedback($("copy-status"), "");
}

export function showDraft(quote, outcome, target = $("draft")) {
  target.classList.toggle("empty", !quote && !outcome);
  target.replaceChildren();
  if (outcome) {
    target.append(pill(outcome.status), node("p", outcome.order_id, "cell-note"),
      node("p", outcome.policy.reasons.join(" "), "cell-note"));
    return;
  }
  if (!quote) {
    target.append("Create a ticket draft to review quantities, prices and the delivery date.");
    return;
  }
  target.append(node("p", "Delivery " + date(quote.delivery_date)),
    node("p", "Quote expires " + new Date(quote.expires_at).toLocaleString("en-FI", {timeZone:"Europe/Helsinki"}), "cell-note"),
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
    target.append(node("p", quote.policy_preview.reasons.join(" "), "cell-note"));
  }
  const button = node("button", "Submit ticket to Aimo", "primary");
  if (new Date(quote.expires_at) <= new Date()) {
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

function offerRows(offers) {
  return offers.map(item => {
    const product = node("span", item.name || item.product_id);
    const provenance = item.substitution_source === "catalog_ingredient_match" ? " · Catalog suggestion" : "";
    product.append(node("small", item.product_id + " · " + item.sales_unit + (item.country ? " · " + item.country : "") + provenance, "cell-note"));
    const availability = item.orderable
      ? item.unlimited ? "Supplier stock unverified" : number.format(item.available_qty) + " " + item.sales_unit
      : item.reason.replaceAll("_", " ");
    return [product, item.unit_price == null ? "—" : money.format(item.unit_price),
      availability, item.available_date ? date(item.available_date) : "—",
      item.co2_per_kg == null ? "—" : number.format(item.co2_per_kg),
      item.reliability == null ? "—" : number.format(item.reliability * 100) + "%"];
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
  target.append(node("h3", "Live offers", "results"), table(headings, offerRows(result.offers)));
  if (result.next_delivery_options?.length) {
    target.append(node("h3", "Available on a later date", "results"),
      table(headings, offerRows(result.next_delivery_options.map(option => option.offer))));
  }
  for (const [productId, alternatives] of Object.entries(result.alternatives ?? {})) {
    if (alternatives.length) {
      target.append(node("h3", "Alternatives for " + productId, "results"),
        table(headings, offerRows(alternatives)));
    }
  }
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
    target.replaceChildren(node("span", stageName(detail.stage, document.documentElement.lang), "tag"), node("p", order.order_id + " · Delivery " + date(order.delivery_date),
      "cell-note"), lineItems(order.lines), node("p", money.format(order.total_net) + " excl. VAT", "ticket-total"),
      node("h3", "Policy decision", "results"), node("p", order.policy.reasons.join(" ")));
    target.append(orderThread(detail, {url, key, language:document.documentElement.lang}));
    if (order.status === "confirmed") target.append(repeatForm(order, current, key, dialog));
    const audit = await request("/audit?order_id=" + encodeURIComponent(id), key);
    if (current !== scope || !dialog.open) return;
    const events = node("ol", "", "timeline");
    for (const event of audit.events) events.append(node("li", event.summary));
    target.append(node("h3", "Audit trail", "results"), events,
      node("p", audit.chain.ok ? "Audit chain verified" : "Audit chain verification failed", "cell-note"));
  } catch (error) {
    if (current === scope && dialog.open) target.append(node("p", error.message, "feedback error"));
  }
}

function showRecipe(recipe) {
  const target = $("results");
  target.replaceChildren(node("h3", "Recipe ingredients", "results"));
  const data = recipe.ingredients.map(row => [
    row.ingredient, number.format(row.quantity) + " " + row.unit, row.dishes.join(", "),
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
  if (requestData.action === "draft") showDraft(null);
  feedback($("chat-status"), "Checking the catalog and offers…");
  $("results").replaceChildren();
  try {
    const result = await request("/client/chat", buyerKey(), requestData);
    if (current !== queryVersion) return;
    feedback($("chat-status"), result.message);
    $("assistant-mode").textContent = result.mode === "gemini-4-hydrogen" ? "Gemini 4 Hydrogen" :
      result.mode === "guided_fallback" ? "Gemini unavailable. Using guided search." : "Guided search";
    if (result.recipe) showRecipe(result.recipe);
    else showResults(result, requestData);
    if (result.draft) showDraft(result.draft);
  } catch (error) {
    if (current === queryVersion) feedback($("chat-status"), error.message, true);
  } finally {
    if (current === queryVersion) buttons.forEach(button => { button.disabled = false; });
  }
}

$("chat").addEventListener("submit", event => {
  event.preventDefault();
  const text = $("message").value.trim();
  if (!text) return;
  sendChat({text, action: event.submitter?.value || "lookup",
    postal_code: $("postcode").value || null, delivery_date:$("chat-delivery-date").value || null,
    model:$("assistant-model").value, include_substitutes: $("substitutes").checked});
});

document.querySelectorAll("[data-example]").forEach(button => button.addEventListener("click", () => {
  $("message").value = button.dataset.example;
  $("message").focus();
}));
$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("mcp-command").textContent);
    feedback($("copy-status"), "Configuration copied.");
  } catch {
    feedback($("copy-status"), "Clipboard is unavailable. Select and copy the configuration above.", true);
  }
});
$("seasonal-form").addEventListener("submit", async event => {
  event.preventDefault();
  const version = ++seasonalVersion;
  const target = $("seasonal-results");
  const button = event.currentTarget.querySelector("button");
  target.replaceChildren(node("p", "Checking seasonal stock…", "feedback"));
  button.disabled = true;
  try {
    const result = await request("/client/seasonal?delivery_date=" + encodeURIComponent($("seasonal-date").value), buyerKey());
    if (version !== seasonalVersion) return;
    target.replaceChildren(node("p", result.calendar + " · " + date(result.delivery_date), "cell-note"));
    if (!result.suggestions.length) target.append(node("p", "No available products match the seasonal calendar for this date.", "empty"));
    for (const group of result.suggestions) {
      target.append(node("h3", group.ingredient, "results"), table(
        ["Product", "Net price / unit", "Availability", "Earliest date", "kg CO₂e/kg", "Reliability"], offerRows(group.offers)));
    }
  } catch (error) {
    if (version === seasonalVersion) target.replaceChildren(node("p", error.message, "feedback error"));
  } finally {
    if (version === seasonalVersion) button.disabled = false;
  }
});

buyer.addEventListener("change", () => {
  seasonalVersion += 1;
  $("seasonal-results").replaceChildren();
  $("seasonal-form").querySelector("button").disabled = false;
  scope += 1;
  queryVersion += 1;
  $("chat").querySelectorAll("[type=submit]").forEach(button => { button.disabled = false; });
  connection();
  showDraft(null);
  $("results").replaceChildren();
  feedback($("chat-status"), "");
});
connection();


document.querySelector("[data-recipe]").addEventListener("click", () => {
  $("message").value = "Tomato salad (4)\n500 g tomato\n80 g red onion\n12 g basil";
  $("message").focus();
});
request("/client/models", buyerKey()).then(data => {
  const model = data.models[0];
  if (!model.available) $("assistant-mode").textContent =
    "Gemini key pending. Guided search accepts product requests and metric recipe lists.";
}).catch(() => {});
