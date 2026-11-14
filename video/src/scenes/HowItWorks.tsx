import React from "react";
import { useCurrentFrame } from "remotion";
import { Logo } from "../components/Logo";
import { Caption, FadeUp, GeminiText, Headline, Kicker, PageBackdrop, Sparkle, useEnter, useProgress } from "../components/ui";
import { C } from "../theme";

type Box = { x: number; y: number; w: number; h: number; title: string; sub: React.ReactNode };

const LEFT: Box[] = [
  { x: 100, y: 330, w: 470, h: 150, title: "Kitchen workspace", sub: <>Plain requests, read by <GeminiText style={{ fontWeight: 700 }}>Gemini</GeminiText></> },
  { x: 100, y: 520, w: 470, h: 150, title: "Any AI agent", sub: "Open standards: MCP or REST" },
  { x: 100, y: 710, w: 470, h: 150, title: "Aimo operations", sub: "People review the exceptions" },
];
const CORE = { x: 720, y: 300, w: 520, h: 590 };
const RIGHT: Box = { x: 1390, y: 500, w: 430, h: 190, title: "Valio Aimo", sub: "Catalog, live prices and stock" };

const MODULES: { label: React.ReactNode; ai?: boolean }[] = [
  { label: "Search & live offers" },
  { label: "Signed quotes" },
  { label: "Buyer’s rules" },
  { label: "Warehouse checks" },
  { label: "Gemini Decision 1 review", ai: true },
  { label: "Receipts for every step" },
];

const NodeBox: React.FC<{ b: Box; delay: number; dark?: boolean }> = ({ b, delay, dark }) => {
  const p = useEnter(delay);
  return (
    <div
      style={{
        position: "absolute",
        left: b.x,
        top: b.y,
        width: b.w,
        height: b.h,
        background: dark ? C.yellow : C.white,
        borderRadius: 18,
        border: `1px solid ${dark ? C.yellowDeep : C.line}`,
        padding: "28px 30px",
        opacity: p,
        transform: `translateY(${(1 - p) * 24}px)`,
        boxShadow: "0 14px 34px rgba(11,36,64,0.08)",
      }}
    >
      <div style={{ fontSize: 38, fontWeight: 700, letterSpacing: "-0.02em", color: C.ink }}>{b.title}</div>
      <div style={{ fontSize: 26, color: dark ? C.navy : C.muted, marginTop: 8 }}>{b.sub}</div>
    </div>
  );
};

const Wire: React.FC<{ from: [number, number]; to: [number, number]; start: number }> = ({ from, to, start }) => {
  const frame = useCurrentFrame();
  const draw = useProgress(start, start + 20);
  const mx = (from[0] + to[0]) / 2;
  const d = `M ${from[0]} ${from[1]} C ${mx} ${from[1]}, ${mx} ${to[1]}, ${to[0]} ${to[1]}`;
  const t = (((frame - start) % 45) + 45) % 45 / 45;
  const bez = (a: number, b: number, c: number, e: number, s: number) =>
    (1 - s) ** 3 * a + 3 * (1 - s) ** 2 * s * b + 3 * (1 - s) * s ** 2 * c + s ** 3 * e;
  return (
    <g>
      <path d={d} fill="none" stroke={C.blue} strokeWidth={4} strokeOpacity={0.35} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
      {draw >= 1 ? <circle cx={bez(from[0], mx, mx, to[0], t)} cy={bez(from[1], from[1], to[1], to[1], t)} r={8} fill={C.yellowDeep} /> : null}
    </g>
  );
};

export const HowItWorks: React.FC = () => {
  const core = useEnter(34);
  return (
    <PageBackdrop>
      <div style={{ position: "absolute", left: 100, top: 76 }}>
        <Kicker>How it works</Kicker>
        <div style={{ height: 14 }} />
        <Headline size={70}>Three ways in. One set of rules.</Headline>
      </div>

      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {LEFT.map((b, i) => (
          <Wire key={b.title} from={[b.x + b.w, b.y + b.h / 2]} to={[CORE.x, CORE.y + 150 + i * 150]} start={50 + i * 6} />
        ))}
        <Wire from={[CORE.x + CORE.w, CORE.y + CORE.h / 2]} to={[RIGHT.x, RIGHT.y + RIGHT.h / 2]} start={80} />
      </svg>

      {LEFT.map((b, i) => (
        <NodeBox key={b.title} b={b} delay={10 + i * 8} />
      ))}
      <NodeBox b={RIGHT} delay={70} dark />

      <div
        style={{
          position: "absolute",
          left: CORE.x,
          top: CORE.y,
          width: CORE.w,
          height: CORE.h,
          background: C.navy,
          borderRadius: 28,
          padding: 32,
          color: "white",
          opacity: core,
          transform: `scale(${0.92 + core * 0.08})`,
          boxShadow: "0 30px 70px rgba(11,36,64,0.3)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Logo size={56} />
          <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: "-0.02em" }}>Agent Dairy gateway</div>
        </div>
        <div style={{ display: "grid", gap: 12, marginTop: 26 }}>
          {MODULES.map((m, i) => (
            <FadeUp key={i} delay={48 + i * 6} distance={12}>
              <div
                style={{
                  background: m.ai ? "rgba(145,119,199,0.18)" : C.navyLift,
                  border: m.ai ? "1px solid rgba(145,119,199,0.7)" : "1px solid transparent",
                  borderRadius: 12,
                  padding: "13px 20px",
                  fontSize: 28,
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                }}
              >
                {m.ai ? <Sparkle size={24} /> : <span style={{ width: 11, height: 11, borderRadius: 6, background: C.yellow }} />}
                {m.ai ? <GeminiText>{m.label}</GeminiText> : m.label}
              </div>
            </FadeUp>
          ))}
        </div>
      </div>

      <Caption delay={130}>Browser, agent or Aimo — the same checks, every time.</Caption>
    </PageBackdrop>
  );
};
