export const $ = id => document.getElementById(id);
export const number = new Intl.NumberFormat("en-FI", {maximumFractionDigits: 2});
export const money = new Intl.NumberFormat("en-FI", {style: "currency", currency: "EUR"});
const dateFormat = new Intl.DateTimeFormat("en-FI", {dateStyle: "medium", timeZone: "Europe/Helsinki"});
export const date = value => value ? dateFormat.format(new Date(value)) : "—";
export const statusText = {confirmed:"Confirmed", pending_approval:"Needs review", rejected:"Rejected", expired:"Expired"};

export function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
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
      cell.append(value ?? "—");
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
  const headers = {"X-API-Key": key};
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method: payload === undefined ? "GET" : "POST", headers,
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
