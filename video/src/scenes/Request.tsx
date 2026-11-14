import React from "react";
import { interpolate, Sequence, useCurrentFrame } from "remotion";
import { Browser, Card, ClientShell, GhostButton, YellowButton } from "../components/AppChrome";
import { Caption, FadeUp, PageBackdrop, Sparkle, Tag, Typewriter, useEnter, useKeyframes } from "../components/ui";
import { HOTEL_LIMITS, LIMIT_MESSAGE, OFFERS, QUOTE_TOTAL } from "../data";
import { C, CLIENT_URL } from "../theme";

const W = 1780;
const H = 880;
const ZOOM = 1.3;
const LW = W / ZOOM;
const LH = (H - 56) / ZOOM;

const REQUEST = "I need 1,000 litres of lactose-free milk by Monday.";
const COLS = "2.2fr 0.72fr 0.55fr 0.8fr 1.3fr";

const OfferRow: React.FC<{ o: (typeof OFFERS)[number]; delay: number }> = ({ o, delay }) => {
  const p = useEnter(delay);
  const out = o.tone !== "green";
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: COLS,
        gap: 10,
        alignItems: "center",
        padding: "11px 6px",
        borderBottom: `1px solid ${C.line}`,
        fontSize: 14.5,
        opacity: p * (out ? 0.8 : 1),
        transform: `translateX(${(1 - p) * 30}px)`,
      }}
    >
      <span>
        <span style={{ fontWeight: 600, textDecoration: out ? "line-through" : "none", textDecorationColor: "rgba(155,44,31,0.55)" }}>{o.name}</span>
        <span style={{ display: "block", fontSize: 12, color: C.muted, marginTop: 2 }}>
          {o.id} · {o.pack}
        </span>
      </span>
      <span style={{ fontWeight: 700 }}>{o.price}</span>
      <span style={{ color: C.muted }}>{o.perL}</span>
      <span style={{ color: C.muted }}>{o.stock}</span>
      <span>
        <Tag tone={o.tone} size={13}>
          {o.status}
        </Tag>
      </span>
    </div>
  );
};

