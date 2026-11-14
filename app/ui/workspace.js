import {$, date, feedback, inputDate, money, node, number, parseInputDate, portalUrl, request, table} from "./common.js";
import {buyerKey, editBasket, inspectTicket, showDraft, ticketNameForm} from "./client.js";
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

async function loadDraftFlyout() {
  const flyout = $("draft-flyout");
  if (flyout.hidden) return;
  flyout.replaceChildren(node("h2", t("Saved drafts")));
  try {
    const drafts = await request("/client/drafts", buyerKey());
    if (flyout.hidden) return;
    if (!drafts.length) flyout.append(node("p", language() === "fi" ? "Ei luonnoksia." : "No saved drafts."));
    for (const quote of drafts) {
      const button = node("button", quote.name || quote.quote_id);
      button.type = "button";
      button.addEventListener("click", () => {
        draftSelection = quote.quote_id;
        $("draft-flyout-toggle").click();
        if (viewName() === "drafts") showDrafts(draftSelection);
        else location.hash = "drafts";
      });
      flyout.append(button);
    }
  } catch (error) { flyout.append(node("p", error.message, "feedback error")); }
}

const draftsNav = document.querySelector('[data-view="drafts"]');
const flyoutToggle = node("button", "›", "draft-flyout-toggle");
flyoutToggle.id = "draft-flyout-toggle";
flyoutToggle.type = "button";
flyoutToggle.setAttribute("aria-label", "Saved drafts / Tallennetut luonnokset");
flyoutToggle.setAttribute("aria-controls", "draft-flyout");
flyoutToggle.setAttribute("aria-expanded", "false");
const draftNavRow = node("div", "", "draft-nav-row");
draftsNav.replaceWith(draftNavRow);
draftNavRow.append(draftsNav, flyoutToggle);
flyoutToggle.addEventListener("click", () => {
  const flyout = $("draft-flyout");
  flyout.hidden = !flyout.hidden;
  $("draft-flyout-toggle").setAttribute("aria-expanded", String(!flyout.hidden));
  loadDraftFlyout();
});
window.addEventListener("draft-changed", loadDraftFlyout);
window.addEventListener("ticket-renamed", event => {
  loadDraftFlyout();
  if (viewName() === "drafts") showDrafts(event.detail.url.split("/").at(-1));
  if (viewName() === "requests") showRequests();
});
let settings = {};
let version = 0;
let year = Number(new Intl.DateTimeFormat("en", {year:"numeric", timeZone:"Europe/Helsinki"}).format(new Date()));
let preferenceWrites = Promise.resolve();

function viewName() {
  const name = location.hash.slice(1);
  return Object.hasOwn(views, name) ? name : "products";
}

function language() { return settings.language || "en"; }

