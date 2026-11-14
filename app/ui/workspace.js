import {$, date, feedback, money, node, number, request, table} from "./common.js";
import {buyerKey, inspectTicket, showDraft} from "./client.js";
import {stageName, stages} from "./order_thread.js";

const views = {
  dashboard: ["Dashboard", "Etusivu", "Follow your drafts and deliveries in one place."],
  products: ["Product Search", "Tuotehaku", "Find products, compare live offers, or paste a recipe."],
  drafts: ["Draft Tickets", "Luonnokset", "Review signed drafts before sending them to Aimo."],
  requests: ["Submitted Requests", "Lähetetyt pyynnöt", "Track fulfillment and talk to Aimo on each request."],
  analytics: ["Analytics", "Analytiikka", "Understand spend, stock availability, and fulfillment times."],
  settings: ["Settings", "Asetukset", "Manage your workspace, billing preferences, and agent permissions."]
};
const root = $("workspace-view");
const buyer = $("buyer");
const translations = {
  "Follow your drafts and deliveries in one place.":"Seuraa luonnoksia ja toimituksia yhdessä paikassa.",
  "Find products, compare live offers, or paste a recipe.":"Hae tuotteita, vertaile tarjouksia tai liitä resepti.",
  "Review signed drafts before sending them to Aimo.":"Tarkista allekirjoitetut luonnokset ennen lähettämistä Aimolle.",
  "Track fulfillment and talk to Aimo on each request.":"Seuraa toimitusta ja keskustele Aimon kanssa.",
  "Understand spend, stock availability, and fulfillment times.":"Tarkastele kuluja, saatavuutta ja toimitusaikoja.",
  "Manage your workspace, billing preferences, and agent permissions.":"Hallitse työtilaa, laskutusta ja agentin oikeuksia.",
  "Saved drafts":"Tallennetut luonnokset", "AI Helper":"Tekoälyavustaja", "Ticket review":"Tilauksen tarkistus",
  "Request history":"Pyyntöhistoria", "Kitchen purchasing":"Keittiön hankinnat", "Workspace preferences":"Työtilan asetukset",
  "Monthly net spend":"Kuukausittaiset nettokulut", "Observed stock availability":"Havaittu saatavuus",
  "Average hours between stages":"Keskimääräiset tunnit vaiheiden välillä", "Most ordered products":"Tilatuimmat tuotteet",
  "Appearance":"Ulkoasu", "Default language":"Oletuskieli", "Client business":"Yritys", "Delivery address":"Toimitusosoite",
  "Billing email":"Laskutussähköposti", "Payment method":"Maksutapa", "Invoice reference":"Laskuviite",
  "Allow agents to place orders":"Salli agenttien tehdä tilauksia", "Reminder time (Helsinki)":"Muistutusaika (Helsinki)",
  "Daily reminder for tomorrow’s order":"Päivittäinen muistutus huomisen tilauksesta", "Save settings":"Tallenna asetukset",
};
const t = text => language() === "fi" ? translations[text] || text : text;
let settings = {};
let version = 0;
let year = Number(new Intl.DateTimeFormat("en", {year:"numeric", timeZone:"Europe/Helsinki"}).format(new Date()));
let preferenceWrites = Promise.resolve();

function viewName() {
  const name = location.hash.slice(1);
  return Object.hasOwn(views, name) ? name : "dashboard";
}

function language() { return settings.language || "en"; }

function applyPreferences() {
  document.documentElement.dataset.theme = settings.theme || "light";
  document.documentElement.lang = language();
  for (const label of document.querySelectorAll("[data-en][data-fi]")) label.textContent = label.dataset[language()];
  for (const code of ["en", "fi"]) $("lang-" + code).setAttribute("aria-pressed", String(code === language()));
}

function panel(title) {
  const section = node("section", "", "panel");
  section.append(node("h2", t(title)));
  return section;
}

function metric(label, value) {
  const box = node("div");
  box.append(node("dt", label), node("dd", value));
  return box;
}

function dashboard(data) {
  const section = panel(language() === "fi" ? "Tilausten yhteenveto" : "Purchasing overview");
  const totals = node("dl", "", "metrics workspace-metrics");
  totals.append(metric(language() === "fi" ? "Luonnokset" : "Drafts to review", data.drafts),
    metric(language() === "fi" ? "Lähetetyt pyynnöt" : "Submitted requests", data.submitted));
  const pipeline = node("ol", "", "delivery-pipeline");
  for (const stage of stages) {
    const step = node("li");
    step.append(node("strong", String(data.stages[stage] ?? 0)), node("span", stageName(stage, language())));
    pipeline.append(step);
  }
  section.append(totals, pipeline);
  const closed = (data.stages.rejected || 0) + (data.stages.expired || 0);
  if (closed) section.append(node("p", closed + " rejected or expired requests", "muted"));
  root.replaceChildren(section);
}

