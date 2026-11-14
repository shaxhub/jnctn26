import React from "react";
import { Headline, Kicker, PageBackdrop, useEnter } from "../components/ui";
import { C } from "../theme";

const ICON: Record<string, React.ReactNode> = {
  recipe: <path d="M5 10h14v3a7 7 0 0 1-14 0v-3ZM9 6c0-1.5 1-2 1-3M13 6c0-1.5 1-2 1-3M3 10h18" />,
  season: (
    <>
      <path d="M20 4C13 4 5 7 5 15c0 3 2 5 5 5 8 0 10-8 10-16Z" />
      <path d="M4 21c2-6 6-9 11-11" />
    </>
  ),
  drift: <path d="M3 17l5-5 4 3 8-8M15 7h5v5" />,
  swap: <path d="M4 8h13l-3-3M20 16H7l3 3" />,
  truck: (
    <>
      <path d="M2 6h11v10H2zM13 10h5l3 3v3h-8" />
      <circle cx="6" cy="18" r="2" />
      <circle cx="17" cy="18" r="2" />
    </>
  ),
  chat: <path d="M4 5h16v11H9l-5 4V5Z" />,
};

const FEATURES: { icon: string; title: string; body: string }[] = [
  { icon: "recipe", title: "Recipe → order", body: "Paste a recipe, get it sourced" },
  { icon: "season", title: "Seasonal picks", body: "What’s in season for your date" },
  { icon: "drift", title: "Standing orders", body: "Drift flagged before repeating" },
  { icon: "swap", title: "Smart substitutes", body: "Ranked, then checked by the rules" },
  { icon: "truck", title: "Reliability & CO₂", body: "Shown beside every price" },
  { icon: "chat", title: "One thread per order", body: "Buyer, agent and Aimo together" },
];

const Tile: React.FC<{ f: (typeof FEATURES)[number]; i: number }> = ({ f, i }) => {
  const p = useEnter(14 + i * 7);
  return (
    <div
      style={{
        background: C.white,
        border: `1px solid ${C.line}`,
        borderRadius: 22,
        padding: "48px 40px",
        display: "flex",
        gap: 30,
        alignItems: "center",
        opacity: p,
        transform: `translateY(${(1 - p) * 34}px)`,
      }}
    >
      <div style={{ width: 104, height: 104, borderRadius: 24, background: C.yellow, display: "grid", placeItems: "center", flex: "none" }}>
        <svg width={56} height={56} viewBox="0 0 24 24" fill="none" stroke={C.navy} strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
          {ICON[f.icon]}
        </svg>
      </div>
      <div>
        <div style={{ fontSize: 44, fontWeight: 700, letterSpacing: "-0.025em" }}>{f.title}</div>
        <div style={{ fontSize: 31, color: C.muted, marginTop: 8, lineHeight: 1.3 }}>{f.body}</div>
      </div>
    </div>
  );
};

export const Beyond: React.FC = () => (
  <PageBackdrop>
    <div style={{ position: "absolute", left: 110, top: 80 }}>
      <Kicker>Beyond the core</Kicker>
      <div style={{ height: 14 }} />
      <Headline size={70}>Built for how kitchens actually plan.</Headline>
    </div>
    <div style={{ position: "absolute", left: 110, right: 110, top: 320, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 30 }}>
      {FEATURES.map((f, i) => (
        <Tile key={f.title} f={f} i={i} />
      ))}
    </div>
  </PageBackdrop>
);
