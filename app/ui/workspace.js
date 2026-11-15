import {$, configurePostcodeInput, date, deliveryAddressParts, feedback, gatewayNow, inputDate,
  money, node, number, parseInputDate, portalUrl, request, table} from "./common.js";
import {buyerKey, editBasket, inspectTicket, showDraft, ticketNameForm} from "./client.js";
import {stageName, stages} from "./order_thread.js";

const views = {
  dashboard: ["Dashboard", "Etusivu", "Follow your drafts and deliveries in one place."],
  products: ["Product Search", "Tuotehaku", "Find products, compare live offers, or paste a recipe."],
  drafts: ["Draft Tickets", "Luonnokset", "Review signed drafts before sending them to Aimo."],
  requests: ["Submitted Requests", "Lähetetyt pyynnöt", "Track fulfillment and talk to Aimo on each request."],
  analytics: ["Analytics", "Analytiikka", "Understand spend, stock availability, and fulfillment times."],
  settings: ["Settings and Tools", "Asetukset ja työkalut", "Manage your workspace, billing preferences, and agent permissions."]
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
  "AI Helper":"Tekoälyavustaja", "Ticket review":"Tilauksen tarkistus",
  "Delivery schedule":"Toimitusaikataulu", "No requests in this stage.":"Ei pyyntöjä tässä vaiheessa.",
  "Create a draft from Product Search to see it here.":"Luo luonnos tuotehaussa nähdäksesi sen täällä.",
  "Choose a draft to edit its quantities and delivery date.":"Valitse luonnos muokataksesi määriä ja toimituspäivää.",
  "Order not found in this workspace.":"Tilausta ei löytynyt tästä työtilasta.",
  "Needs fresh quote":"Tarvitsee uuden tarjouksen",
  "Request history":"Pyyntöhistoria", "Kitchen purchasing":"Keittiön hankinnat", "Workspace preferences":"Työtilan asetukset",
  "Monthly net spend":"Kuukausittaiset nettokulut", "Observed stock availability":"Havaittu saatavuus",
  "Average hours between stages":"Keskimääräiset tunnit vaiheiden välillä", "Most ordered products":"Tilatuimmat tuotteet",
  "Appearance":"Ulkoasu", "Default language":"Oletuskieli", "Client business":"Yritys", "Delivery address":"Toimitusosoite",
  "Postcode":"Postinumero",
  "Billing email":"Laskutussähköposti", "Payment method":"Maksutapa", "Invoice reference":"Laskuviite",
  "Allow agents to place orders":"Salli agenttien tehdä tilauksia", "Reminder time (Helsinki)":"Muistutusaika (Helsinki)",
  "Daily reminder for tomorrow’s order":"Päivittäinen muistutus huomisen tilauksesta", "Save settings":"Tallenna asetukset",
  "Delivery year":"Toimitusvuosi", "Registered orders":"Rekisteröidyt tilaukset", "Registered offers":"Rekisteröidyt tarjoukset",
  "Net spend":"Verottomat kulut", "Monthly availability by product":"Kuukausittainen saatavuus tuotteittain",
  "Most checked product codes":"Eniten tarkistetut tuotteet", "Update":"Päivitä", "No observations":"Ei havaintoja",
  "Submission to arrival":"Lähetyksestä saapumiseen", "Sales unit":"Myyntiyksikkö",
  "No confirmed orders for this year.":"Ei vahvistettuja tilauksia tälle vuodelle.",
  "Display and language":"Näyttö ja kieli", "Business and delivery":"Yritys ja toimitus",
  "Billing":"Laskutus", "Agent permissions and reminders":"Agentin oikeudet ja muistutukset",
  "Agent integration":"Agentin tiedot", "Light":"Vaalea", "Dark":"Tumma", "Invoice":"Lasku",
  "Bank transfer":"Tilisiirto", "Purchase order":"Ostotilaus", "Settings saved.":"Asetukset tallennettu.",
  "Agent access is managed by the Aimo deployment. Ask Aimo operations for a workspace key.":
    "Agentin käyttöoikeuksia hallinnoi Aimo. Pyydä työtilan avain Aimon asiakaspalvelusta.",
  "Connect an external purchasing agent with this workspace’s demo key. Keep the key private.":
    "Yhdistä ulkoinen ostoagentti työtilan demoavaimella. Pidä avain salassa.",
  "Copy command":"Kopioi komento", "API reference":"API-ohjeet", "Command copied.":"Komento kopioitu.",
  "Clipboard unavailable. Select and copy the command.":"Leikepöytä ei ole käytettävissä. Valitse ja kopioi komento.",
  "over ":"yli ", "all substitutions":"kaikki korvaavat tuotteet",
  "substitutions outside category":"korvaavat tuotteet muista tuoteryhmistä",
  "partial stock":"osittainen saatavuus", "unverified stock":"vahvistamaton saatavuus", "trace allergens":"allergeenijäämät",
  "None":"Ei mitään", "Any amount":"Ei rajaa", " net":" veroton", "Automatic orders":"Automaattiset tilaukset",
  "Weekly limit":"Viikkoraja", "Used this week":"Käytetty tällä viikolla", "Needs approval":"Vaatii hyväksynnän",
  "Blocked allergens":"Poissuljetut allergeenit", "Mandate ":"Hankintasäännöt ", " · issued by ":" · laatija ",
};
const t = text => language() === "fi" ? translations[text] || text : text;
let draftSelection;
let draftQuotes = [];

