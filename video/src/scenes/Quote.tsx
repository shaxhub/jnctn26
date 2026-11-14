import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Logo } from "../components/Logo";
import { Check, Cross, FadeUp, Headline, Kicker, PageBackdrop, Pop, useEnter } from "../components/ui";
import { C, CLIENT_URL, MONO } from "../theme";

export const Quote: React.FC = () => {
  const frame = useCurrentFrame();
  const card = useEnter(12);
  const tamperAt = 96;
  const tampered = frame >= tamperAt + 14;
  const strike = interpolate(frame, [tamperAt, tamperAt + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const crack = interpolate(frame, [tamperAt + 26, tamperAt + 34], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const shake = frame > tamperAt + 26 && frame < tamperAt + 40 ? Math.sin(frame * 2.2) * 6 : 0;

  return (
    <PageBackdrop>
      <div style={{ position: "absolute", left: 120, top: 80 }}>
        <Kicker>Signed quotes</Kicker>
        <div style={{ height: 14 }} />
        <Headline size={70}>A signed price can’t be quietly changed.</Headline>
      </div>

      <div
        style={{
          position: "absolute",
          left: 120,
          top: 300,
          width: 1060,
          opacity: card,
          transform: `translateY(${(1 - card) * 40}px) translateX(${shake}px)`,
        }}
      >
        <div
          style={{
            background: C.white,
            borderRadius: 28,
            border: `2px solid ${tampered ? "#e9b4ab" : C.line}`,
            boxShadow: "0 30px 70px rgba(11,36,64,0.14)",
            padding: "44px 52px",
            position: "relative",
          }}
        >
          <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: "0.12em", color: C.muted }}>QUOTE · HOTEL KITCHEN</div>
          <div style={{ fontSize: 34, marginTop: 14, fontWeight: 600 }}>1,000 × Valio lactose-free milk 1 L</div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", marginTop: 14 }}>
            <span style={{ position: "relative", fontSize: 110, fontWeight: 700, letterSpacing: "-0.05em", color: tampered ? "#b9c3cf" : C.ink }}>
              €1,010.00
              <span
                style={{
                  position: "absolute",
                  left: 0,
                  top: "52%",
                  height: 8,
                  width: `${strike * 100}%`,
                  background: C.red,
                  borderRadius: 4,
                }}
              />
            </span>
            <div style={{ height: 112, display: "flex", alignItems: "center", gap: 18 }}>
              {tampered ? (
                <Pop delay={tamperAt + 14} style={{ transformOrigin: "left center" }}>
                  <span style={{ fontSize: 96, fontWeight: 700, letterSpacing: "-0.05em", color: C.red }}>→ €910.00</span>
                </Pop>
              ) : null}
            </div>
          </div>
          <div style={{ fontSize: 28, color: C.muted, marginTop: 10 }}>Valid until Sun 15 Nov, 17:00 — the order cutoff</div>

          <div style={{ position: "absolute", right: 34, top: 28, width: 150, height: 150 }}>
            <div
              style={{
                width: 150,
                height: 150,
                borderRadius: 75,
                border: `6px solid ${crack > 0 ? C.red : C.navy}`,
                display: "grid",
                placeItems: "center",
                background: crack > 0 ? C.redBg : C.pale,
                transform: `rotate(${-10 + crack * 8}deg)`,
              }}
            >
              <Logo size={72} />
            </div>
            <div style={{ position: "absolute", top: 160, left: -20, right: -20, textAlign: "center", fontSize: 20, fontWeight: 700, letterSpacing: "0.1em", color: crack > 0 ? C.red : C.navy }}>
              {crack > 0 ? "SEAL BROKEN" : "SIGNED"}
            </div>
            {crack > 0 ? (
              <svg width={150} height={150} viewBox="0 0 170 170" style={{ position: "absolute", inset: 0 }}>
                <path
                  d="M30 40 L70 80 L58 98 L100 120 L92 140 L140 158"
                  fill="none"
                  stroke={C.red}
                  strokeWidth={6}
                  strokeLinejoin="round"
                  pathLength={1}
                  strokeDasharray={1}
                  strokeDashoffset={1 - crack}
                />
              </svg>
            ) : null}
          </div>
        </div>
      </div>

      <div style={{ position: "absolute", left: 1260, top: 330, width: 560, display: "grid", gap: 26 }}>
        <FadeUp delay={40}>
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start", fontSize: 32, lineHeight: 1.3 }}>
            <Check size={40} /> <span>Price and stock are fixed and signed by Agent Dairy.</span>
          </div>
        </FadeUp>
        <FadeUp delay={58}>
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start", fontSize: 32, lineHeight: 1.3 }}>
            <Check size={40} /> <span>Anyone can verify it — no need to trust the agent.</span>
          </div>
        </FadeUp>
        {frame >= tamperAt + 40 ? (
          <Pop delay={tamperAt + 40}>
            <div
              style={{
                display: "flex",
                gap: 16,
                alignItems: "flex-start",
                fontSize: 34,
                lineHeight: 1.3,
                background: C.redBg,
                color: C.red,
                padding: "20px 24px",
                borderRadius: 18,
                fontWeight: 700,
              }}
            >
              <Cross size={42} /> <span>Edited quote → signature fails → order refused.</span>
            </div>
          </Pop>
        ) : null}
      </div>

      <FadeUp delay={170} style={{ position: "absolute", left: 120, bottom: 70 }}>
        <div style={{ fontFamily: MONO, fontSize: 23, color: C.muted }}>
          Ed25519 signature · public keys at {CLIENT_URL}/.well-known/jwks.json
        </div>
      </FadeUp>
    </PageBackdrop>
  );
};
