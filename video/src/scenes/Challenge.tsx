import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { FadeUp, Headline, Kicker, PageBackdrop } from "../components/ui";
import { C } from "../theme";

const Stat: React.FC<{ value: number; suffix?: string; label: string; delay: number }> = ({ value, suffix = "", label, delay }) => {
  const frame = useCurrentFrame();
  const n = interpolate(frame, [delay, delay + 36], [0, value], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
  return (
    <FadeUp delay={delay} style={{ flex: 1 }}>
      <div style={{ borderLeft: `6px solid ${C.yellow}`, paddingLeft: 28 }}>
        <div style={{ fontSize: 100, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1 }}>
          {Math.round(n).toLocaleString("en-GB")}
          {suffix}
        </div>
        <div style={{ fontSize: 32, color: C.muted, marginTop: 10, fontWeight: 500 }}>{label}</div>
      </div>
    </FadeUp>
  );
};

export const Challenge: React.FC = () => (
  <PageBackdrop>
    <div style={{ position: "absolute", inset: "100px 140px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 80 }}>
      <div>
        <Kicker>The challenge</Kicker>
        <div style={{ height: 22 }} />
        <Headline size={78}>Valio Aimo’s kitchens will soon order through AI agents.</Headline>
      </div>
      <div style={{ display: "flex", gap: 60 }}>
        <Stat value={20000} suffix="+" label="professional kitchens" delay={22} />
        <Stat value={25000} label="products" delay={32} />
        <Stat value={700} label="suppliers" delay={42} />
      </div>
      <FadeUp delay={100}>
        <div style={{ fontSize: 56, fontWeight: 700, letterSpacing: "-0.03em", color: C.blue, lineHeight: 1.15 }}>
          So what may an agent decide alone —
          <br />
          and what needs a human?
        </div>
      </FadeUp>
    </div>
  </PageBackdrop>
);
