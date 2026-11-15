import React from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { Logo } from "../components/Logo";
import { FadeUp, NavyBackdrop, PoweredByGemini, useEnter, useProgress } from "../components/ui";
import { C, CLIENT_URL, FONT } from "../theme";
import { CaptionBar } from "./Caption";
import { ChatGPT, CHAT_FRAMES } from "./ChatGPT";
import { at, camOn, FULL, Screen, Step, timeline } from "./Screen";

const ADMIN_URL = `${CLIENT_URL}/admin/`;
const range = (prefix: string, from: number, to: number, by: number, f: number, extra: Partial<Step> = {}): Step[] => {
  const out: Step[] = [];
  for (let n = from; n <= to; n += by) out.push({ shot: `${prefix}-${n}`, f, ...extra });
  return out;
};

// Part 1: buyer signs in, asks for milk, submits the draft; Aimo approves; buyer creates a ChatGPT key.
const PART1: Step[] = [
  { shot: "login", f: 24, cam: { cx: 720, cy: 270, s: 1.5 }, cur: at("login", "user"), url: CLIENT_URL },
  ...range("user", 1, 4, 1, 4),
  { shot: "user-4", f: 8, cur: at("login", "pass") },
  ...range("pass", 2, 14, 2, 2),
  { shot: "signin-hover", f: 16, cur: at("login", "signIn"), click: true },
  { shot: "home", f: 36, cam: FULL, cur: null },
  { shot: "home", f: 22, cam: camOn("home", "card", 1.35, 0, 20), cur: at("home", "ask", -200, -40) },
  ...range("ask", 2, 50, 2, 3),
  { shot: "ask-50", f: 8, cur: at("home", "post") },
  ...range("post", 1, 5, 1, 3),
  { shot: "build-hover", f: 16, cur: at("home", "build"), click: true },
  ...range("busy", 0, 3, 1, 16, { cur: null }),
  { shot: "result", f: 120, cam: { cx: 1215, cy: 430, s: 1.45 } },
  ...range("scroll", 24, 360, 24, 2, { cam: FULL }),
  { shot: "result-scrolled", f: 110, cam: { cx: 650, cy: 470, s: 1.35 } },
  { shot: "result-scrolled", f: 110, cam: { cx: 650, cy: 700, s: 1.45 } },
  { shot: "drafts-hover", f: 18, cam: FULL, cur: [101, 227], click: true },
  { shot: "drafts", f: 45, cam: { cx: 757, cy: 520, s: 1.4 }, cur: at("drafts", "addr", -100) },
  ...range("addr", 2, 24, 2, 2),
  { shot: "addr-25", f: 4 },
  { shot: "submit-hover", f: 16, cur: at("drafts", "submit"), click: true },
  { shot: "submitted-empty", f: 10, cam: FULL },
  { shot: "requests-hover", f: 16, cur: [126, 276], click: true },
  { shot: "requests-pending", f: 100, cam: camOn("requests-pending", "row", 1.6), cur: null },
  { shot: "admin-home", f: 40, cam: FULL, cur: at("admin-home", "panel"), url: CLIENT_URL },
  { shot: "panel-hover", f: 14, cur: at("admin-home", "panel"), click: true },
  { shot: "queue", f: 50, cam: camOn("queue", "row", 1.5), cur: at("queue", "ticket"), url: ADMIN_URL },
  { shot: "ticket-hover", f: 12, cur: at("queue", "ticket"), click: true },
  { shot: "ticket", f: 120, cam: { cx: 720, cy: 330, s: 1.35 }, cur: at("ticket", "note", -200) },
  ...range("note", 3, 33, 3, 2),
  { shot: "approve-hover", f: 16, cur: at("ticket", "approve"), click: true },
  { shot: "approved", f: 130, cam: { cx: 720, cy: 330, s: 1.4 }, cur: null },
  { shot: "settings", f: 50, cam: { cx: 844, cy: 520, s: 1.3 }, cur: at("settings", "agentName", -380), url: CLIENT_URL },
  ...range("agentname", 1, 7, 1, 3),
  { shot: "agentname-7", f: 12, cur: at("settings", "allow"), click: true },
  { shot: "allow-checked", f: 6 },
  { shot: "create-hover", f: 16, cur: at("settings", "create"), click: true },
  { shot: "key-created", f: 80, cam: { cx: 844, cy: 600, s: 1.3 }, cur: null },
];

// Part 3: the ChatGPT order in Aimo, confirmed with Gemini Decision 1 evidence.
const PART3: Step[] = [
  { shot: "queue-all", f: 65, cam: camOn("queue-all", "row", 1.5), cur: at("queue-all", "ticket"), url: ADMIN_URL },
  { shot: "butter-hover", f: 14, cur: at("queue-all", "ticket"), click: true },
  { shot: "butter", f: 45, cam: { cx: 720, cy: 330, s: 1.35 }, cur: null },
  { shot: "butter-evidence", f: 210, cam: { cx: 721, cy: 480, s: 1.55 } },
];

const T1 = timeline(PART1);
const T3 = timeline(PART3);

