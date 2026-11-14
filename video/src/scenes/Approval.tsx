import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { AdminShell, Browser, Card, GhostButton, Pointer, YellowButton } from "../components/AppChrome";
import { Caption, Check, FadeUp, PageBackdrop, Tag, useEnter, useKeyframes } from "../components/ui";
import { FULFILMENT, LIMIT_MESSAGE, QUOTE_TOTAL, WAREHOUSE_FACTS } from "../data";
import { C, OPS_URL } from "../theme";

const W = 1780;
const H = 880;
const ZOOM = 1.3;
const LW = W / ZOOM;
const LH = (H - 56) / ZOOM;

const QUEUE_COLS = "150px 80px 120px 110px 100px 1fr";

export const Approval: React.FC = () => {
  const frame = useCurrentFrame();
  const openAt = 58;
  const approveAt = 196;
  const modal = useEnter(openAt + 4);
  const approved = frame >= approveAt + 4;
  const confirmed = frame >= approveAt + 58;
  const stageOn = (i: number) => frame >= approveAt + 70 + i * 12;

  // Pointer path in screen px (relative to the browser frame).
  const px = useKeyframes([20, openAt - 4, openAt + 30, approveAt - 6], [1300, 440, 900, 262]);
  const py = useKeyframes([20, openAt - 4, openAt + 30, approveAt - 6], [820, 392, 720, 596]);
  const camS = useKeyframes([openAt + 6, openAt + 34], [1, 1.38]);
  const camX = useKeyframes([openAt + 6, openAt + 34], [0, 262]);
  const down = (frame >= openAt - 2 && frame < openAt + 4) || (frame >= approveAt && frame < approveAt + 6);
  const press = interpolate(frame, [approveAt, approveAt + 5, approveAt + 10], [1, 0.93, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <PageBackdrop>
      <div style={{ position: "absolute", left: 70, top: 36 }}>
        <Browser url={OPS_URL} width={W} height={H} zoom={ZOOM} camera={{ s: camS, x: camX, y: 0 }}>
          <AdminShell width={LW} height={LH}>
            <div style={{ display: "flex", gap: 10, marginBottom: 18 }}>
              <YellowButton>Review queue</YellowButton>
              <GhostButton>Activity log</GhostButton>
              <GhostButton>Analytics</GhostButton>
            </div>
            <Card>
              <div style={{ fontSize: 19, fontWeight: 700 }}>Review queue</div>
              <div style={{ display: "grid", gridTemplateColumns: QUEUE_COLS, gap: 12, padding: "16px 8px 8px", fontSize: 13, color: C.muted, fontWeight: 600, borderBottom: `1px solid ${C.line}` }}>
                <span>Ticket</span>
                <span>Client</span>
                <span>Status</span>
                <span>Delivery</span>
                <span>Net total</span>
                <span>Policy</span>
              </div>
              <FadeUp delay={8} distance={8}>
                <div style={{ display: "grid", gridTemplateColumns: QUEUE_COLS, gap: 12, padding: "12px 8px", fontSize: 14, alignItems: "center", borderBottom: `1px solid ${C.line}`, background: frame >= openAt - 2 ? C.pale : "transparent" }}>
                  <span style={{ border: `1px solid ${C.lineStrong}`, borderRadius: 7, padding: "4px 8px", fontWeight: 700, width: "fit-content" }}>ord_7c41e2</span>
                  <span>hotel</span>
                  <span>{confirmed ? <Tag tone="green" size={12}>Confirmed</Tag> : <Tag tone="amber" size={12}>Needs review</Tag>}</span>
                  <span>16.11.2026</span>
                  <span>{QUOTE_TOTAL}</span>
                  <span style={{ fontSize: 13 }}>{LIMIT_MESSAGE}</span>
                </div>
              </FadeUp>
            </Card>
          </AdminShell>

          {frame >= openAt + 4 ? (
            <div style={{ position: "absolute", inset: 0, background: `rgba(11,36,64,${0.45 * modal})` }}>
              <div
                style={{
                  position: "absolute",
                  left: 290,
                  top: 26,
                  width: 800,
                  background: C.white,
                  borderRadius: 16,
                  padding: "24px 28px",
                  opacity: modal,
                  transform: `translateY(${(1 - modal) * 20}px)`,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ fontSize: 21, fontWeight: 700 }}>Ticket details</div>
                  <GhostButton style={{ fontSize: 14, padding: "6px 12px" }}>Close</GhostButton>
                </div>
                <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 12 }}>
                  {confirmed ? <Tag tone="green" size={13}>Confirmed</Tag> : <Tag tone="amber" size={13}>Needs review</Tag>}
                  <span style={{ fontSize: 13, color: C.muted }}>hotel · Delivery 16.11.2026 · {QUOTE_TOTAL}</span>
                </div>
                <div style={{ fontSize: 15, marginTop: 10 }}>• Valio Arki® Eila® kevytmaitojuoma 1 l laktoositon · 1,000 ST · {QUOTE_TOTAL}</div>
                <div style={{ fontSize: 15, fontWeight: 700, marginTop: 14 }}>Policy decision</div>
                <div style={{ fontSize: 15 }}>{LIMIT_MESSAGE}</div>
                <div style={{ marginTop: 12, borderLeft: `4px solid ${C.yellow}`, background: C.sky, borderRadius: 10, padding: "10px 14px" }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>Approval evidence</div>
                  <div style={{ fontSize: 13.5, color: C.muted, marginTop: 2 }}>Warehouse check passed. {WAREHOUSE_FACTS}.</div>
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 16, alignItems: "center" }}>
                  <YellowButton press={press} style={{ background: approved ? C.green : C.yellow, color: approved ? "white" : C.navy, borderColor: approved ? C.green : C.yellowDeep }}>
                    {approved ? "Approved" : "Approve ticket"}
                  </YellowButton>
                  <GhostButton style={{ opacity: approved ? 0.4 : 1 }}>Reject ticket</GhostButton>
                  <div style={{ display: "flex", gap: 14, marginLeft: 10 }}>
                    {["Quote still valid", "Stock rechecked", "Warehouse rechecked"].map((t, i) =>
                      frame >= approveAt + 14 + i * 12 ? (
                        <FadeUp key={t} delay={approveAt + 14 + i * 12} distance={6} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, fontWeight: 600 }}>
                          <Check size={17} /> {t}
                        </FadeUp>
                      ) : null,
                    )}
                  </div>
                </div>
                <div style={{ fontSize: 15, fontWeight: 700, marginTop: 18 }}>Delivery tracking</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, marginTop: 8 }}>
                  {FULFILMENT.map((s, i) => (
                    <div
                      key={s}
                      style={{
                        borderLeft: `3px solid ${stageOn(i) ? C.green : C.line}`,
                        background: stageOn(i) ? C.greenBg : C.sky,
                        padding: "8px 10px",
                        fontSize: 13,
                        fontWeight: 600,
                        color: stageOn(i) ? C.green : C.muted,
                      }}
                    >
                      {s}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </Browser>
        {frame >= 20 && frame < approveAt + 24 ? <Pointer x={px} y={py} down={down} size={48} /> : null}
      </div>
      <Caption delay={approveAt + 60}>A person at Aimo approves. Everything is rechecked live first.</Caption>
    </PageBackdrop>
  );
};
