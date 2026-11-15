import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";

/** Numbered caption pill under the screen; shows the latest caption whose start frame has passed. */
export const CaptionBar: React.FC<{ caps: { t: number; n: string; text: string }[] }> = ({ caps }) => {
  const frame = useCurrentFrame();
  let idx = -1;
  caps.forEach((c, i) => {
    if (frame >= c.t) idx = i;
  });
  if (idx < 0) return null;
  const c = caps[idx];
  const p = interpolate(frame - c.t, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 22, display: "flex", justifyContent: "center" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 18,
          background: C.navy,
          color: "white",
          borderRadius: 16,
          padding: "12px 28px 12px 14px",
          fontFamily: FONT,
          fontSize: 33,
          fontWeight: 600,
          letterSpacing: "-0.01em",
          opacity: p,
          transform: `translateY(${(1 - p) * 10}px)`,
          boxShadow: "0 14px 30px rgba(11,36,64,0.25)",
        }}
      >
        <span style={{ width: 46, height: 46, borderRadius: 12, background: C.yellow, color: C.navy, display: "grid", placeItems: "center", fontWeight: 700 }}>{c.n}</span>
        {c.text}
      </div>
    </div>
  );
};

