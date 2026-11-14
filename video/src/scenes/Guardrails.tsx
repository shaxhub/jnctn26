import React from "react";
import { Cross, Headline, Kicker, PageBackdrop, Tag, Tone, useEnter } from "../components/ui";
import { C, MONO } from "../theme";

// app/evals/cases.jsonl (hospital_allergen_substitution), ADR 0005, and the rules_fallback path in docs/aimo-approval.md.
const CASES: { who: string; tries: string; verdict: string; why: string; rule: string; tone: Tone; bg: string; fg: string }[] = [
  {
    who: "Hospital ward kitchen",
    tries: "The gluten-free oat drink is sold out. The listed substitute contains gluten.",
    verdict: "Rejected",
    why: "Blocked allergen for a coeliac ward. No override.",
    rule: "forbidden_allergen",
    tone: "red",
    bg: C.redBg,
    fg: C.red,
  },
  {
    who: "Any AI agent",
    tries: "Tries to approve its own pending order.",
    verdict: "Impossible",
    why: "Agents get no approval tool. Approval only exists in the Aimo app.",
    rule: "no MCP tool",
    tone: "red",
    bg: C.redBg,
    fg: C.red,
  },
  {
    who: "Gemini is unreachable",
    tries: "The review request times out.",
    verdict: "Rules decide",
    why: "The code checks still run, and the receipt records the fallback.",
    rule: "rules_fallback",
    tone: "navy",
    bg: C.pale,
    fg: C.navy,
  },
];

const CaseCard: React.FC<{ c: (typeof CASES)[number]; delay: number }> = ({ c, delay }) => {
  const p = useEnter(delay);
  const v = useEnter(delay + 30, 12);
  return (
    <div
      style={{
        flex: 1,
        background: C.white,
        borderRadius: 22,
        border: `1px solid ${C.line}`,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        opacity: p,
        transform: `translateY(${(1 - p) * 50}px)`,
        boxShadow: "0 18px 40px rgba(11,36,64,0.08)",
      }}
    >
      <div style={{ padding: "30px 32px", flex: 1 }}>
        <div style={{ fontSize: 21, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: C.muted }}>{c.who}</div>
        <div style={{ fontSize: 44, fontWeight: 600, marginTop: 18, lineHeight: 1.24, letterSpacing: "-0.015em" }}>{c.tries}</div>
      </div>
      <div style={{ background: c.bg, padding: "24px 32px", opacity: v, transform: `translateY(${(1 - v) * 16}px)`, minHeight: 170 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {c.tone === "red" ? <Cross size={32} /> : null}
          <span style={{ fontWeight: 700, fontSize: 36, color: c.fg }}>{c.verdict}</span>
          <Tag tone={c.tone} size={17} mono style={{ marginLeft: "auto", background: "white", fontFamily: MONO }}>
            {c.rule}
          </Tag>
        </div>
        <div style={{ fontSize: 29, color: c.fg, marginTop: 12, lineHeight: 1.35 }}>{c.why}</div>
      </div>
    </div>
  );
};

export const Guardrails: React.FC = () => (
  <PageBackdrop>
    <div style={{ position: "absolute", left: 110, top: 80, right: 110 }}>
      <Kicker color={C.red}>Guardrails</Kicker>
      <div style={{ height: 14 }} />
      <Headline size={70}>
        The agent has no authority. <span style={{ color: C.blue }}>The gateway does.</span>
      </Headline>
    </div>
    <div style={{ position: "absolute", left: 110, right: 110, top: 300, bottom: 90, display: "flex", gap: 28 }}>
      {CASES.map((c, i) => (
        <CaseCard key={c.rule} c={c} delay={20 + i * 56} />
      ))}
    </div>
  </PageBackdrop>
);