window.addEventListener("ticket-renamed", event => {
  if (viewName() === "drafts") {
    const quote = draftQuotes.find(item => event.detail.url === "/client/drafts/" + encodeURIComponent(item.quote_id));
    if (!quote) return;
    quote.name = event.detail.name;
    const item = Array.from($("draft-list").querySelectorAll("button")).find(button => button.dataset.quote === quote.quote_id);
    if (item) item.querySelector("strong").textContent = quote.name;
  }
  if (viewName() === "requests") showRequests();
});
let settings = {};
let version = 0;
let year = Number(new Intl.DateTimeFormat("en", {year:"numeric", timeZone:"Europe/Helsinki"}).format(gatewayNow()));
let yearSelected = false;
let preferenceWrites = Promise.resolve();

function viewName() {
  const name = location.hash.slice(1).split("?")[0];
  return Object.hasOwn(views, name) ? name : "products";
}

function language() { return settings.language || "en"; }

function applyPreferences() {
  window.portalTheme.apply(settings.theme);
  document.documentElement.lang = language();
  for (const label of document.querySelectorAll("[data-en][data-fi]")) label.textContent = label.dataset[language()];
  const prompt = $("message");
  prompt.placeholder = language() === "fi" ? "Tarvitsen 200 litraa laktoositonta maitoa maanantaiksi" :
    "I need 200 litres of lactose-free milk by Monday";
  prompt.setAttribute("aria-label", language() === "fi" ? "Mitä keittiösi tarvitsee?" : "What does your kitchen need?");
  document.title = language() === "fi" ? "Agent Dairy | Hankintatyötila" : "Agent Dairy | Purchasing workspace";
  if ($("draft").classList.contains("empty")) showDraft(null);
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
  const heading = node("h3", t("Delivery schedule"), "delivery-heading");
  const pipeline = node("div", "", "delivery-board");
  for (const stage of stages.slice(0, 4)) {
    const orders = data.active_orders[stage];
    const column = node("section", "", "delivery-column");
    column.dataset.stage = stage;
    const header = node("h4", stageName(stage, language()));
    header.append(node("span", String(orders.length)));
    const list = node("ul");
    for (const order of orders) {
      const link = node("a", "", "delivery-ticket");
      link.href = "#requests?" + new URLSearchParams({order:order.order_id});
      link.append(node("strong", order.name || order.order_id), node("time", date(order.delivery_date)));
      link.querySelector("time").dateTime = order.delivery_date;
      const item = node("li");
      item.append(link);
      list.append(item);
    }
    column.append(header, orders.length ? list : node("p", t("No requests in this stage."), "delivery-empty"));
    pipeline.append(column);
  }
  section.append(totals, heading, pipeline);
  const laterStages = stages.slice(4).filter(stage => data.stages[stage]);
  if (laterStages.length) {
    const summary = node("p", "", "delivery-summary");
    for (const stage of laterStages) {
      summary.append(node("span", stageName(stage, language()) + " " + data.stages[stage], "tag stage-tag " + stage));
    }
    section.append(summary);
  }
  const closed = (data.stages.rejected || 0) + (data.stages.expired || 0);
  if (closed) section.append(node("p", closed + (language() === "fi" ?
    (closed === 1 ? " hylätty tai vanhentunut pyyntö" : " hylättyä tai vanhentunutta pyyntöä") :
    (closed === 1 ? " rejected or expired request" : " rejected or expired requests")), "muted"));
  if (!data.drafts && !data.submitted) {
    const empty = node("div", "", "empty dashboard-empty");
    empty.append(node("p", language() === "fi"
      ? "Ei vielä luonnoksia tai lähetettyjä pyyntöjä. Aloita etsimällä tuotteita tai liittämällä resepti."
      : "No drafts or submitted requests yet. Start by finding products or pasting a recipe."));
    const start = node("button", language() === "fi" ? "Aloita tuotehaku" : "Start a product search", "primary");
    start.type = "button";
    start.addEventListener("click", () => { location.hash = "products"; });
    const actions = node("div", "", "actions");
    actions.append(start);
    empty.append(actions);
    section.append(empty);
  }
  root.replaceChildren(section);
}

