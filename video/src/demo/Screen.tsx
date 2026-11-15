import React from "react";
import { Easing, Img, staticFile, useCurrentFrame } from "remotion";
import capture from "./capture.json";
import { C, FONT, MONO } from "../theme";

/**
 * Plays back screenshots captured from the real Agent Dairy app (see video/README.md, "Demo video").
 * Coordinates are page CSS px of the 1440×810 capture viewport; images are 2× for crisp zooms.
 */
export const PAGE_W = 1440;
export const PAGE_H = 810;

type Box = [number, number, number, number];
type Shot = { file: string; boxes: Record<string, Box> };
const SHOTS = (capture as unknown as { shots: Record<string, Shot> }).shots;

export type Cam = { cx: number; cy: number; s: number };
export type Step = {
  shot: string;
  f: number;
  cam?: Cam;
  cur?: [number, number] | null;
  click?: boolean;
  url?: string;
};

export const FULL: Cam = { cx: PAGE_W / 2, cy: PAGE_H / 2, s: 1 };

/** Centre of a captured element's box, optionally offset. */
export const at = (shot: string, box: string, dx = 0, dy = 0): [number, number] => {
  const b = SHOTS[shot]?.boxes[box];
  if (!b) throw new Error(`No box ${box} on shot ${shot}`);
  return [b[0] + b[2] / 2 + dx, b[1] + b[3] / 2 + dy];
};
/** A camera centred on a captured element. */
export const camOn = (shot: string, box: string, s: number, dx = 0, dy = 0): Cam => {
  const [cx, cy] = at(shot, box, dx, dy);
  return { cx, cy, s };
};

const ease = Easing.bezier(0.45, 0, 0.2, 1);
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;

type Key<T> = { t: number; to: T; dur: number };

export const timeline = (steps: Step[]) => {
  let t = 0;
  const starts: number[] = [];
  const camKeys: Key<Cam>[] = [];
  const curKeys: Key<[number, number] | null>[] = [];
  const clicks: number[] = [];
  for (const s of steps) {
    if (!SHOTS[s.shot]) throw new Error(`Unknown shot ${s.shot}`);
    starts.push(t);
    if (s.cam) camKeys.push({ t, to: s.cam, dur: 22 });
    if (s.cur !== undefined) curKeys.push({ t, to: s.cur, dur: s.click ? Math.max(6, s.f - 8) : 16 });
    if (s.click) clicks.push(t + s.f - 5);
    t += s.f;
  }
  return { steps, starts, camKeys, curKeys, clicks, total: t };
};

const camAt = (keys: Key<Cam>[], t: number): Cam => {
  let c = FULL;
  for (const k of keys) {
    if (t < k.t) break;
    const p = ease(Math.min(1, (t - k.t) / k.dur));
    c = { cx: lerp(c.cx, k.to.cx, p), cy: lerp(c.cy, k.to.cy, p), s: lerp(c.s, k.to.s, p) };
  }
  return c;
};

const curAt = (keys: Key<[number, number] | null>[], t: number): { x: number; y: number; o: number } => {
  let x = PAGE_W * 0.62;
  let y = PAGE_H * 0.8;
  let o = 0;
  for (const k of keys) {
    if (t < k.t) break;
    const p = ease(Math.min(1, (t - k.t) / k.dur));
    if (k.to === null) {
      o = lerp(o, 0, p);
    } else {
      x = lerp(x, k.to[0], p);
      y = lerp(y, k.to[1], p);
      o = lerp(o, 1, Math.min(1, p * 3));
    }
  }
  return { x, y, o };
};

/** Browser window that plays a captured step list. `t0` offsets the timeline within the parent sequence. */
export const Screen: React.FC<{ tl: ReturnType<typeof timeline>; width: number; urlFallback: string }> = ({ tl, width, urlFallback }) => {
  const frame = useCurrentFrame();
  const t = Math.min(frame, tl.total - 1);
  let i = tl.starts.length - 1;
  while (i > 0 && tl.starts[i] > t) i--;
  const step = tl.steps[i];
  let url = urlFallback;
  for (let j = 0; j <= i; j++) if (tl.steps[j].url) url = tl.steps[j].url!;

  const k = width / PAGE_W;
  const viewH = PAGE_H * k;
  const cam = camAt(tl.camKeys, t);
  const s = cam.s;
  const cx = Math.min(Math.max(cam.cx, PAGE_W / (2 * s)), PAGE_W - PAGE_W / (2 * s));
  const cy = Math.min(Math.max(cam.cy, PAGE_H / (2 * s)), PAGE_H - PAGE_H / (2 * s));
  const tx = width / 2 - cx * k * s;
  const ty = viewH / 2 - cy * k * s;

  const cur = curAt(tl.curKeys, t);
  const clickT = tl.clicks.find((c) => t >= c && t < c + 14);
  const press = clickT === undefined ? 0 : t - clickT;
  const ring = clickT === undefined ? 0 : press / 14;
  const sx = cur.x * k * s + tx;
  const sy = cur.y * k * s + ty;

  const bar = 50;
  return (
    <div
      style={{
        width,
        height: viewH + bar,
        borderRadius: 18,
        overflow: "hidden",
        background: C.white,
        boxShadow: "0 40px 90px rgba(11,36,64,0.22), 0 0 0 1px rgba(11,36,64,0.08)",
        fontFamily: FONT,
      }}
    >
      <div style={{ height: bar, background: "#e8edf4", display: "flex", alignItems: "center", gap: 9, padding: "0 20px" }}>
        {["#ff6159", "#ffbd2e", "#28c941"].map((c) => (
          <span key={c} style={{ width: 13, height: 13, borderRadius: 7, background: c }} />
        ))}
        <div style={{ marginLeft: 22, background: C.white, borderRadius: 9, padding: "6px 18px", fontSize: 19, color: C.ink, fontFamily: MONO, display: "flex", alignItems: "center", gap: 9 }}>
          <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke={C.muted} strokeWidth={2.4}>
            <rect x="5" y="11" width="14" height="10" rx="2" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
          {url}
        </div>
      </div>
      <div style={{ position: "relative", width, height: viewH, overflow: "hidden", background: "#f7f9fc" }}>
        <Img
          src={staticFile(SHOTS[step.shot].file)}
          style={{ position: "absolute", left: 0, top: 0, width: PAGE_W * k, height: PAGE_H * k, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${s})` }}
        />
        {cur.o > 0.01 ? (
          <div style={{ position: "absolute", left: sx, top: sy, opacity: cur.o, pointerEvents: "none" }}>
            {clickT !== undefined ? (
              <div
                style={{
                  position: "absolute",
                  left: -26 - ring * 14,
                  top: -26 - ring * 14,
                  width: 52 + ring * 28,
                  height: 52 + ring * 28,
                  borderRadius: "50%",
                  border: `4px solid ${C.yellowDeep}`,
                  opacity: 1 - ring,
                }}
              />
            ) : null}
            <svg
              width={40}
              height={40}
              viewBox="0 0 24 24"
              style={{ position: "absolute", left: -6, top: -4, transform: `scale(${press > 0 && press < 6 ? 0.85 : 1})`, transformOrigin: "6px 4px", filter: "drop-shadow(0 3px 5px rgba(0,0,0,0.35))" }}
            >
              <path d="M5 3l14 8.2-6.3 1.4 3.7 6.9-2.6 1.4-3.7-6.9L5 18.6Z" fill="#0b2440" stroke="white" strokeWidth={1.4} strokeLinejoin="round" />
            </svg>
          </div>
        ) : null}
      </div>
    </div>
  );
};