function draftEditor(quote, selected, state) {
  const section = panel("AI Helper");
  section.append(node("p", "Suggest changes to quantities or delivery date, then save a fresh quote.", "muted"));
  const form = node("form", "", "workspace-form");
  const input = node("input");
  input.type = "date";
  input.value = quote.delivery_date;
  input.required = true;
  const label = node("label", "Delivery date");
  label.append(input);
  form.append(label);
  const fields = new Map();
  for (const line of quote.lines) {
    if (fields.has(line.product_id)) {
      fields.get(line.product_id).value = Number(fields.get(line.product_id).value) + line.quantity;
      continue;
    }
    const amount = node("input");
    amount.type = "number";
    amount.min = "0";
    amount.max = "1000000";
    amount.step = "any";
    amount.required = true;
    amount.value = line.quantity;
    const item = node("label", (line.name || line.product_id) + " (" + line.sales_unit + ")");
    item.append(amount);
    fields.set(line.product_id, amount);
    form.append(item);
  }
  const prompt = node("input");
  prompt.maxLength = 500;
  prompt.placeholder = "Set " + quote.lines[0].product_id + " to 12";
  const promptLabel = node("label", "Ask AI Helper");
  promptLabel.append(prompt);
  const propose = node("button", "Suggest edit");
  propose.type = "button";
  const save = node("button", "Save revised draft", "primary");
  const open = node("button", "Review and submit");
  open.type = "button";
  const notice = node("p", "", "feedback");
  notice.setAttribute("role", "status");
  notice.hidden = true;
  form.append(promptLabel, propose, save, open, notice);
  const key = buyerKey();
  const base = "/client/drafts/" + encodeURIComponent(quote.quote_id);
  propose.addEventListener("click", async () => {
    if (!prompt.value.trim()) return;
    propose.disabled = true;
    try {
      const suggestion = await request(base + "/help", key, {text:prompt.value});
      input.value = suggestion.delivery_date;
      for (const [sku, field] of fields) field.value = suggestion.quantities[sku] ?? 0;
      feedback(notice, "Suggestion applied to the fields. Save to refresh price and stock.");
    } catch (error) { feedback(notice, error.message, true); }
    finally { propose.disabled = false; }
  });
  open.addEventListener("click", () => showDraft(quote, undefined, selected));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    save.disabled = true;
    try {
      const quantities = Object.fromEntries([...fields].map(([sku, field]) => [sku, Number(field.value)]).filter(([, value]) => value > 0));
      const fresh = await request(base + "/edit", key, {delivery_date:input.value, quantities});
      if (state === version) showDrafts(fresh.quote_id);
    } catch (error) { feedback(notice, error.message, true); }
    finally { save.disabled = false; }
  });
  section.append(form);
  return section;
}

async function showDrafts(select) {
  const state = version;
  const data = await request("/client/drafts", buyerKey());
  if (state !== version) return;
  const grid = node("div", "", "workspace");
  const list = panel("Saved drafts");
  const review = node("div", "", "draft-inline");
  const detail = panel("Ticket review");
  detail.append(review);
  if (!data.length) list.append(node("p", "Create a draft from Product Search to see it here.", "empty"));
  const rows = data.map(quote => {
    const button = node("button", quote.quote_id);
    button.addEventListener("click", () => showDrafts(quote.quote_id));
    const expired = new Date(quote.expires_at) <= new Date();
    return [button, date(quote.delivery_date), money.format(quote.total_net), expired ? "Needs fresh quote" : "Ready to review"];
  });
  if (rows.length) list.append(table(["Draft", "Delivery", "Net total", "Status"], rows));
  const sidebar = node("aside", "", "side");
  grid.append(list, sidebar);
  const quote = data.find(item => item.quote_id === select) || data[0];
  if (quote) {
    sidebar.append(draftEditor(quote, review, state), detail);
  }
  root.replaceChildren(grid);
}

