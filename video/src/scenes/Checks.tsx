import React from "react";
import { Check, Cross, FadeUp, GeminiText, Hand, Headline, Kicker, PageBackdrop, Sparkle, useEnter, useProgress } from "../components/ui";
import { C, GEMINI } from "../theme";

const STAGES: { n: string; title: React.ReactNode; tag: string; items: string[]; ai?: boolean }[] = [
  { n: "1", title: "Buyer’s rules", tag: "Code", items: ["Spend per order and week", "Blocked allergens", "Hard cap — never approvable"] },
  { n: "2", title: "Warehouse", tag: "Code", items: ["Stock and shelf life", "Picking + transit vs. deadline", "Cold chain and route capacity"] },
  { n: "3", title: "Gemini Decision 1", tag: "AI judgment", ai: true, items: ["Is it what the buyer asked for?", "Is the quantity usual?", "Any instructions aimed at the reviewer?"] },
];

const Stage: React.FC<{ s: (typeof STAGES)[number]; delay: number }> = ({ s, delay }) => {
  const p = useEnter(delay);
  return (
    <div
      style={{
        flex: 1,
        background: s.ai ? C.navy : C.white,
        color: s.ai ? "white" : C.ink,
        borderRadius: 24,
        border: s.ai ? "2px solid transparent" : `1px solid ${C.line}`,
        backgroundImage: s.ai ? `linear-gradient(${C.navy}, ${C.navy}), ${GEMINI.gradient}` : undefined,
        backgroundOrigin: "border-box",
        backgroundClip: s.ai ? "padding-box, border-box" : undefined,
        padding: "30px 34px",
        opacity: p,
        transform: `translateY(${(1 - p) * 40}px)`,
        boxShadow: "0 18px 40px rgba(11,36,64,0.1)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: 14,
            background: s.ai ? "rgba(255,255,255,0.08)" : C.yellow,
            display: "grid",
            placeItems: "center",
            fontSize: 28,
            fontWeight: 700,
            color: s.ai ? "white" : C.navy,
          }}
        >
          {s.ai ? <Sparkle size={30} /> : s.n}
        </div>
        <span
          style={{
            fontSize: 20,
            fontWeight: 700,
            padding: "6px 14px",
            borderRadius: 999,
            background: s.ai ? "rgba(255,255,255,0.1)" : C.pale,
            color: s.ai ? "white" : C.blue,
          }}
        >
          {s.tag}
        </span>
      </div>
      <div style={{ fontSize: 40, fontWeight: 700, letterSpacing: "-0.03em", marginTop: 20 }}>
        {s.ai ? <GeminiText>{s.title}</GeminiText> : s.title}
      </div>
      <div style={{ display: "grid", gap: 12, marginTop: 18 }}>
        {s.items.map((it, i) => (
          <FadeUp key={it} delay={delay + 10 + i * 6} distance={8}>
            <div style={{ fontSize: 26, lineHeight: 1.3, color: s.ai ? C.railText : C.muted, display: "flex", gap: 12 }}>
              <span style={{ color: s.ai ? GEMINI.b : C.yellowDeep, fontWeight: 700 }}>•</span>
              {it}
            </div>
          </FadeUp>
        ))}
      </div>
    </div>
  );
};

const Arrow: React.FC<{ delay: number }> = ({ delay }) => {
  const p = useProgress(delay, delay + 12);
  return (
    <svg width={50} height={40} viewBox="0 0 50 40" style={{ alignSelf: "center", flex: "none", opacity: p }}>
      <path d={`M4 20 H${4 + 36 * p}`} stroke={C.navy} strokeWidth={5} strokeLinecap="round" />
      <path d="M32 9 L45 20 L32 31" fill="none" stroke={C.navy} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" opacity={p > 0.9 ? 1 : 0} />
    </svg>
  );
};

const Outcome: React.FC<{ icon: React.ReactNode; text: string; result: string; bg: string; fg: string; delay: number }> = ({
  icon,
  text,
  result,
  bg,
  fg,
  delay,
}) => (
  <FadeUp delay={delay} style={{ flex: 1 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 16, background: bg, borderRadius: 18, padding: "18px 24px" }}>
      {icon}
      <div style={{ fontSize: 25, color: fg }}>
        {text} <b>→ {result}</b>
      </div>
    </div>
  </FadeUp>
);

export const Checks: React.FC = () => (
  <PageBackdrop>
    <div style={{ position: "absolute", left: 110, top: 70 }}>
      <Kicker>Before any order is placed</Kicker>
      <div style={{ height: 14 }} />
      <Headline size={70}>Every order passes three checks.</Headline>
    </div>
    <div style={{ position: "absolute", left: 110, right: 110, top: 270, display: "flex", gap: 14 }}>
      <Stage s={STAGES[0]} delay={18} />
      <Arrow delay={44} />
      <Stage s={STAGES[1]} delay={50} />
      <Arrow delay={76} />
      <Stage s={STAGES[2]} delay={82} />
    </div>
    <div style={{ position: "absolute", left: 110, right: 110, top: 720, display: "flex", gap: 20 }}>
      <Outcome icon={<Cross size={36} />} text="A hard rule fails" result="rejected" bg={C.redBg} fg={C.red} delay={150} />
      <Outcome icon={<Hand size={36} />} text="Anything unsure" result="a person decides" bg={C.amberBg} fg={C.amber} delay={162} />
      <Outcome icon={<Check size={36} />} text="All clear" result="confirmed" bg={C.greenBg} fg={C.green} delay={174} />
    </div>
    <div style={{ position: "absolute", left: 110, right: 110, bottom: 70, display: "flex", justifyContent: "center" }}>
      <FadeUp delay={220}>
        <div style={{ fontSize: 54, fontWeight: 700, letterSpacing: "-0.035em" }}>
          Code does the maths. <GeminiText>Gemini judges the meaning.</GeminiText>
        </div>
      </FadeUp>
    </div>
  </PageBackdrop>
);
