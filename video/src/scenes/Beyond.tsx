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
  link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
  key: (
    <>
      <circle cx="8" cy="15" r="4" />
      <path d="M11 12l9-9M17 6l3 3M14 9l2 2" />
    </>
  ),
};

// Features on main as of 15 Nov 2026: ChatGPT OAuth (read-only) and named agent keys (6c7f2f8, 4187518),
// school meal plans (3c127b4), nationwide postcode travel estimates (30c0a39).
const FEATURES: { icon: string; title: string; body: string }[] = [
  { icon: "link", title: "ChatGPT", body: "Orders with an agent key you can revoke" },
  { icon: "key", title: "Agent keys", body: "Named, revocable, in every receipt" },
  { icon: "recipe", title: "Meal plans", body: "Headcount and diet → sourced menu" },
  { icon: "swap", title: "Smart substitutes", body: "Ranked, then checked by the rules" },
  { icon: "drift", title: "Standing orders", body: "Drift flagged before repeating" },
  { icon: "truck", title: "Delivery & CO₂", body: "Travel time for any Finnish postcode" },
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
      <Headline size={70}>Built for real kitchens and the AIs they use.</Headline>
    </div>
    <div style={{ position: "absolute", left: 110, right: 110, top: 320, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 30 }}>
      {FEATURES.map((f, i) => (
        <Tile key={f.title} f={f} i={i} />
      ))}
    </div>
  </PageBackdrop>
);