export const Request: React.FC = () => {
  const frame = useCurrentFrame();
  const press = interpolate(frame, [70, 75, 80], [1, 0.93, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const draftPress = interpolate(frame, [232, 237, 242], [1, 0.93, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const draft = useEnter(246);
  const camY = useKeyframes([0, 100, 140, 228, 262], [120, 120, 395, 395, 162]);
  const camX = useKeyframes([0, 228, 262], [250, 250, 316]);

  return (
    <PageBackdrop>
      <div style={{ position: "absolute", left: 70, top: 36 }}>
        <Browser url={CLIENT_URL} width={W} height={H} zoom={ZOOM} camera={{ s: 1.25, x: camX, y: camY }}>
          <ClientShell active="Product Search" title="Product Search" sub="Find products, compare live offers, or paste a recipe." width={LW} height={LH + 400}>
            <div style={{ display: "grid", gridTemplateColumns: "660px 1fr", gap: 24, alignItems: "start" }}>
              <div style={{ display: "grid", gap: 22 }}>
                <Card>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: "-0.02em" }}>Ask Agent Dairy</div>
                    <Sparkle size={22} />
                  </div>
                  <div
                    style={{
                      marginTop: 14,
                      border: `1.5px solid ${frame < 76 ? C.blue : C.lineStrong}`,
                      borderRadius: 10,
                      padding: "12px 14px",
                      fontSize: 17,
                      minHeight: 70,
                    }}
                  >
                    <Typewriter text={REQUEST} start={14} cps={34} caret={frame < 76} />
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", minHeight: 26, flexWrap: "wrap" }}>
                    {frame >= 84 ? (
                      <FadeUp delay={84} distance={6}>
                        <span style={{ fontSize: 12.5, color: C.muted }}>Understood as</span>
                      </FadeUp>
                    ) : null}
                    {["lactose-free milk", "1,000 L", "Mon 16 Nov", "hotel kitchen"].map((c, i) => (
                      <FadeUp key={c} delay={88 + i * 4} distance={6}>
                        <span style={{ fontSize: 12.5, fontWeight: 600, padding: "4px 10px", borderRadius: 999, background: C.pale, color: C.navy }}>{c}</span>
                      </FadeUp>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
                    <YellowButton press={press}>Check offers</YellowButton>
                    <GhostButton style={{ transform: `scale(${draftPress})`, background: frame >= 236 ? C.pale : C.white }}>Create ticket draft</GhostButton>
                  </div>
                </Card>

                <FadeUp delay={100} distance={20}>
                  <Card>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <div style={{ fontSize: 17, fontWeight: 700 }}>Live offers · Mon 16 Nov</div>
                      <div style={{ fontSize: 12, color: C.muted }}>Valio Aimo price & availability</div>
                    </div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: COLS,
                        gap: 10,
                        padding: "12px 6px 8px",
                        borderBottom: `1px solid ${C.line}`,
                        fontSize: 12.5,
                        color: C.muted,
                        fontWeight: 600,
                      }}
                    >
                      <span>Product</span>
                      <span>Net / unit</span>
                      <span>€ / L</span>
                      <span>Stock</span>
                      <span>Status</span>
                    </div>
                    {OFFERS.map((o, i) => (
                      <OfferRow key={o.id} o={o} delay={112 + i * 10} />
                    ))}
                  </Card>
                </FadeUp>
              </div>

              <div style={{ display: "grid", gap: 22 }}>
                <Card>
                  <div style={{ fontSize: 19, fontWeight: 700 }}>Ticket review</div>
                  {frame < 246 ? (
                    <div style={{ marginTop: 12, background: C.sky, borderRadius: 10, padding: 14, fontSize: 14, color: C.muted }}>
                      Create a ticket draft to review quantities, prices and the delivery date.
                    </div>
                  ) : (
                    <div style={{ opacity: draft, transform: `translateY(${(1 - draft) * 12}px)` }}>
                      <div style={{ fontSize: 14, marginTop: 10 }}>Delivery 16.11.2026</div>
                      <div style={{ fontSize: 12, color: C.muted }}>Signed quote · expires 15.11.2026 klo 17.00</div>
                      <div style={{ fontSize: 14, marginTop: 10 }}>• Valio Arki® Eila® 1 l laktoositon · 1,000 ST</div>
                      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 12, letterSpacing: "-0.02em" }}>{QUOTE_TOTAL} excl. VAT</div>
                      <div style={{ marginTop: 10, background: C.amberBg, color: C.amber, borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontWeight: 600 }}>
                        {LIMIT_MESSAGE}
                      </div>
                      <YellowButton style={{ marginTop: 12, fontSize: 14 }}>Submit ticket to Aimo</YellowButton>
                    </div>
                  )}
                </Card>
                <Card>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: 19, fontWeight: 700 }}>Purchasing limits</div>
                    <Tag tone="blue" size={11}>
                      MANDATE
                    </Tag>
                  </div>
                  <div style={{ marginTop: 8 }}>
                    {HOTEL_LIMITS.map(([k, v]) => (
                      <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderBottom: `1px solid ${C.line}`, fontSize: 13 }}>
                        <span style={{ color: C.muted }}>{k}</span>
                        <b>{v}</b>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </div>
          </ClientShell>
        </Browser>
      </div>
      <Sequence from={140} durationInFrames={100} layout="none">
        <Caption>Live prices and stock. Bad offers are filtered out — with the reason.</Caption>
      </Sequence>
      <Sequence from={262} layout="none">
        <Caption>Best plan: €1,010 — just over the hotel’s €1,000 automatic limit.</Caption>
      </Sequence>
    </PageBackdrop>
  );
};
