import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, FONT, GEMINI, MONO } from "../theme";

/** Spring progress 0→1 starting at `delay` frames. */
export const useEnter = (delay = 0, damping = 200) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delay, fps, config: { damping } });
};

/** Eased progress between two frames, clamped. */
export const useProgress = (from: number, to: number) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [from, to], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
};

/** Piecewise keyframes → value, clamped and eased. */
export const useKeyframes = (frames: number[], values: number[]) => {
  const frame = useCurrentFrame();
  return interpolate(frame, frames, values, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.45, 0, 0.2, 1),
  });
};

export const FadeUp: React.FC<{
  delay?: number;
  distance?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ delay = 0, distance = 36, style, children }) => {
  const p = useEnter(delay);
  return (
    <div style={{ opacity: p, transform: `translateY(${(1 - p) * distance}px)`, ...style }}>{children}</div>
  );
};

/** Pops in with a slight overshoot — for stamps and verdicts. */
export const Pop: React.FC<{ delay: number; style?: React.CSSProperties; children: React.ReactNode; rotate?: number }> = ({
  delay,
  style,
  children,
  rotate = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 11, stiffness: 180 } });
  const visible = frame >= delay;
  return (
    <div
      style={{
        opacity: visible ? Math.min(1, p * 1.6) : 0,
        transform: `scale(${visible ? 1.5 - 0.5 * p : 1.5}) rotate(${rotate}deg)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Typewriter: React.FC<{
  text: string;
  start: number;
  cps?: number;
  style?: React.CSSProperties;
  caret?: boolean;
}> = ({ text, start, cps = 32, style, caret = true }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const chars = Math.max(0, Math.floor(((frame - start) / fps) * cps));
  const done = chars >= text.length;
  const blink = Math.floor(frame / 15) % 2 === 0;
  return (
    <span style={style}>
      {text.slice(0, chars)}
      {caret && (!done || blink) ? (
        <span
          style={{
            display: "inline-block",
            width: "0.07em",
            height: "1em",
            marginLeft: 3,
            verticalAlign: "-0.12em",
            background: "currentColor",
          }}
        />
      ) : null}
    </span>
  );
};

export type Tone = "navy" | "green" | "amber" | "red" | "yellow" | "ghost" | "blue";

const TONES: Record<Tone, { bg: string; fg: string }> = {
  navy: { bg: "#e7eef8", fg: C.navy },
  blue: { bg: "#e5eef8", fg: C.blue },
  green: { bg: C.greenBg, fg: C.green },
  amber: { bg: C.amberBg, fg: C.amber },
  red: { bg: C.redBg, fg: C.red },
  yellow: { bg: C.yellow, fg: C.navy },
  ghost: { bg: "rgba(255,255,255,0.1)", fg: C.railText },
};

export const Tag: React.FC<{
  tone?: Tone;
  mono?: boolean;
  size?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ tone = "navy", mono = false, size = 22, style, children }) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      padding: `${size * 0.28}px ${size * 0.6}px`,
      borderRadius: size * 0.35,
      background: TONES[tone].bg,
      color: TONES[tone].fg,
      fontFamily: mono ? MONO : FONT,
      fontWeight: 700,
      fontSize: size,
      whiteSpace: "nowrap",
      ...style,
    }}
  >
    {children}
  </span>
);

/** Navy backdrop with the arcs from the Aimo operations hero. */
export const NavyBackdrop: React.FC<{ children?: React.ReactNode; ringX?: number; ringY?: number }> = ({
  children,
  ringX = 1560,
  ringY = -360,
}) => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 80) * 16;
  return (
    <AbsoluteFill style={{ background: C.navy, fontFamily: FONT, overflow: "hidden", color: "white" }}>
      <div
        style={{
          position: "absolute",
          width: 980,
          height: 980,
          left: ringX - 490 + drift,
          top: ringY,
          borderRadius: "50%",
          border: `56px solid ${C.ring}`,
          boxShadow: `0 0 0 34px #17336f`,
          opacity: 0.55,
        }}
      />
      {children}
    </AbsoluteFill>
  );
};

export const PageBackdrop: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: C.page, fontFamily: FONT, color: C.ink }}>{children}</AbsoluteFill>
);

