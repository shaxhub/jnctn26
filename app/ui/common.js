export const $ = id => document.getElementById(id);
export const portalUrl = path => new URL(path.replace(/^\//, ""), document.baseURI).href;
export const number = new Intl.NumberFormat("en-FI", {maximumFractionDigits: 2});
export const money = new Intl.NumberFormat("en-FI", {style: "currency", currency: "EUR"});
const dateFormat = new Intl.DateTimeFormat("fi-FI", {dateStyle: "short", timeZone: "Europe/Helsinki"});
const dateTimeFormat = new Intl.DateTimeFormat("fi-FI", {dateStyle: "short", timeStyle: "short", timeZone: "Europe/Helsinki"});
export const date = value => value ? dateFormat.format(new Date(value)) : "—";
export const dateTime = value => value ? dateTimeFormat.format(new Date(value)) : "—";
// dd.mm.yyyy for inputs; ISO (yyyy-mm-dd) for the API.
export const inputDate = value => {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? match[3] + "." + match[2] + "." + match[1] : "";
};
export const parseInputDate = value => {
  const match = String(value || "").trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!match || match[3] === "0000") return null;
  const iso = match[3] + "-" + match[2].padStart(2, "0") + "-" + match[1].padStart(2, "0");
  const parsed = new Date(iso);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().startsWith(iso + "T") ? iso : null;
};
export const statusText = {confirmed:"Confirmed", pending_approval:"Needs review", rejected:"Rejected", expired:"Expired"};

const finnish = {
  "All mandate rules passed.":"Kaikki hankintasäännöt täyttyvät.",
  "Confirmed":"Vahvistettu", "Needs review":"Tarkistettava", "Rejected":"Hylätty", "Expired":"Vanhentunut",
  "Product":"Tuote", "Ingredient":"Raaka-aine", "Quantity":"Määrä", "Net price / unit":"Veroton yksikköhinta",
  "Net total":"Veroton summa", "Availability":"Saatavuus", "Earliest date":"Aikaisin toimitus",
  "Reliability":"Toimitusvarmuus", "Stock":"Varasto", "Status":"Tila", "Delivery":"Toimitus",
  "Draft":"Luonnos", "Request":"Pyyntö", "Stage":"Toimitusvaihe", "Used in":"Käyttökohteet",
  "Matched products":"Sopivat tuotteet", "Recipe ingredients":"Reseptin raaka-aineet",
  "Submit ticket to Aimo":"Lähetä tilaus Aimolle", "Review and submit":"Tarkista ja lähetä",
  "AI Helper":"Tekoälyavustaja", "Ask AI Helper":"Kysy tekoälyavustajalta", "Suggest edit":"Ehdota muokkausta",
  "Save revised draft":"Tallenna muutokset", "Delivery date":"Toimituspäivä",
  "Ticket review":"Tilauksen tarkistus", "Saved drafts":"Tallennetut luonnokset", "Request history":"Pyyntöjen historia",
  "Order plans":"Tilausvaihtoehdot", "Draft this plan":"Tee tästä luonnos",
  "Policy decision":"Tilauspäätös", "Audit trail":"Tapahtumahistoria", "Signed quote":"Allekirjoitettu tarjous",
  "Quote verification keys":"Tarjouksen varmennusavaimet",
  "Recurring order comparison":"Toistuvien tilausten vertailu", "New delivery date":"Uusi toimituspäivä",
  "Create repeat draft":"Luo uusi luonnos", "Request conversation":"Keskustelu tilauksesta",
  "Close":"Sulje", "Previous":"Edellinen", "Next":"Seuraava", "Message":"Viesti", "Send message":"Lähetä viesti",
  "Refresh conversation":"Päivitä keskustelu", "Delivery tracking":"Toimituksen seuranta",
  "No messages on this request yet.":"Tilauksella ei vielä ole viestejä.",
  "Create a draft from Product Search to see it here.":"Luo luonnos tuotehaussa, niin näet sen täällä.",
  "Submitted tickets will appear here.":"Lähetetyt tilaukset näkyvät täällä.",
  "Suggest changes to quantities or delivery date, then save a fresh quote.":"Pyydä muutoksia määriin tai toimituspäivään ja tallenna uusi tarjous.",
  "Needs fresh quote":"Uusi tarjous tarvitaan", "Ready to review":"Valmis tarkistettavaksi",
  "available":"Saatavilla", "unmatched":"Tuotetta ei löytynyt", "unverified":"Saatavuus vahvistamatta",
  "partial":"Saatavilla osittain", "stockout":"Loppu varastosta",
};
export const translate = text => document.documentElement.lang === "fi" && typeof text === "string" ?
  finnish[text] ?? text : text;

export function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = translate(text);
  if (className) element.className = className;
  return element;
}

export function table(headings, rows) {
  const grid = node("table");
  const header = grid.createTHead().insertRow();
  for (const title of headings) {
    const th = node("th", title);
    th.scope = "col";
    header.append(th);
  }
  const body = grid.createTBody();
  for (const values of rows) {
    const row = body.insertRow();
    for (const value of values) {
      const cell = row.insertCell();
      cell.append(translate(value ?? "—"));
    }
  }
  const scroll = node("div", "", "table-scroll");
  scroll.append(grid);
  return scroll;
}

export function pill(status) {
  return node("span", statusText[status] || status, "tag " + status);
}

export function feedback(target, text, error = false) {
  target.hidden = !text;
  target.classList.toggle("error", error);
  target.textContent = text;
}

export async function request(path, key, payload) {
  const headers = key ? {"X-API-Key": key} : {};
  const workspace = $("buyer");
  if (workspace?.dataset.admin === "true") headers["X-Workspace-Buyer"] = workspace.value;
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(portalUrl(path), {method: payload === undefined ? "GET" : "POST", headers,
    body: payload === undefined ? undefined : JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "The server could not process this request.");
  }
  return data;
}

export function lineItems(lines) {
  const list = node("ul", "", "ticket-lines");
  for (const line of lines) {
    list.append(node("li", (line.name || line.product_id) + " · " +
      number.format(line.quantity) + " " + line.sales_unit + " · " + money.format(line.line_total)));
  }
  return list;
}

export function auditTrail(audit) {
  const section = node("section", "", "audit-trail");
  const timeline = node("ol", "", "timeline");
  for (const event of audit.events) {
    const entry = node("li");
    const time = node("time", dateTime(event.ts), "cell-note");
    time.dateTime = event.ts;
    const label = event.event_type.toLowerCase().replaceAll("_", " ");
    const outcome = event.data?.decision?.replaceAll("_", " ");
    const summary = event.summary || label[0].toUpperCase() + label.slice(1) + (outcome ? " · " + outcome : "");
    entry.append(time, node("p", summary));
    timeline.append(entry);
  }
  section.append(node("h3", "Audit trail"), timeline);
  if (audit.chain) section.append(node("p",
    audit.chain.ok ? "Audit chain verified" : "Audit chain verification failed", "cell-note"));
  return section;
}
