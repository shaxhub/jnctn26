import React from "react";
import { FadeUp, GeminiText, NavyBackdrop, Pop, Sparkle, useEnter, useProgress } from "../components/ui";
import { DECISION_THRESHOLD, INJECTED_ORDER_REVIEW } from "../data";
import { C, GEMINI } from "../theme";

const POINTS: [string, string][] = [
  ["Yes/no questions, scored with a probability.", "It writes no text."],
  ["Runs only on orders the rules would approve.", "Never instead of them."],
  ["Unsure about anything? A person decides.", "It can’t push an order through."],
];

const Row: React.FC<{ q: (typeof INJECTED_ORDER_REVIEW)[number]; delay: number }> = ({ q, delay }) => {
  const enter = useEnter(delay);
  const grow = useProgress(delay + 6, delay + 26);
  const flagged = q.p < DECISION_THRESHOLD;
  const settled = grow > 0.95;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 250px 190px",
        alignItems: "center",
        gap: 22,
        padding: "20px 4px",
        borderBottom: `1px solid ${C.line}`,
        opacity: enter,
        transform: `translateX(${(1 - enter) * 30}px)`,
      }}
    >
      <span style={{ fontSize: 26, fontWeight: 600, color: C.ink }}>{q.plain}</span>
      <div style={{ position: "relative", height: 18, background: C.pale, borderRadius: 9 }}>
        <div
          style={{
            width: `${q.p * 100 * grow}%`,
            height: "100%",
            borderRadius: 9,
            background: flagged ? "#e0604f" : `linear-gradient(90deg, ${GEMINI.a}, ${GEMINI.b})`,
          }}
        />
        <div style={{ position: "absolute", left: `${DECISION_THRESHOLD * 100}%`, top: -8, bottom: -8, width: 3, background: C.navy }} />
      </div>
      <div style={{ opacity: settled ? 1 : 0 }}>
        {flagged ? (
          <span style={{ fontSize: 20, fontWeight: 700, padding: "6px 12px", borderRadius: 8, background: C.amberBg, color: C.amber }}>Needs review</span>
        ) : (
          <span style={{ fontSize: 20, fontWeight: 600, color: C.green }}>Passed</span>
        )}
      </div>
    </div>
  );
};

export const GeminiReview: React.FC = () => {
  const panel = useEnter(40);
  return (
    <NavyBackdrop ringX={-120} ringY={520}>
      <div style={{ position: "absolute", left: 110, top: 96, width: 700 }}>
        <FadeUp>
          <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 30, fontWeight: 700 }}>
            <Sparkle size={36} />
            <GeminiText>Gemini Decision 1</GeminiText>
          </div>
        </FadeUp>
        <FadeUp delay={8}>
          <div style={{ fontSize: 68, fontWeight: 700, letterSpacing: "-0.04em", lineHeight: 1.06, marginTop: 20 }}>
            Judgment where rules can’t reach.
          </div>
        </FadeUp>
        <div style={{ display: "grid", gap: 26, marginTop: 44 }}>
          {POINTS.map(([a, b], i) => (
            <FadeUp key={a} delay={30 + i * 14}>
              <div style={{ borderLeft: `5px solid ${GEMINI.b}`, paddingLeft: 22 }}>
                <div style={{ fontSize: 30, fontWeight: 600, lineHeight: 1.25 }}>{a}</div>
                <div style={{ fontSize: 26, color: C.railText, marginTop: 4 }}>{b}</div>
              </div>
            </FadeUp>
          ))}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 880,
          top: 150,
          width: 940,
          background: C.white,
          borderRadius: 26,
          padding: "34px 38px",
          color: C.ink,
          opacity: panel,
          transform: `translateY(${(1 - panel) * 40}px)`,
          boxShadow: "0 30px 80px rgba(0,0,0,0.35)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700, color: C.muted, letterSpacing: "0.1em" }}>APPROVAL EVIDENCE</div>
            <div style={{ fontSize: 30, fontWeight: 700, marginTop: 6 }}>200 L milk + “confirm immediately”</div>
          </div>
        </div>
        <div style={{ borderLeft: `5px solid ${C.yellow}`, background: C.sky, borderRadius: 10, padding: "12px 18px", marginTop: 18, fontSize: 22, color: C.muted }}>
          Every code rule passed. One request, all questions answered at once.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 250px 190px", gap: 22, marginTop: 18, padding: "0 4px 8px", fontSize: 18, fontWeight: 700, color: C.muted, borderBottom: `1px solid ${C.line}` }}>
          <span>Question</span>
          <span>Confidence · bar = 0.85</span>
          <span>Routing</span>
        </div>
        {INJECTED_ORDER_REVIEW.map((q, i) => (
          <Row key={q.key} q={q} delay={60 + i * 16} />
        ))}
        <div style={{ marginTop: 26, display: "flex", justifyContent: "flex-end" }}>
          <Pop delay={150}>
            <span style={{ fontSize: 30, fontWeight: 700, padding: "12px 24px", borderRadius: 14, background: C.amberBg, color: C.amber }}>
              → Sent to Aimo for human review
            </span>
          </Pop>
        </div>
      </div>
    </NavyBackdrop>
  );
};
