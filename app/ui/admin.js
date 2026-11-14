import {$, date, feedback, lineItems, money, node, number, pill, request, table} from "./common.js";

let key = sessionStorage.getItem("aimo-operations-key") || "";
let view = "queue";
let page = null;
let version = 0;
const recordTarget = $("records");

function ticketButton(id) {
  const button = node("button", id);
  button.addEventListener("click", () => inspect(id));
  return button;
}

async function inspect(id) {
  const dialog = $("details");
  const target = $("detail-body");
  target.replaceChildren(node("p", "Loading ticket…", "empty"));
  if (!dialog.open) dialog.showModal();
  try {
    const detail = await request("/operations/orders/" + encodeURIComponent(id), key);
    const order = detail.order;
    target.replaceChildren(pill(order.status),
      node("p", order.buyer_id + " · Delivery " + date(order.delivery_date) + " · " + money.format(order.total_net), "cell-note"),
      lineItems(order.lines), node("h3", "Policy decision", "results"),
      node("p", order.policy.reasons.join(" ")));
    if (detail.approval?.status === "pending") target.append(reviewForm(detail.approval.approval_id, id));
    else if (detail.approval?.decided_at) {
      target.append(node("p", "Reviewed " + date(detail.approval.decided_at) + " by " +
        detail.approval.decided_by + (detail.approval.comment ? " · " + detail.approval.comment : ""), "cell-note"));
    }
    const timeline = node("ol", "", "timeline");
    for (const event of detail.audit.events) {
      timeline.append(node("li", event.summary || event.event_type.replaceAll("_", " ")));
    }
    target.append(node("h3", "Audit trail", "results"), timeline,
      node("p", detail.audit.chain.ok ? "Audit chain verified" : "Audit chain verification failed", "cell-note"));
  } catch (error) {
    target.replaceChildren(node("p", error.message, "feedback error"));
  }
}

function reviewForm(approvalId, orderId) {
  const form = node("form");
  const label = node("label", "Review note");
  const input = node("textarea");
  input.rows = 2;
  input.maxLength = 1000;
  label.append(input);
  const actions = node("div", "", "actions");
  const buttons = ["approve", "reject"].map(decision => {
    const button = node("button", decision === "approve" ? "Approve ticket" : "Reject ticket",
      decision === "approve" ? "primary" : "");
    button.value = decision;
    actions.append(button);
    return button;
  });
  const notice = node("p", "", "feedback");
  notice.hidden = true;
  notice.setAttribute("role", "status");
  form.append(label, actions, notice);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!event.submitter) return;
    buttons.forEach(button => { button.disabled = true; });
    try {
      await request("/operations/approvals/" + encodeURIComponent(approvalId), key,
        {decision: event.submitter.value, comment: input.value});
      await Promise.all([inspect(orderId), load()]);
    } catch (error) {
      feedback(notice, error.message, true);
      buttons.forEach(button => { button.disabled = false; });
    }
  });
  return form;
}

function renderRows(rows, append) {
  const isQueue = view === "queue";
  const headers = isQueue ? ["Ticket", "Client", "Status", "Delivery", "Net total", "Policy"]
    : ["Time", "Client", "Event", "Details", "Ticket"];
  const values = isQueue ? rows.map(order => [ticketButton(order.order_id), order.buyer_id,
    pill(order.status), date(order.delivery_date), money.format(order.total_net), order.policy.reasons[0]])
    : rows.map(event => [new Date(event.ts).toLocaleString("en-FI", {timeZone:"Europe/Helsinki"}),
      event.sector, event.event_type.toLowerCase().replaceAll("_", " "), event.summary,
      event.order_id ? ticketButton(event.order_id) : "—"]);
  if (!rows.length && !append) {
    recordTarget.replaceChildren(node("p", isQueue ? "No tickets match these filters." : "No activity matches these filters.", "empty"));
    return;
  }
  const grid = table(headers, values);
  if (append) {
    const body = recordTarget.querySelector("tbody");
    body.append(...grid.querySelector("tbody").rows);
  } else {
    recordTarget.replaceChildren(grid);
  }
}

async function load(append = false) {
  const current = ++version;
  const selected = view;
  if (selected === "insights") {
    await insights(current);
    return;
  }
  const isQueue = selected === "queue";
  const params = new URLSearchParams({q: $("query").value, buyer: $("buyer").value});
  if (isQueue && $("status").value) params.set("status", $("status").value);
  if (!isQueue) params.set("kind", $("kind").value);
  if (append && page != null) params.set(isQueue ? "offset" : "before", page);
  if (!append) recordTarget.replaceChildren(node("p", "Loading activity…", "empty"));
  $("more").hidden = true;
  try {
    const data = await request("/operations/" + (isQueue ? "orders" : "activity") + "?" + params, key);
    if (current !== version) return;
    page = isQueue ? data.next_offset : data.next_before;
    renderRows(isQueue ? data.orders : data.events, append);
    $("more").hidden = page == null;
  } catch (error) {
    if (current === version) recordTarget.replaceChildren(node("p", error.message, "feedback error"));
  }
}

