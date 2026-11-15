import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Logo } from "../components/Logo";
import { Check } from "../components/ui";
import { C, FONT, MONO } from "../theme";
import capture from "./capture.json";
import { CaptionBar } from "./Caption";

/**
 * A neutral chat window labelled ChatGPT (text only, no logos). Every value shown comes from the real
 * MCP calls made with the captured agent key: video/src/demo/capture.json → mcp.
 */
const M = (capture as unknown as {
  mcp: { order_id: string; status: string; total: number; delivery: string; address: string; product: string; product_id: string; unit_price: number; quote_id: string; preview: string; qty: number };
}).mcp;

const eur = (n: number) => `€${n.toFixed(2)}`;
const day = new Date(M.delivery + "T12:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

const PROMPT = "Order 40 packs of Valio unsalted butter (500 g) for Tuesday.";
const REPLY = `Done. Order ${M.order_id} is confirmed: ${M.qty} × ${M.product}, ${eur(M.total)} excl. VAT, delivered ${day} to ${M.address.split(",")[0]}. It’s under your €1,000 automatic limit, so it went straight through.`;

const TOOLS: { name: string; at: number; result: string }[] = [
  { name: "check_offers", at: 110, result: `${M.product} (${M.product_id}) · ${eur(M.unit_price)} per pack · orderable` },
  { name: "create_quote", at: 170, result: `${M.qty} packs · ${eur(M.total)} · signed quote · mandate: ${M.preview}` },
  { name: "place_order", at: 230, result: `${M.order_id} · ${M.status}` },
];
const SEND = 92;
const REPLY_AT = 290;
export const CHAT_FRAMES = 660;

const typed = (text: string, start: number, cps: number, frame: number) => text.slice(0, Math.max(0, Math.floor(((frame - start) / 30) * cps)));

const ToolRow: React.FC<{ t: (typeof TOOLS)[number] }> = ({ t }) => {
  const frame = useCurrentFrame();
  if (frame < t.at) return null;
  const done = frame >= t.at + 24;
  const p = interpolate(frame - t.at, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  const spin = ((frame - t.at) * 18) % 360;
  return (
    <div style={{ opacity: p, transform: `translateY(${(1 - p) * 8}px)`, display: "flex", alignItems: "center", gap: 14, padding: "12px 18px", borderRadius: 14, background: "#f4f6f9", border: "1px solid #e3e7ee", fontSize: 22 }}>
      <div style={{ width: 34, height: 34, borderRadius: 9, background: C.yellow, display: "grid", placeItems: "center", flex: "none" }}>
        <Logo size={26} />
      </div>
      <span style={{ fontWeight: 600, color: "#30343b" }}>Agent Dairy</span>
      <span style={{ fontFamily: MONO, fontSize: 19, color: "#5b6270", background: "white", border: "1px solid #e3e7ee", borderRadius: 7, padding: "2px 9px" }}>{t.name}</span>
      {done ? (
        <span style={{ display: "flex", alignItems: "center", gap: 8, color: "#30343b" }}>
          <Check size={22} /> {t.result}
        </span>
      ) : (
        <svg width={22} height={22} viewBox="0 0 24 24" style={{ transform: `rotate(${spin}deg)` }}>
          <circle cx="12" cy="12" r="9" fill="none" stroke="#c9ced8" strokeWidth={3} />
          <path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke="#30343b" strokeWidth={3} strokeLinecap="round" />
        </svg>
      )}
    </div>
  );
};

export const ChatGPT: React.FC = () => {
  const frame = useCurrentFrame();
  const draft = frame < SEND ? typed(PROMPT, 12, 34, frame) : "";
  const reply = typed(REPLY, REPLY_AT, 55, frame);
  return (
    <AbsoluteFill style={{ background: "#e9eef5", fontFamily: FONT }}>
      <div
        style={{
          position: "absolute",
          left: 160,
          top: 18,
          width: 1600,
          height: 950,
          borderRadius: 18,
          overflow: "hidden",
          background: "white",
          boxShadow: "0 40px 90px rgba(11,36,64,0.22), 0 0 0 1px rgba(11,36,64,0.08)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ height: 50, background: "#e8edf4", display: "flex", alignItems: "center", gap: 9, padding: "0 20px", flex: "none" }}>
          {["#ff6159", "#ffbd2e", "#28c941"].map((c) => (
            <span key={c} style={{ width: 13, height: 13, borderRadius: 7, background: c }} />
          ))}
        </div>
        <div style={{ height: 76, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 36px", borderBottom: "1px solid #eceff3", flex: "none" }}>
          <div style={{ fontSize: 28, fontWeight: 600, color: "#202123" }}>ChatGPT</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 20, color: "#30343b", background: "#f4f6f9", borderRadius: 999, padding: "8px 16px 8px 10px" }}>
            <div style={{ width: 28, height: 28, borderRadius: 8, background: C.yellow, display: "grid", placeItems: "center" }}>
              <Logo size={22} />
            </div>
            Agent Dairy · hotel kitchen
            <span style={{ width: 9, height: 9, borderRadius: 5, background: "#1aa37a" }} />
          </div>
        </div>
        <div style={{ flex: 1, display: "flex", justifyContent: "center", padding: "36px 0" }}>
          <div style={{ width: 1080, display: "flex", flexDirection: "column", gap: 20, fontSize: 27, lineHeight: 1.45, color: "#202123" }}>
            {frame >= SEND ? (
              <div style={{ alignSelf: "flex-end", background: "#f0f1f4", borderRadius: 24, padding: "14px 24px", maxWidth: 760 }}>{PROMPT}</div>
            ) : null}
            <div style={{ display: "grid", gap: 10, marginTop: 6 }}>
              {TOOLS.map((t) => (
                <ToolRow key={t.name} t={t} />
              ))}
            </div>
            {reply ? <div style={{ marginTop: 6 }}>{reply}</div> : null}
          </div>
        </div>
        <div style={{ padding: "0 0 30px", display: "flex", justifyContent: "center", flex: "none" }}>
          <div style={{ width: 1080, minHeight: 66, borderRadius: 33, border: "1px solid #dfe3ea", boxShadow: "0 6px 18px rgba(0,0,0,0.06)", display: "flex", alignItems: "center", padding: "0 28px", fontSize: 25, color: draft ? "#202123" : "#9aa1ad" }}>
            {draft || (frame < SEND ? "" : "Ask anything")}
            {frame < SEND && frame % 30 < 16 ? <span style={{ width: 2, height: 30, background: "#202123", marginLeft: 2 }} /> : null}
          </div>
        </div>
      </div>
      <CaptionBar caps={[{ t: 0, n: "6", text: "The chef orders from ChatGPT, through the same rules" }]} />
    </AbsoluteFill>
  );
};
