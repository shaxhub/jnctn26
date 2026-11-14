import {dateTime, feedback, node, request} from "./common.js";

export const stages = ["pending", "registered", "retrieving", "on_delivery", "almost_there", "arrived"];
const labels = {
  en: ["Pending", "Aimo registered", "Retrieving goods", "On delivery", "Almost there", "Arrived"],
  fi: ["Odottaa", "Aimo rekisteröinyt", "Kerätään", "Toimituksessa", "Pian perillä", "Saapunut"]
};
export const stageName = (id, language = "en") => labels[language][stages.indexOf(id)] ??
  ({rejected:"Rejected", expired:"Expired"}[id] ?? id);

export function orderThread(detail, {url, key, admin = false, language = "en"}) {
  const section = node("section", "", "request-thread");
  let state = detail;
  function paint() {
    section.replaceChildren(node("h3", "Delivery tracking", "results"));
    section.append(node("p", "Current stage: " + stageName(state.stage, language), "tag"));
    const progress = node("ol", "", "timeline");
    for (const step of state.stages) {
      progress.append(node("li", stageName(step.stage, language) + " · " + dateTime(step.at)));
    }
    section.append(progress);
    const next = stages[stages.indexOf(state.stage) + 1];
    if (admin && stages.indexOf(state.stage) >= 1 && next) {
      const advance = node("button", "Set to " + stageName(next));
      advance.type = "button";
      advance.addEventListener("click", () => update("/stage", {stage: next}, advance));
      section.append(advance);
    }
    section.append(node("h3", "Request conversation", "results"));
    const list = node("ul", "", "thread-messages");
    for (const item of state.messages) {
      const message = node("li");
      message.append(node("strong", ({aimo:"Aimo",client:"Client",agent:"Client agent"})[item.side]),
        node("p", item.text), node("small", dateTime(item.at)));
      list.append(message);
    }
    section.append(list);
    if (!state.messages.length) section.append(node("p", "No messages on this request yet.", "muted"));
    const actions = node("div", "", "actions");
    const form = node("form");
    const label = node("label", "Message");
    const input = node("textarea");
    input.required = true;
    input.maxLength = 2000;
    input.rows = 2;
    label.append(input);
    const submit = node("button", "Send message", "primary");
    const refresh = node("button", "Refresh conversation");
    refresh.type = "button";
    refresh.addEventListener("click", () => update("", undefined, refresh));
    actions.append(submit, refresh);
    form.append(label, actions);
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (input.value.trim()) update("/messages", {text:input.value}, submit);
    });
    section.append(form, status);
  }
  const status = node("p", "", "feedback");
  status.setAttribute("role", "status");
  status.hidden = true;
  async function update(suffix, payload, button) {
    button.disabled = true;
    try {
      state = await request(url + suffix, key, payload);
      feedback(status, "");
      paint();
    } catch (error) {
      feedback(status, error.message, true);
    } finally {
      button.disabled = false;
    }
  }
  paint();
  return section;
}