function draftEditor(quote, state) {
  const section = panel("AI Helper");
  section.append(node("p", "Suggest changes to quantities or delivery date, then save a fresh quote.", "muted"));
  const form = node("form", "", "workspace-form");
  const input = node("input");
  input.type = "text";
  input.inputMode = "numeric";
  input.placeholder = "dd.mm.yyyy";
  input.value = inputDate(quote.delivery_date);
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
  const notice = node("p", "", "feedback");
  notice.setAttribute("role", "status");
  notice.hidden = true;
  const actions = node("div", "", "draft-helper-actions");
  actions.append(propose, save);
  form.append(promptLabel, actions, notice);
  const key = buyerKey();
  const base = "/client/drafts/" + encodeURIComponent(quote.quote_id);
  propose.addEventListener("click", async () => {
    if (!prompt.value.trim()) return;
    propose.disabled = true;
    try {
      const suggestion = await request(base + "/help", key, {text:prompt.value});
      input.value = inputDate(suggestion.delivery_date);
      for (const [sku, field] of fields) field.value = suggestion.quantities[sku] ?? 0;
      feedback(notice, "Suggestion applied to the fields. Save to refresh price and stock.");
    } catch (error) { feedback(notice, error.message, true); }
    finally { propose.disabled = false; }
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    save.disabled = true;
    try {
      const delivery = parseInputDate(input.value);
      if (!delivery) throw new Error("Enter the delivery date as dd.mm.yyyy.");
      const entries = [];
      for (const [sku, field] of fields) {
        const rawVal = field.value.trim();
        const num = rawVal === "" ? NaN : Number(rawVal);
        if (!Number.isFinite(num) || num < 0 || num > 1_000_000) {
          throw new Error("Enter a valid quantity between 0 and 1,000,000 for each product.");
        }
        if (num > 0) entries.push([sku, num]);
      }
      if (!entries.length) {
        throw new Error("Keep at least one product with a quantity above 0, or delete the draft.");
      }
      const quantities = Object.fromEntries(entries);
      const fresh = await request(base + "/edit", key, {delivery_date:delivery, quantities});
      if (state === version) {
        draftQuotes = [fresh, ...draftQuotes.filter(item => item.quote_id !== quote.quote_id)];
        if (quote.quote_id === draftSelection) displayDrafts(fresh.quote_id);
        else paintDraftList();
      }
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
  draftQuotes = data;
  displayDrafts(select);
}

function paintDraftList(focus = false) {
  const list = $("draft-list");
  list.replaceChildren();
  if (!draftQuotes.length) list.append(node("p", t("Create a draft from Product Search to see it here."), "draft-list-empty"));
  for (const item of draftQuotes) {
    const button = node("button", "", "draft-choice");
    button.type = "button";
    button.dataset.quote = item.quote_id;
    if (item.quote_id === draftSelection) button.setAttribute("aria-current", "true");
    button.append(node("strong", item.name || item.quote_id), node("small", date(item.delivery_date) + " · " + money.format(item.total_net)));
    if (new Date(item.expires_at) <= gatewayNow()) button.append(node("small", t("Needs fresh quote"), "draft-expired"));
    button.addEventListener("click", () => {
      if (draftSelection !== item.quote_id) displayDrafts(item.quote_id, true);
    });
    list.append(button);
  }
  if (focus) list.querySelector('[aria-current="true"]')?.focus();
}

function displayDrafts(select, focus = false) {
  const state = version;
  const quote = draftQuotes.find(item => item.quote_id === select) ?? draftQuotes[0];
  draftSelection = quote?.quote_id;
  paintDraftList(focus);

  const grid = node("div", "", "draft-workspace");
  const review = node("div", "", "draft-inline");
  const detail = panel("Ticket review");
  grid.append(detail);
  if (quote) {
    const base = "/client/drafts/" + encodeURIComponent(quote.quote_id);
    const name = ticketNameForm(quote.name, base, buyerKey());
    name.classList.add("draft-name-form");
    const edit = node("button", language() === "fi" ? "Muokkaa tuotehaussa" : "Edit in Product Search", "secondary");
    edit.addEventListener("click", () => editBasket(quote));
    const remove = node("button", language() === "fi" ? "Poista luonnos" : "Delete draft", "delete-draft");
    const notice = node("p", "", "feedback");
    notice.hidden = true;
    remove.addEventListener("click", async () => {
      if (!window.confirm(language() === "fi" ? "Poistetaanko tämä luonnos?" : "Delete this draft?")) return;
      remove.disabled = true;
      try {
        await request(base + "/delete", buyerKey(), {});
        if (state === version) {
          draftQuotes = draftQuotes.filter(item => item.quote_id !== quote.quote_id);
          if (quote.quote_id === draftSelection) displayDrafts(undefined, true);
          else paintDraftList();
        }
      } catch (error) { feedback(notice, error.message, true); }
      finally { remove.disabled = false; }
    });
    const actions = node("div", "", "draft-review-actions");
    actions.append(edit, remove);
    detail.append(name, review, actions, notice);
    showDraft(quote, undefined, review);
    review.querySelector("h3").remove();
    grid.append(draftEditor(quote, state));
  } else {
    showDraft(null, undefined, review);
    detail.append(review);
    const helper = panel("AI Helper");
    helper.append(node("p", t("Choose a draft to edit its quantities and delivery date."), "empty"));
    grid.append(helper);
  }
  root.replaceChildren(grid);
}

async function showRequests(offset = 0, focus = null) {
  const state = version;
  const params = new URLSearchParams({offset});
  if (focus) params.set("focus", focus);
  const data = await request("/client/requests?" + params, buyerKey());
  if (state !== version) return;
  const section = panel("Request history");
  if (!data.requests.length) section.append(node("p", "Submitted tickets will appear here.", "empty"));
  const rows = data.requests.map(({order, stage}) => {
    const button = node("button", order.name || order.order_id);
    button.addEventListener("click", () => inspectTicket(order.order_id));
    return [button, node("span", stageName(stage, language()), "tag stage-tag " + stage),
      date(order.delivery_date), money.format(order.total_net)];
  });
  const selected = data.requests.findIndex(({order}) => order.order_id === focus);
  if (focus && selected === -1) section.append(node("p", t("Order not found in this workspace."), "feedback"));
  let highlighted;
  if (rows.length) {
    const grid = table(["Request", "Stage", "Delivery", "Net total"], rows);
    if (selected >= 0) highlighted = grid.querySelector("tbody").rows[selected];
    section.append(grid);
  }
  const actions = node("div", "", "actions");
  for (const [label, page] of [["Previous", data.offset ? data.offset - 30 : null], ["Next", data.next_offset]]) {
    if (page == null) continue;
    const button = node("button", label);
    button.addEventListener("click", () => showRequests(page));
    actions.append(button);
  }
  section.append(actions);
  root.replaceChildren(section);
  if (highlighted) {
    highlighted.classList.add("request-highlight");
    highlighted.querySelector("button").focus({preventScroll:true});
    highlighted.scrollIntoView({block:"center", inline:"nearest"});
    window.setTimeout(() => highlighted.classList.remove("request-highlight"), 5500);
  }
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
    measure.setAttribute("aria-label", t(label) + ": " + (value == null ? t("No observations") : format(value)));
    row.append(node("span", t(label)), measure, node("strong", value == null ? "—" : format(value)));
    list.append(row);
  }
  section.append(list);
  return section;
}

async function analytics() {
  const state = version;
  if (!yearSelected) {
    year = Number(new Intl.DateTimeFormat("en", {year:"numeric", timeZone:"Europe/Helsinki"}).format(gatewayNow()));
  }
  const data = await request("/client/analytics?year=" + year, buyerKey());
  if (state !== version) return;
  const toolbar = panel("Kitchen purchasing");
  const input = node("input");
  Object.assign(input, {type:"number", min:"2000", max:"9998", value:year, required:true});
  const form = node("form", "", "analytics-year");
  const label = node("label", t("Delivery year"));
  label.append(input);
  form.append(label, node("button", t("Update")));
  form.addEventListener("submit", event => { event.preventDefault(); yearSelected = true; year = Number(input.value); render(); });
  const total = node("dl", "", "metrics");
  total.append(metric(t("Registered orders"), data.months.reduce((sum, month) => sum + month.orders, 0)),
    metric(t("Net spend"), money.format(data.months.reduce((sum, month) => sum + month.net, 0))));
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
    const label = node("label", t("Most checked product codes"));
    label.append(select);
    const labelFor = sku => data.availability_product_names?.[sku] || ((language() === "fi" ? "Tuote " : "Product ") + sku);
    for (const [sku] of availability) select.append(new Option(labelFor(sku) + " · " + sku, sku));
    const graph = node("div");
    const draw = () => graph.replaceChildren(chart(labelFor(select.value), data.availability_by_sku[select.value].map(month =>
      [months.format(new Date(Date.UTC(year, month.month-1, 1))), month.checked ? 100*month.available/month.checked : null]),
      v => number.format(v)+"%", 100));
    select.addEventListener("change", draw);
    draw();
    section.append(label, graph);
    charts.append(section);
  }
  const items = panel("Most ordered products");
  items.append(data.products.length ? table(["Product","Quantity","Sales unit"], data.products.map(item =>
    [item.name || item.id, number.format(item.quantity), item.unit])) : node("p", t("No confirmed orders for this year."), "empty"));
  root.replaceChildren(toolbar, charts, items);
}

function settingsView() {
  const section = panel("Workspace preferences");
  const form = node("form", "", "workspace-form settings-form");
  const savedAddress = deliveryAddressParts(settings.address);
  const values = {...settings, address:savedAddress.address, postal_code:settings.postal_code || savedAddress.postalCode};
  const groups = [
    ["Display and language", [["theme","Appearance",{light:"Light",dark:"Dark"}], ["language","Default language",{en:"English",fi:"Suomi"}]]],
    ["Business and delivery", [["business","Client business"], ["address","Delivery address"], ["postal_code","Postcode"]]],
    ["Billing", [["billing_email","Billing email",null,"email"],
      ["payment_method","Payment method",{invoice:"Invoice",bank_transfer:"Bank transfer",purchase_order:"Purchase order"}],
      ["invoice_reference","Invoice reference"]]],
    ["Agent permissions and reminders", [["agent_self_order","Allow agents to place orders",null,"checkbox"],
      ["recurring_prompt","Daily reminder for tomorrow’s order"], ["recurring_time","Reminder time (Helsinki)",null,"time"]]],
  ];
  for (const [heading, fields] of groups) {
    const group = node("fieldset", "", "settings-group");
    group.append(node("legend", t(heading)));
    const grid = node("div", "", "settings-fields");
    for (const [id, title, options, type] of fields) {
      const label = node("label", t(title), type === "checkbox" ? "settings-permission" : "");
      const control = node(options ? "select" : "input");
      control.name = id;
      if (options) for (const [key, name] of Object.entries(options)) control.append(new Option(t(name), key));
      else control.type = type || "text";
      if (id === "address") {
        control.autocomplete = "street-address";
        control.maxLength = 240;
      }
      if (id === "postal_code") configurePostcodeInput(control);
      if (type === "checkbox") {
        control.checked = Boolean(settings[id]);
        label.prepend(control);
      } else {
        control.value = values[id] ?? "";
        label.append(control);
      }
      grid.append(label);
    }
    group.append(grid);
    form.append(group);
  }
  const note = node("p", "", "feedback");
  note.hidden = true;
  note.setAttribute("role", "status");
  form.append(node("button", t("Save settings"), "primary"), note);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const value = Object.fromEntries(new FormData(form));
    value.agent_self_order = form.elements.agent_self_order.checked;
    if (!value.recurring_time) {
      delete value.recurring_time;
    } else if (/^\d{2}:\d{2}:\d{2}$/.test(value.recurring_time)) {
      value.recurring_time = value.recurring_time.slice(0, 5);
    }
    try {
      await save(value);
      if (viewName() === "settings") settingsView();
      if ($("settings-status")) feedback($("settings-status"), t("Settings saved."));
    }
    catch (error) { feedback(note, error.message, true); }
  });
  note.id = "settings-status";
  section.append(form);
  root.replaceChildren(section, agentIntegration());
}