export const Kicker: React.FC<{ children: React.ReactNode; color?: string; delay?: number }> = ({
  children,
  color = C.blue,
  delay = 0,
}) => (
  <FadeUp delay={delay} distance={14}>
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      <span style={{ width: 8, height: 34, borderRadius: 4, background: C.yellow }} />
      <span style={{ fontSize: 26, fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase", color }}>
        {children}
      </span>
    </div>
  </FadeUp>
);

export const Headline: React.FC<{
  children: React.ReactNode;
  size?: number;
  color?: string;
  delay?: number;
  style?: React.CSSProperties;
}> = ({ children, size = 72, color = C.ink, delay = 0, style }) => (
  <FadeUp delay={delay}>
    <h1 style={{ margin: 0, fontSize: size, lineHeight: 1.05, letterSpacing: "-0.04em", fontWeight: 700, color, ...style }}>
      {children}
    </h1>
  </FadeUp>
);

/** Bottom caption. Keep to ~12 words so it can be read in time. */
export const Caption: React.FC<{ children: React.ReactNode; delay?: number; dark?: boolean }> = ({
  children,
  delay = 0,
  dark = false,
}) => (
  <div style={{ position: "absolute", left: 0, right: 0, bottom: 50, display: "flex", justifyContent: "center" }}>
    <FadeUp delay={delay} distance={18}>
      <div
        style={{
          fontSize: 38,
          fontWeight: 600,
          letterSpacing: "-0.015em",
          color: dark ? "white" : C.ink,
          background: dark ? "rgba(11,36,64,0.92)" : "rgba(255,255,255,0.96)",
          padding: "16px 36px",
          borderRadius: 18,
          borderLeft: `8px solid ${C.yellow}`,
          boxShadow: "0 14px 34px rgba(11,36,64,0.16)",
        }}
      >
        {children}
      </div>
    </FadeUp>
  </div>
);

export const Check: React.FC<{ size?: number; color?: string }> = ({ size = 26, color = C.green }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flex: "none" }}>
    <circle cx="12" cy="12" r="11" fill={color} />
    <path d="M7 12.5l3.2 3.2L17 9" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const Cross: React.FC<{ size?: number; color?: string }> = ({ size = 26, color = C.red }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flex: "none" }}>
    <circle cx="12" cy="12" r="11" fill={color} />
    <path d="M8 8l8 8M16 8l-8 8" stroke="white" strokeWidth="2.4" strokeLinecap="round" />
  </svg>
);

export const Hand: React.FC<{ size?: number; color?: string }> = ({ size = 26, color = C.amber }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flex: "none" }}>
    <circle cx="12" cy="12" r="11" fill={color} />
    <circle cx="12" cy="9" r="3" fill="white" />
    <path d="M6.5 18c1-3 3-4.4 5.5-4.4s4.5 1.4 5.5 4.4" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

export const Sparkle: React.FC<{ size?: number; gradient?: boolean; color?: string }> = ({
  size = 28,
  gradient = true,
  color = C.blue,
}) => {
  const id = React.useId().replace(/[^a-zA-Z0-9]/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: "none" }}>
      <defs>
        <linearGradient id={`g-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={GEMINI.a} />
          <stop offset="0.55" stopColor={GEMINI.b} />
          <stop offset="1" stopColor={GEMINI.c} />
        </linearGradient>
      </defs>
      <path
        d="M12 1.5c.6 5.4 4.1 9.4 10.5 10.5-6.4 1.1-9.9 5.1-10.5 10.5-.6-5.4-4.1-9.4-10.5-10.5C7.9 10.9 11.4 6.9 12 1.5Z"
        fill={gradient ? `url(#g-${id})` : color}
      />
    </svg>
  );
};

/** Gradient text for AI elements. */
export const GeminiText: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <span
    style={{
      backgroundImage: GEMINI.gradient,
      WebkitBackgroundClip: "text",
      backgroundClip: "text",
      color: "transparent",
      ...style,
    }}
  >
    {children}
  </span>
);

export const PoweredByGemini: React.FC<{ size?: number; dark?: boolean }> = ({ size = 26, dark = true }) => (
  <div
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: size * 0.45,
      padding: `${size * 0.4}px ${size * 0.8}px`,
      borderRadius: 999,
      background: dark ? "rgba(255,255,255,0.08)" : C.white,
      border: `1px solid ${dark ? "rgba(255,255,255,0.18)" : C.line}`,
      fontSize: size,
      fontWeight: 600,
      color: dark ? C.railText : C.muted,
    }}
  >
    <Sparkle size={size * 1.05} />
    Powered by <GeminiText style={{ fontWeight: 700 }}>Gemini</GeminiText>
  </div>
);

export const fmtEur = (n: number) =>
  "€" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