// Captions keyed to the first frame of a shot.
const CAPS1: [string, string, string][] = [
  ["login", "1", "The hotel kitchen’s buyer signs in"],
  ["home", "2", "Ask Agent Dairy for what the kitchen needs"],
  ["busy-0", "2", "It reads the request and checks live Valio Aimo prices and stock"],
  ["result", "2", "A signed draft: €1,010.00, just over the €1,000 automatic limit"],
  ["scroll-24", "2", "Order plans ranked on price, delivery reliability and CO₂"],
  ["result-scrolled@2", "2", "Live offers: items past their order cutoff can’t be quoted"],
  ["drafts-hover", "3", "Review the draft and send it to Aimo"],
  ["requests-pending", "3", "Over the limit, so it waits for a person at Aimo"],
  ["admin-home", "4", "At Valio Aimo, an admin opens the admin panel"],
  ["ticket", "4", "The ticket shows the order, the address and why it was held"],
  ["approved", "4", "Approved by a person. Delivery tracking starts."],
  ["settings", "5", "The buyer gives ChatGPT an agent key that may submit orders"],
];
const CAPS3: [string, string, string][] = [
  ["queue-all", "6", "The ChatGPT order reaches Aimo already confirmed"],
  ["butter-evidence", "6", "Under the limit, and Gemini Decision 1 flagged nothing. No human needed."],
];

const capsAt = (tl: ReturnType<typeof timeline>, caps: [string, string, string][]) =>
  caps.map(([key, n, text]) => {
    // "shot@2" means the second step that shows this shot.
    const [shot, nth = "1"] = key.split("@");
    const i = tl.steps.map((s, j) => (s.shot === shot ? j : -1)).filter((j) => j >= 0)[Number(nth) - 1] ?? -1;
    if (i < 0) throw new Error(`Caption shot ${shot} missing`);
    return { t: tl.starts[i], n, text };
  });

const INTRO = 75;
const OUTRO = 150;
const FADE = 10;
export const DEMO_SEGMENTS = [INTRO, T1.total, CHAT_FRAMES, T3.total, OUTRO];
export const DEMO_FRAMES = DEMO_SEGMENTS.reduce((a, b) => a + b, 0);

const SCREEN_W = 1600;

const AppPart: React.FC<{ tl: ReturnType<typeof timeline>; caps: [string, string, string][] }> = ({ tl, caps }) => (
  <AbsoluteFill style={{ background: "#e9eef5" }}>
    <div style={{ position: "absolute", left: (1920 - SCREEN_W) / 2, top: 18 }}>
      <Screen tl={tl} width={SCREEN_W} urlFallback={CLIENT_URL} />
    </div>
    <CaptionBar caps={capsAt(tl, caps)} />
  </AbsoluteFill>
);

const Intro: React.FC = () => {
  const draw = useProgress(0, 24);
  const arrow = useProgress(22, 34);
  return (
    <NavyBackdrop ringX={1650} ringY={-420}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 26, fontFamily: FONT }}>
        <div style={{ display: "flex", alignItems: "center", gap: 34 }}>
          <Logo size={130} draw={draw} arrow={arrow} />
          <div style={{ fontSize: 110, fontWeight: 700, letterSpacing: "-0.05em", color: "white" }}>Agent Dairy</div>
        </div>
        <FadeUp delay={14}>
          <div style={{ fontSize: 40, color: "#dfe9ff", fontWeight: 500 }}>Product demo · the real app, end to end</div>
        </FadeUp>
      </AbsoluteFill>
    </NavyBackdrop>
  );
};

const Outro: React.FC = () => {
  const m = useEnter(30, 14);
  return (
    <NavyBackdrop ringX={1640} ringY={430}>
      <div style={{ position: "absolute", left: 150, top: 0, bottom: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 12, fontFamily: FONT, color: "white" }}>
        <FadeUp delay={2} distance={30}>
          <div style={{ fontSize: 104, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1 }}>Readable by agents.</div>
        </FadeUp>
        <FadeUp delay={14} distance={30}>
          <div style={{ fontSize: 104, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1, color: C.yellow }}>Governed by Valio Aimo.</div>
        </FadeUp>
        <div style={{ display: "flex", alignItems: "center", gap: 26, marginTop: 56, opacity: m, transform: `translateY(${(1 - m) * 16}px)` }}>
          <Logo size={92} />
          <div style={{ fontSize: 46, fontWeight: 700, letterSpacing: "-0.03em", lineHeight: 1.1 }}>
            Agent Dairy
            <div style={{ fontSize: 28, color: C.railText, fontWeight: 500, letterSpacing: 0, marginTop: 4 }}>{CLIENT_URL}</div>
          </div>
          <div style={{ marginLeft: 26 }}>
            <PoweredByGemini size={24} />
          </div>
        </div>
      </div>
    </NavyBackdrop>
  );
};

const Fade: React.FC<{ dur: number; children: React.ReactNode }> = ({ dur, children }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [0, FADE, dur - FADE, dur], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: o }}>{children}</AbsoluteFill>;
};

export const Demo: React.FC = () => {
  let t = 0;
  const parts: [number, React.ReactNode][] = [
    [INTRO, <Intro />],
    [T1.total, <AppPart tl={T1} caps={CAPS1} />],
    [CHAT_FRAMES, <ChatGPT />],
    [T3.total, <AppPart tl={T3} caps={CAPS3} />],
    [OUTRO, <Outro />],
  ];
  return (
    <AbsoluteFill style={{ background: C.navy }}>
      {parts.map(([dur, node], i) => {
        const from = t;
        t += dur;
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <Fade dur={dur}>{node}</Fade>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