function agentIntegration() {
  const section = panel("Agent integration");
  section.classList.add("settings-integration");
  const local = (en, fi) => language() === "fi" ? fi : en;
  let url = portalUrl("/mcp");
  const status = node("p", "", "feedback");
  status.hidden = true;
  status.setAttribute("role", "status");
  function copyButton(label, value) {
    const button = node("button", label);
    button.type = "button";
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(value());
        feedback(status, local("Copied.", "Kopioitu."));
      } catch {
        feedback(status, local("Select and copy the value manually.", "Valitse ja kopioi arvo käsin."), true);
      }
    });
    return button;
  }
  const endpoint = node("pre", url);
  section.append(node("h3", local("MCP server URL", "MCP-palvelimen osoite")), endpoint,
    copyButton(local("Copy MCP URL", "Kopioi MCP-osoite"), () => url));
  const chatGPT = node("div", "", "agent-connect");
  chatGPT.hidden = true;
  const connections = node("ul");
  chatGPT.append(node("h3", "ChatGPT"), node("p", local(
    "Add the MCP URL in ChatGPT, choose OAuth, then sign in with your Agent Dairy account to grant read-only access.",
    "Lisää MCP-osoite ChatGPT:hen, valitse OAuth ja myönnä lukuoikeus kirjautumalla Agent Dairy -tilillesi."), "muted"), connections);
  section.append(chatGPT, node("h3", local("Connect with a bearer key", "Yhdistä Bearer-avaimella")),
    node("p", local("Add the URL in your AI’s MCP settings using Streamable HTTP, then create a key for that agent.",
      "Lisää osoite tekoälysi MCP-asetuksiin Streamable HTTP -yhteytenä ja luo agentille avain."), "muted"));
  const form = node("form", "", "workspace-form");
  const label = node("label", local("Agent name", "Agentin nimi"));
  const name = node("input");
  name.required = true;
  name.maxLength = 60;
  label.append(name);
  const permission = node("label", local("Allow this key to submit orders", "Salli tilausten lähettäminen tällä avaimella"), "settings-permission");
  const canOrder = node("input");
  canOrder.type = "checkbox";
  permission.prepend(canOrder);
  const create = node("button", local("Create agent key", "Luo agenttiavain"), "primary");
  form.append(label, permission, create);
  const secret = node("div", "", "agent-connect");
  const header = node("pre");
  let token = "";
  let issuedId = "";
  secret.hidden = true;
  secret.append(node("p", local(
    "In a bearer token field, paste just the key. In custom headers, use the full Authorization header below. The key is shown once.",
    "Liitä Bearer-tunnistekenttään pelkkä avain. Käytä mukautetuissa otsakkeissa alla olevaa Authorization-otsaketta. Avain näytetään kerran.")),
    header, copyButton(local("Copy key", "Kopioi avain"), () => token),
    copyButton(local("Copy Authorization header", "Kopioi Authorization-otsake"), () => header.textContent));
  const list = node("ul");
  const key = buyerKey();
  async function loadConnections() {
    const result = await request("/client/agent-connections", key);
    connections.replaceChildren();
    for (const item of result) {
      const row = node("li", local("Connected", "Yhdistetty") + " " + date(item.created_at) +
        (item.last_used_at ? " · " + local("Last used", "Viimeksi käytetty") + " " + date(item.last_used_at) : ""));
      const disconnect = node("button", local("Disconnect", "Katkaise yhteys"));
      disconnect.type = "button";
      disconnect.addEventListener("click", async () => {
        disconnect.disabled = true;
        try {
          await request("/client/agent-connections/" + encodeURIComponent(item.id) + "/disconnect", key, {});
          await loadConnections();
          feedback(status, local("ChatGPT disconnected.", "ChatGPT-yhteys katkaistu."));
        } catch (error) { feedback(status, error.message, true); }
        finally { disconnect.disabled = false; }
      });
      row.append(" ", disconnect);
      connections.append(row);
    }
  }
  async function loadKeys() {
    try {
      const keys = await request("/client/agent-credentials", key);
      list.replaceChildren();
      for (const item of keys) {
        const row = node("li", item.label + " · " + item.id + " · " +
          (item.can_order ? local("Ordering enabled for key", "Tilaaminen sallittu avaimelle") : local("Read-only", "Vain luku")) +
          (item.last_used_at ? " · " + date(item.last_used_at) : ""));
        const revoke = node("button", local("Revoke", "Mitätöi"));
        revoke.type = "button";
        revoke.addEventListener("click", async () => {
          if (!window.confirm(local("Revoke this agent key?", "Mitätöidäänkö agenttiavain?"))) return;
          revoke.disabled = true;
          try {
            await request("/client/agent-credentials/" + encodeURIComponent(item.id) + "/revoke", key, {});
            if (item.id === issuedId) {
              secret.hidden = true;
              header.textContent = "";
              token = "";
              issuedId = "";
            }
            await loadKeys();
          } catch (error) { feedback(status, error.message, true); }
          finally { revoke.disabled = false; }
        });
        row.append(" ", revoke);
        list.append(row);
      }
    } catch (error) { feedback(status, error.message, true); }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    create.disabled = true;
    try {
      const result = await request("/client/agent-credentials", key, {label:name.value, can_order:canOrder.checked});
      token = result.secret;
      issuedId = result.id;
      header.textContent = "Authorization: Bearer " + token;
      secret.hidden = false;
      form.reset();
      feedback(status, local("Copy this key now. It is shown once.", "Kopioi avain nyt. Se näytetään vain kerran."));
      await loadKeys();
    } catch (error) { feedback(status, error.message, true); }
    finally { create.disabled = false; }
  });
  section.append(form, status, secret, list);
  request("/client/agent-integration", key).then(async integration => {
    if (integration.url) endpoint.textContent = url = integration.url;
    chatGPT.hidden = !integration.chatgpt_oauth;
    if (integration.chatgpt_oauth) await loadConnections();
  }).catch(error => feedback(status, error.message, true));
  loadKeys();
  return section;
}

