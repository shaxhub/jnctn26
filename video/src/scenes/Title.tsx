import React from "react";
import { Logo } from "../components/Logo";
import { FadeUp, NavyBackdrop, PoweredByGemini, useEnter, useProgress } from "../components/ui";
import { C } from "../theme";

export const Title: React.FC = () => {
  const tile = useEnter(0, 16);
  const draw = useProgress(6, 40);
  const arrow = useProgress(40, 54);
  return (
    <NavyBackdrop ringX={1650} ringY={-420}>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 38 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 44 }}>
          <div style={{ transform: `scale(${0.6 + tile * 0.4})`, opacity: tile }}>
            <Logo size={190} draw={draw} arrow={arrow} />
          </div>
          <FadeUp delay={30} distance={0} style={{ transform: `translateX(${(1 - useEnter(30)) * -24}px)` }}>
            <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.055em", lineHeight: 1 }}>Agent Dairy</div>
          </FadeUp>
        </div>
        <FadeUp delay={52}>
          <div style={{ fontSize: 46, fontWeight: 500, color: "#dfe9ff", textAlign: "center" }}>
            The trusted gateway between AI purchasing agents and <span style={{ color: C.yellow, fontWeight: 700 }}>Valio Aimo</span>.
          </div>
        </FadeUp>
        <FadeUp delay={72}>
          <PoweredByGemini size={28} />
        </FadeUp>
      </div>
    </NavyBackdrop>
  );
};
