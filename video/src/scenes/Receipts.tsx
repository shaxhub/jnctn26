import React from "react";
import { useCurrentFrame } from "remotion";
import { FadeUp, Headline, Kicker, PageBackdrop, Pop, useEnter } from "../components/ui";
import { C, MONO } from "../theme";

// Human-readable versions of the audit events for the 1,000 L order (app/gateway/audit.py summaries).
const RECEIPTS = [
  "Agent asked for 1,000 L lactose-free milk by Monday",
  "4 offers checked · 2 filtered out",
  "Quote signed · €1,010.00",
  "Over the €1,000 automatic limit → human review",
  "Warehouse check passed",
  "Approved by Aimo operations",
  "Order confirmed",
];
const TAMPERED = 3;

const Link: React.FC<{ broken: boolean }> = ({ broken }) => (
  <svg width={30} height={26} viewBox="0 0 30 26" style={{ marginLeft: 30 }}>
    <path d="M15 0 V26" stroke={broken ? C.red : C.lineStrong} strokeWidth={4} strokeDasharray={broken ? "4 5" : undefined} />
  </svg>
);

export const Receipts: React.FC = () => {
  const frame = useCurrentFrame();
  const editAt = 120;
  const edited = frame >= editAt;
  const brokenFrom = (i: number) => edited && i > TAMPERED && frame >= editAt + 14 + (i - TAMPERED) * 6;
  return (
    <PageBackdrop>
      <div style={{ position: "absolute", left: 120, top: 120, width: 660 }}>
        <Kicker>Audit trail</Kicker>
        <div style={{ height: 16 }} />
        <Headline size={72}>Every step leaves a receipt.</Headline>
        <FadeUp delay={30}>
          <p style={{ fontSize: 34, lineHeight: 1.4, color: C.muted, marginTop: 32 }}>
            The buyer and Aimo read the same plain-language history.
          </p>
        </FadeUp>
        {edited ? (
          <Pop delay={editAt + 50}>
            <div style={{ marginTop: 40, background: C.redBg, color: C.red, borderRadius: 18, padding: "22px 26px", fontSize: 34, fontWeight: 700, lineHeight: 1.3 }}>
              Change one receipt and the chain no longer adds up.
            </div>
          </Pop>
        ) : null}
        <FadeUp delay={editAt + 70}>
          <div style={{ fontFamily: MONO, fontSize: 21, color: C.muted, marginTop: 26 }}>Each entry carries the SHA-256 hash of the one before it.</div>
        </FadeUp>
      </div>

      <div style={{ position: "absolute", left: 880, top: 110, width: 920 }}>
        {RECEIPTS.map((r, i) => {
          const p = useEnter(16 + i * 9);
          const broken = brokenFrom(i);
          const isEdited = i === TAMPERED && edited;
          return (
            <div key={r} style={{ opacity: p, transform: `translateX(${(1 - p) * 40}px)` }}>
              {i > 0 ? <Link broken={broken} /> : null}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 18,
                  background: broken ? C.redBg : C.white,
                  border: `2px solid ${isEdited ? C.red : broken ? "#efc2ba" : C.line}`,
                  borderRadius: 16,
                  padding: "16px 22px",
                  fontSize: 27,
                  boxShadow: "0 8px 20px rgba(11,36,64,0.05)",
                }}
              >
                <span style={{ fontFamily: MONO, fontSize: 20, color: broken || isEdited ? C.red : C.muted, width: 30 }}>{String(i + 1).padStart(2, "0")}</span>
                <span style={{ flex: 1, color: broken ? C.red : C.ink }}>
                  {isEdited ? (
                    <>
                      <span style={{ textDecoration: "line-through", color: "#a8b3c0" }}>Over the €1,000 limit</span>{" "}
                      <b style={{ color: C.red }}>Within limits → auto-confirm</b>
                    </>
                  ) : (
                    r
                  )}
                </span>
                {broken ? <span style={{ fontSize: 20, fontWeight: 700, color: C.red }}>✕ mismatch</span> : null}
              </div>
            </div>
          );
        })}
      </div>
    </PageBackdrop>
  );
};