async function loadTrust() {
  const key = buyerKey();
  const target = $("trust");
  if (!target) return;
  try {
    const me = await request("/me", key);
    if (key === buyerKey()) renderTrust(me);
  } catch (error) {
    if (key === buyerKey()) {
      target.classList.add("empty");
      target.replaceChildren(node("p", "Limits unavailable. " + error.message, "cell-note"));
    }
  }
}

function approvalSummary(m) {
  const needs = [];
  if (m.max_order_total != null) needs.push(t("over ") + money.format(m.max_order_total));
  if (m.substitution_policy === "always_approval") needs.push(t("all substitutions"));
  else if (m.substitution_policy === "same_category") needs.push(t("substitutions outside category"));
  if (m.partial_coverage === "needs_approval") needs.push(t("partial stock"));
  if (m.unknown_availability === "needs_approval") needs.push(t("unverified stock"));
  if (m.may_contain_forbidden === "needs_approval" && m.forbidden_allergens.length) needs.push(t("trace allergens"));
  return needs.length ? needs.join(", ") : t("None");
}

function renderTrust(me) {
  const target = $("trust");
  if (!target) return;
  const m = me.mandate;
  const values = [
    ["Automatic orders", m.max_order_total == null ? t("Any amount") : money.format(m.max_order_total) + t(" net")],
    ["Weekly limit", m.max_weekly_total == null ? t("None") : money.format(m.max_weekly_total) + t(" net")],
    ["Used this week", money.format(me.weekly_spent || 0)],
    ["Needs approval", approvalSummary(m)],
    ["Blocked allergens", m.forbidden_allergens?.length ? m.forbidden_allergens.join(", ") : t("None")],
  ];
  const list = node("dl", "", "limits");
  for (const [label, value] of values) {
    const row = node("div", "", "limit-row");
    row.append(node("dt", t(label)), node("dd", value));
    list.append(row);
  }
  target.classList.remove("empty");
  target.replaceChildren(list, node("p", t("Mandate ") + m.mandate_id + t(" · issued by ") + m.issued_by, "cell-note"));
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
  const crumb = $("crumb-current");
  if (crumb) crumb.textContent = language() === "fi" ? fi : en;
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
  $("draft-sidebar").hidden = view !== "drafts";
  if (view === "drafts") $("draft-list").replaceChildren();
  root.hidden = view === "products";
  if (root.hidden) return;
  root.replaceChildren(node("p", "Loading workspace…", "empty"));
  try {
    if (view === "drafts") await showDrafts(draftSelection);
    else if (view === "requests") await showRequests(0, new URLSearchParams(location.hash.split("?")[1]).get("order"));
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
    loadTrust();
  } catch (error) {
    root.replaceChildren(node("p", error.message, "feedback error"));
  } finally {
    document.documentElement.classList.remove("booting");
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("ticket-submitted", () => { render(); loadTrust(); });
window.setInterval(refreshReminder, 60000);
buyer.addEventListener("change", () => {
  if (buyer.dataset.admin === "true") {
    sessionStorage.setItem("agent-dairy-admin-buyer", buyer.value);
    // Reload so pending requests and open editors cannot cross workspace boundaries.
    window.location.reload();
  } else connect();
});
for (const code of ["en", "fi"]) $("lang-" + code).addEventListener("click", async () => {
  try { await save({...settings, language:code}); render(); loadTrust(); }
  catch (error) { feedback($("reminder"), error.message, true); }
});
$("help-open").addEventListener("click", () => $("client-help").showModal());
function loginScreen(show) {
  $("client-login").hidden = !show;
  $("main").querySelector(".top").hidden = show;
  $("main").querySelector(".content").hidden = show;
  document.querySelector(".rail").hidden = show;
  if (show) $("draft-sidebar").hidden = true;
}

$("client-login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    await request("/session/login", "", {username:$("client-username").value, password:$("client-password").value});
    window.location.reload();
  } catch (error) {
    feedback($("client-login-status"), error.message, true);
    button.disabled = false;
  }
});