function applyPreferences() {
  document.documentElement.dataset.theme = settings.theme || "light";
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
  const pipeline = node("ol", "", "delivery-pipeline");
  for (const stage of stages) {
    const step = node("li");
    step.append(node("strong", String(data.stages[stage] ?? 0)), node("span", stageName(stage, language())));
    pipeline.append(step);
  }
  section.append(totals, pipeline);
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

function draftEditor(quote, selected, state) {
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
      input.value = inputDate(suggestion.delivery_date);
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
      const delivery = parseInputDate(input.value);
      if (!delivery) throw new Error("Enter the delivery date as dd.mm.yyyy.");
      const quantities = Object.fromEntries([...fields].map(([sku, field]) => [sku, Number(field.value)]).filter(([, value]) => value > 0));
      const fresh = await request(base + "/edit", key, {delivery_date:delivery, quantities});
      if (state === version) showDrafts(fresh.quote_id);
      window.dispatchEvent(new Event("draft-changed"));
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
    const button = node("button", quote.name || quote.quote_id);
    button.addEventListener("click", () => showDrafts(quote.quote_id));
    const expired = new Date(quote.expires_at) <= new Date();
    return [button, date(quote.delivery_date), money.format(quote.total_net), expired ? "Needs fresh quote" : "Ready to review"];
  });
  if (rows.length) list.append(table(["Draft", "Delivery", "Net total", "Status"], rows));
  const sidebar = node("aside", "", "side");
  grid.append(list, sidebar);
  const quote = data.find(item => item.quote_id === select) || data[0];
  if (quote) {
    const base = "/client/drafts/" + encodeURIComponent(quote.quote_id);
    const edit = node("button", language() === "fi" ? "Muokkaa tuotehaussa" : "Edit in Product Search");
    edit.addEventListener("click", () => editBasket(quote));
    const remove = node("button", language() === "fi" ? "Poista luonnos" : "Delete draft");
    const notice = node("p", "", "feedback");
    notice.hidden = true;
    remove.addEventListener("click", async () => {
      if (!window.confirm(language() === "fi" ? "Poistetaanko tämä luonnos?" : "Delete this draft?")) return;
      remove.disabled = true;
      try {
        await request(base + "/delete", buyerKey(), {});
        window.dispatchEvent(new Event("draft-changed"));
        if (state === version) showDrafts();
      } catch (error) { feedback(notice, error.message, true); }
      finally { remove.disabled = false; }
    });
    detail.prepend(ticketNameForm(quote.name, base, buyerKey()), edit, remove, notice);
    showDraft(quote, undefined, review);
    sidebar.append(detail, draftEditor(quote, review, state));
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
    const button = node("button", order.name || order.order_id);
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
    measure.setAttribute("aria-label", t(label) + ": " + (value == null ? t("No observations") : format(value)));
    row.append(node("span", t(label)), measure, node("strong", value == null ? "—" : format(value)));
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
  const label = node("label", t("Delivery year"));
  label.append(input);
  form.append(label, node("button", t("Update")));
  form.addEventListener("submit", event => { event.preventDefault(); year = Number(input.value); render(); });
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
  const groups = [
    ["Display and language", [["theme","Appearance",{light:"Light",dark:"Dark"}], ["language","Default language",{en:"English",fi:"Suomi"}]]],
    ["Business and delivery", [["business","Client business"], ["address","Delivery address"]]],
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
      if (type === "checkbox") {
        control.checked = Boolean(settings[id]);
        label.prepend(control);
      } else {
        control.value = settings[id] ?? "";
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
  const hosted = buyer.dataset.hosted === "true";
  const url = hosted ? "https://agent-dairy-mcp.kienlebox.stream/mcp" : portalUrl("/mcp");
  section.append(node("p", local("Create a separate key for each agent. Use Streamable HTTP and an Authorization Bearer header.",
    "Luo jokaiselle agentille oma avain. Käytä Streamable HTTP -yhteyttä ja Authorization Bearer -otsaketta."), "muted"), node("pre", url));
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
  const secret = node("pre");
  secret.hidden = true;
  const list = node("ul");
  const status = node("p", "", "feedback");
  status.hidden = true;
  status.setAttribute("role", "status");
  const key = buyerKey();
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
            secret.hidden = true;
            secret.textContent = "";
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
      secret.textContent = "Authorization: Bearer " + result.secret;
      secret.hidden = false;
      form.reset();
      feedback(status, local("Copy this key now. It is shown once.", "Kopioi avain nyt. Se näytetään vain kerran."));
      await loadKeys();
    } catch (error) { feedback(status, error.message, true); }
    finally { create.disabled = false; }
  });
  if (hosted) {
    const fallback = node("p", local("Funnel endpoint", "Funnel-osoite") +
      " · https://kienlebox.tail80aa1e.ts.net/agent-dairy/mcp", "cell-note");
    section.append(fallback);
    }
  section.append(form, status, secret, list);
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
  root.hidden = view === "products";
  if (root.hidden) return;
  root.replaceChildren(node("p", "Loading workspace…", "empty"));
  try {
    if (view === "drafts") await showDrafts(draftSelection);
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
buyer.addEventListener("change", connect);
for (const code of ["en", "fi"]) $("lang-" + code).addEventListener("click", async () => {
  try { await save({...settings, language:code}); render(); loadTrust(); loadDraftFlyout(); }
  catch (error) { feedback($("reminder"), error.message, true); }
});
$("help-open").addEventListener("click", () => $("client-help").showModal());
function loginScreen(show) {
  $("client-login").hidden = !show;
  $("main").querySelector(".top").hidden = show;
  $("main").querySelector(".content").hidden = show;
  document.querySelector(".rail").hidden = show;
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
  if (session.required) {
    buyer.dataset.hosted = "true";
    buyer.disabled = true;
    if (!session.username) {
      loginScreen(true);
      document.documentElement.classList.remove("booting");
      return;
    }
    buyer.value = session.buyer_id;
    loginScreen(false);
    await connect();
    return;
  }
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
    document.documentElement.classList.remove("booting");
  } else {
    await connect();
  }
}
initialize().catch(error => root.replaceChildren(node("p", error.message, "feedback error")));