async function showRequests(offset = 0) {
  const state = version;
  const data = await request("/client/requests?offset=" + offset, buyerKey());
  if (state !== version) return;
  const section = panel("Request history");
  if (!data.requests.length) section.append(node("p", "Submitted tickets will appear here.", "empty"));
  const rows = data.requests.map(({order, stage}) => {
    const button = node("button", order.order_id);
    button.addEventListener("click", () => inspectTicket(order.order_id));
    return [button, node("span", stageName(stage, language()), "tag"), date(order.delivery_date), money.format(order.total_net)];
  });
  if (rows.length) section.append(table(["Request", "Stage", "Delivery", "Net total"], rows));
  const actions = node("div", "", "actions");
  for (const [label, page] of [["Previous", offset ? offset - 30 : null], ["Next", data.next_offset]]) {
    if (page == null) continue;
    const button = node("button", label);
    button.addEventListener("click", () => showRequests(page));
    actions.append(button);
  }
  section.append(actions);
  root.replaceChildren(section);
}

function chart(title, values, format, ceiling) {
  const section = panel(title);
  const max = ceiling ?? Math.max(1, ...values.map(([, value]) => value ?? 0));
  const list = node("ul", "", "workspace-chart");
  for (const [label, value] of values) {
    const row = node("li");
    const measure = node("progress");
    measure.max = max;
    measure.value = value ?? 0;
    measure.setAttribute("aria-label", label + ": " + (value == null ? "No observations" : format(value)));
    row.append(node("span", label), measure, node("strong", value == null ? "—" : format(value)));
    list.append(row);
  }
  section.append(list);
  return section;
}

async function analytics() {
  const state = version;
  const data = await request("/client/analytics?year=" + year, buyerKey());
  if (state !== version) return;
  const toolbar = panel("Kitchen purchasing");
  const input = node("input");
  Object.assign(input, {type:"number", min:"2000", max:"9998", value:year, required:true});
  const form = node("form", "", "actions");
  const label = node("label", "Delivery year");
  label.append(input);
  form.append(label, node("button", "Update"));
  form.addEventListener("submit", event => { event.preventDefault(); year = Number(input.value); render(); });
  const total = node("dl", "", "metrics");
  total.append(metric("Registered orders", data.months.reduce((sum, month) => sum + month.orders, 0)),
    metric("Net spend", money.format(data.months.reduce((sum, month) => sum + month.net, 0))));
  toolbar.append(form, total);
  const months = new Intl.DateTimeFormat(language(), {month:"short", timeZone:"UTC"});
  const byMonth = fn => data.months.map(m => [months.format(new Date(Date.UTC(year, m.month-1, 1))), fn(m)]);
  const charts = node("div", "", "workspace-metrics-grid");
  charts.append(chart("Monthly net spend", byMonth(m => m.net), money.format),
    chart("Observed stock availability", byMonth(m => m.checked ? 100*m.available/m.checked : null), v => number.format(v)+"%", 100),
    chart("Average hours between stages", [
      ["Submission to arrival", data.stage_hours.end_to_end?.average ?? null],
      ...stages.slice(1).map(s => [stageName(s, language()), data.stage_hours[s]?.average ?? null])
    ], v => number.format(v)+" h"));
  const availability = Object.entries(data.availability_by_sku);
  if (availability.length) {
    const section = panel("Monthly availability by product");
    const select = node("select");
    const label = node("label", "Most checked product codes");
    label.append(select);
    for (const [sku] of availability) select.append(new Option(sku, sku));
    const graph = node("div");
    const draw = () => graph.replaceChildren(chart(select.value, data.availability_by_sku[select.value].map(month =>
      [months.format(new Date(Date.UTC(year, month.month-1, 1))), month.checked ? 100*month.available/month.checked : null]),
      v => number.format(v)+"%", 100));
    select.addEventListener("change", draw);
    draw();
    section.append(label, graph);
    charts.append(section);
  }
  const items = panel("Most ordered products");
  items.append(data.products.length ? table(["Product","Quantity","Sales unit"], data.products.map(item =>
    [item.name || item.id, number.format(item.quantity), item.unit])) : node("p", "No confirmed orders for this year.", "empty"));
  root.replaceChildren(toolbar, charts, items);
}