$("client-sign-out").addEventListener("click", async () => {
  if (buyer.dataset.hosted === "true") await request("/session/logout", "", {});
  else sessionStorage.setItem("agent-dairy-signed-out", "true");
  window.location.reload();
});
async function initialize() {
  const session = await request("/session", "");
  $("offline-demo-banner").hidden = !session.offline_demo;
  $("admin-panel-link").hidden = session.role !== "admin";
  if (session.required || session.username) {
    buyer.dataset.hosted = "true";
    buyer.disabled = session.role !== "admin";
    if (!session.username) {
      loginScreen(true);
      document.documentElement.classList.remove("booting");
      return;
    }
    if (session.role === "admin") {
      buyer.dataset.admin = "true";
      const selected = sessionStorage.getItem("agent-dairy-admin-buyer");
      buyer.value = ["hotel", "hospital"].includes(selected) ? selected : "hotel";
    } else buyer.value = session.buyer_id;
    loginScreen(false);
    await connect();
    return;
  }
  if (sessionStorage.getItem("agent-dairy-signed-out")) {
    loginScreen(true);
    const button = node("button", "Open demo workspace");
    button.type = "button";
    button.addEventListener("click", () => {
      sessionStorage.removeItem("agent-dairy-signed-out");
      window.location.reload();
    });
    $("client-login").append(button);
    document.documentElement.classList.remove("booting");
  } else {
    await connect();
  }
}
initialize().catch(error => root.replaceChildren(node("p", error.message, "feedback error")));