function chart(title, labels) {
  const section = node("section");
  section.append(node("h3", title));
  const max = Math.max(1, ...labels.map(([, value]) => value));
  if (!labels.length) section.append(node("p", "No recorded activity", "cell-note"));
  for (const [label, value] of labels) {
    const entry = node("label", label + " · " + number.format(value), "cell-note");
    const meter = node("meter");
    meter.max = max;
    meter.value = value;
    entry.append(meter);
    section.append(entry);
  }
  return section;
}

async function insights(current) {
  const target = $("analytics");
  target.replaceChildren(node("p", "Loading analytics…", "empty"));
  try {
    const data = await request("/operations/analytics?period=" + encodeURIComponent($("period").value), key);
    if (current !== version) return;
    const metrics = node("dl", "", "metrics");
    for (const [title, value] of [["Inquiries", data.inquiries],
      ["Confirmed orders", data.statuses.confirmed ?? 0], ["Needs review", data.statuses.pending_approval ?? 0],
      ["Confirmed net spend", money.format(data.confirmed_net_eur)],
      ["Estimated kg CO₂e", data.estimated_kg_co2e == null ? "—" : number.format(data.estimated_kg_co2e)]]) {
      const metric = node("div");
      metric.append(node("dt", title), node("dd", value));
      metrics.append(metric);
    }
    const charts = node("div", "", "analytics-grid");
    const sectors = Object.entries(data.sectors);
    charts.append(chart("Inquiries by client sector", sectors.map(([sector, stats]) => [sector, stats.inquiries])),
      chart("Estimated kg CO₂e by sector", sectors.filter(([, stats]) => stats.carbon_covered_lines)
        .map(([sector, stats]) => [sector, stats.kg_co2e])),
      chart("Most queried product categories", Object.entries(data.categories)));
    target.replaceChildren(metrics, node("p", "Carbon coverage · " + data.carbon_covered_lines +
      " confirmed lines estimated, " + data.carbon_missing_lines + " with missing factors or weights", "cell-note"), charts,
      node("h3", "Most ordered products", "results"),
      table(["Product", "Code", "Quantity", "Sales unit"], data.products.map(p => [p.name, p.product_id, number.format(p.quantity), p.sales_unit])),
      node("h3", "Top buyers by confirmed orders", "results"),
      table(["Client", "Orders", "Net spend"], data.buyers.map(b => [b.buyer_id, b.orders, money.format(b.net_eur)])));
  } catch (error) {
    if (current === version) target.replaceChildren(node("p", error.message, "feedback error"));
  }
}

function showView(next) {
  view = next;
  $("work").hidden = next === "insights";
  $("insights").hidden = next !== "insights";
  $("status-label").hidden = next !== "queue";
  $("kind-label").hidden = next !== "activity";
  $("work-title").textContent = next === "queue" ? "Review queue" : "Activity log";
  for (const tab of ["queue", "activity", "insights"]) {
    $(tab + "-tab").setAttribute("aria-pressed", String(tab === next));
  }
  load();
}

async function signIn(credential) {
  try {
    await request("/operations/activity", credential);
    key = credential;
    sessionStorage.setItem("aimo-operations-key", key);
    $("login").hidden = true;
    $("dashboard").hidden = false;
    $("sign-out").hidden = false;
    $("admin-key").value = "";
    showView("queue");
  } catch (error) {
    sessionStorage.removeItem("aimo-operations-key");
    feedback($("login-status"), error.message, true);
  }
}

$("sign-in").addEventListener("submit", event => {
  event.preventDefault();
  signIn($("admin-key").value.trim());
});
$("sign-out").addEventListener("click", () => {
  key = "";
  version += 1;
  sessionStorage.removeItem("aimo-operations-key");
  $("dashboard").hidden = true;
  $("sign-out").hidden = true;
  $("login").hidden = false;
  if ($("details").open) $("details").close();
  $("admin-key").focus();
});
$("filters").addEventListener("submit", event => { event.preventDefault(); load(); });
$("refresh").addEventListener("click", () => load());
$("more").addEventListener("click", () => load(true));
$("period").addEventListener("change", () => load());
for (const tab of ["queue", "activity", "insights"]) $(tab + "-tab").addEventListener("click", () => showView(tab));
if (key) signIn(key);