function settingsView() {
  const section = panel("Workspace preferences");
  const form = node("form", "", "workspace-form settings-grid");
  const fields = [
    ["theme","Appearance",{light:"Light",dark:"Dark"}], ["language","Default language",{en:"English",fi:"Suomi"}],
    ["business","Client business"], ["address","Delivery address"], ["billing_email","Billing email",null,"email"],
    ["payment_method","Payment method",{invoice:"Invoice",bank_transfer:"Bank transfer",purchase_order:"Purchase order"}],
    ["invoice_reference","Invoice reference"], ["agent_self_order","Allow agents to place orders",null,"checkbox"],
    ["recurring_prompt","Daily reminder for tomorrow’s order"], ["recurring_time","Reminder time (Helsinki)",null,"time"]
  ];
  for (const [id, title, options, type] of fields) {
    const label = node("label", t(title));
    const control = node(options ? "select" : "input");
    control.name = id;
    if (options) for (const [key, name] of Object.entries(options)) control.append(new Option(name, key));
    else control.type = type || "text";
    if (type === "checkbox") control.checked = Boolean(settings[id]);
    else control.value = settings[id] ?? "";
    label.append(control);
    form.append(label);
  }
  const note = node("p", "", "feedback");
  note.hidden = true;
  note.setAttribute("role", "status");
  form.append(node("button", t("Save settings"), "primary"), note);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const value = Object.fromEntries(new FormData(form));
    value.agent_self_order = form.elements.agent_self_order.checked;
    try { await save(value); feedback(note, "Settings saved."); }
    catch (error) { feedback(note, error.message, true); }
  });
  section.append(form);
  root.replaceChildren(section);
}

async function save(value) {
  const key = buyerKey();
  const pending = preferenceWrites.catch(() => {}).then(() => request("/client/settings", key, value));
  preferenceWrites = pending;
  const saved = await pending;
  if (key !== buyerKey()) return;
  settings = saved;
  applyPreferences();
  updateHeading();
  refreshReminder();
}

function updateHeading() {
  const active = viewName();
  const [en, fi, description] = views[active];
  $("view-title").textContent = language() === "fi" ? fi : en;
  $("view-description").textContent = t(description);
  for (const link of document.querySelectorAll("[data-view]")) {
    if (link.dataset.view === active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

async function render() {
  const state = ++version;
  const view = viewName();
  updateHeading();
  $("product-view").hidden = view !== "products";
  root.hidden = view === "products";
  if (root.hidden) return;
  root.replaceChildren(node("p", "Loading workspace…", "empty"));
  try {
    if (view === "drafts") await showDrafts();
    else if (view === "requests") await showRequests();
    else if (view === "analytics") await analytics();
    else if (view === "settings") settingsView();
    else {
      const data = await request("/client/dashboard", buyerKey());
      if (state === version) dashboard(data);
    }
  } catch (error) {
    if (state === version) root.replaceChildren(node("p", error.message, "feedback error"));
  }
}

async function refreshReminder() {
  if (!settings.recurring_prompt) {
    feedback($("reminder"), "");
    return;
  }
  const key = buyerKey();
  try {
    const data = await request("/client/reminders", key);
    if (key === buyerKey()) feedback($("reminder"), data.reminder ?
      "Tomorrow’s order (" + date(data.reminder.delivery_date) + ") · " + data.reminder.text : "");
  } catch {
    if (key === buyerKey()) feedback($("reminder"), "");
  }
}

async function connect() {
  const key = buyerKey();
  try {
    const value = await request("/client/settings", key);
    if (key !== buyerKey()) return;
    settings = value;
    applyPreferences();
    render();
    refreshReminder();
  } catch (error) { root.replaceChildren(node("p", error.message, "feedback error")); }
}

window.addEventListener("hashchange", render);
window.addEventListener("ticket-submitted", render);
window.setInterval(refreshReminder, 60000);
buyer.addEventListener("change", connect);
for (const code of ["en", "fi"]) $("lang-" + code).addEventListener("click", async () => {
  try { await save({...settings, language:code}); render(); }
  catch (error) { feedback($("reminder"), error.message, true); }
});
$("help-open").addEventListener("click", () => $("client-help").showModal());
$("client-sign-out").addEventListener("click", () => {
  sessionStorage.setItem("agent-dairy-signed-out", "true");
  window.location.reload();
});
if (sessionStorage.getItem("agent-dairy-signed-out")) {
  $("main").replaceChildren();
  const signedOut = panel("Signed out");
  const button = node("button", "Open demo workspace", "primary");
  button.addEventListener("click", () => {
    sessionStorage.removeItem("agent-dairy-signed-out");
    window.location.reload();
  });
  signedOut.append(button);
  document.querySelector(".rail").hidden = true;
  $("main").append(signedOut);
} else {
  connect();
}
