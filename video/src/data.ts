// On-screen data, sourced from the repo so the video matches the product.
import type { Tone } from "./components/ui";

// app/evals/cases.jsonl → milk_1000l_hotel (real challenge catalog data).
export const OFFERS: {
  id: string;
  name: string;
  pack: string;
  price: string;
  perL: string;
  stock: string;
  status: string;
  tone: Tone;
}[] = [
  { id: "464306", name: "Valio Arki® Eila® kevytmaitojuoma 1 l laktoositon", pack: "ST · 1 L", price: "€1.01", perL: "€1.01", stock: "Unlimited", status: "Orderable", tone: "green" },
  { id: "464073", name: "Valio täysmaito 1 l laktoositon UHT", pack: "ST · 1 L", price: "€1.64", perL: "€1.64", stock: "Unlimited", status: "Orderable", tone: "green" },
  { id: "465039", name: "Valio Eila® kevytmaitojuoma 1 l laktoositon", pack: "ST · 5 L", price: "€6.86", perL: "€1.37", stock: "—", status: "Order cutoff passed", tone: "red" },
  { id: "464440", name: "Valio kevytmaito 0,5 l laktoositon UHT", pack: "ST · 0.5 L", price: "€0.88", perL: "€1.76", stock: "Unknown", status: "No stock data", tone: "amber" },
];

// app/mandates/hotel.json
export const HOTEL_LIMITS: [string, string][] = [
  ["Automatic orders", "€1,000.00 net"],
  ["Weekly limit", "€5,000.00 net"],
  ["Used this week", "€0.00"],
  ["Blocked allergens", "None"],
];

export const QUOTE_TOTAL = "€1,010.00";
export const LIMIT_MESSAGE = "Order total €1,010.00 exceeds the per-order limit €1,000.00.";

/** Decision 1 routes an order to a human when P(yes) falls below this (app/gateway/decisions.py). */
export const DECISION_THRESHOLD = 0.85;

/**
 * Gemini Decision 1 questions, worded as in app/ui/admin.js `decisionLabels`, with plain-language
 * versions for the video. `p` values are ILLUSTRATIVE ONLY and are never printed on screen: they set
 * bar lengths relative to the 0.85 threshold. Replace them with the answers recorded under
 * AIMO_APPROVAL_EVALUATED → data.answers from a real run with GEMINI_API_KEY set.
 */
export const INJECTED_ORDER_REVIEW: { key: string; label: string; plain: string; p: number }[] = [
  { key: "matches_request", label: "Matches buyer request", plain: "Is it what the buyer asked for?", p: 0.96 },
  { key: "rationale_consistent", label: "Agent rationale", plain: "Does the agent’s reason match the order?", p: 0.9 },
  { key: "not_duplicate", label: "Distinct from recent orders", plain: "Is it different from recent orders?", p: 0.97 },
  { key: "free_of_instructions", label: "Approval instructions in order text", plain: "Is the text free of instructions to the reviewer?", p: 0.05 },
];

// Warehouse facts as shown in Aimo "Approval evidence" for a 1,000-unit milk order (offline demo run).
export const WAREHOUSE_FACTS = "Pick and load: 68 min · Transit: 35 min · Meets the delivery deadline";

export const FULFILMENT = ["Aimo registered", "Retrieving goods", "On delivery", "Almost there", "Arrived"];

// app/gateway/seed_demo.py DEMO_ADDRESSES["hotel"], without the "[Demo]" marker. Shown as in admin.js deliveryAddress().
export const DELIVERY_ADDRESS = "Hotel kitchen, loading entrance, Esimerkkikatu 1, 00100 Helsinki";
