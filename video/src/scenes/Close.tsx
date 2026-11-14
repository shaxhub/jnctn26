import React from "react";
import { Logo } from "../components/Logo";
import { FadeUp, NavyBackdrop, PoweredByGemini, useEnter, useProgress } from "../components/ui";
import { C, CLIENT_URL } from "../theme";

export const Close: React.FC = () => {
  const m = useEnter(64, 14);
  const arrow = useProgress(70, 86);
  return (
    <NavyBackdrop ringX={1640} ringY={430}>
      <div style={{ position: "absolute", left: 150, top: 0, bottom: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 14 }}>
        <FadeUp delay={4} distance={40}>
          <div style={{ fontSize: 124, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 1 }}>Readable by agents.</div>
        </FadeUp>
        <FadeUp delay={24} distance={40}>
          <div style={{ fontSize: 124, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 1, color: C.yellow }}>Governed by Valio Aimo.</div>
        </FadeUp>
        <div style={{ display: "flex", alignItems: "center", gap: 28, marginTop: 70, opacity: m, transform: `translateY(${(1 - m) * 20}px)` }}>
          <Logo size={104} arrow={arrow} />
          <div style={{ fontSize: 50, fontWeight: 700, letterSpacing: "-0.03em", lineHeight: 1.1 }}>
            Agent Dairy
            <div style={{ fontSize: 30, color: C.railText, fontWeight: 500, letterSpacing: 0, marginTop: 4 }}>{CLIENT_URL}</div>
          </div>
          <div style={{ marginLeft: 30 }}>
            <PoweredByGemini size={26} />
          </div>
        </div>
        <FadeUp delay={84}>
          <div style={{ fontSize: 24, color: "#a9c5eb", marginTop: 28 }}>Junction 2026 · Valio Aimo Trusted Trade Agents</div>
        </FadeUp>
      </div>
    </NavyBackdrop>
  );
};
