import React from "react";
import { C, FONT, MONO } from "../theme";
import { Logo } from "./Logo";

export type Camera = { s: number; x: number; y: number };

/**
 * A browser window whose page is laid out at real portal size (logical px) and scaled up so it stays
 * readable on a projector. `camera` zooms into the page: s = extra zoom, x/y = logical top-left corner.
 */
export const Browser: React.FC<{
  url: string;
  width: number;
  height: number;
  zoom: number;
  camera?: Camera;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ url, width, height, zoom, camera = { s: 1, x: 0, y: 0 }, children, style }) => {
  const bar = 56;
  const s = zoom * camera.s;
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 22,
        overflow: "hidden",
        background: C.white,
        boxShadow: "0 40px 90px rgba(11,36,64,0.22), 0 0 0 1px rgba(11,36,64,0.08)",
        display: "flex",
        flexDirection: "column",
        fontFamily: FONT,
        color: C.ink,
        ...style,
      }}
    >
      <div style={{ height: bar, background: "#e8edf4", display: "flex", alignItems: "center", gap: 10, padding: "0 22px", flex: "none" }}>
        {["#ff6159", "#ffbd2e", "#28c941"].map((c) => (
          <span key={c} style={{ width: 14, height: 14, borderRadius: 7, background: c }} />
        ))}
        <div
          style={{
            marginLeft: 26,
            background: C.white,
            borderRadius: 10,
            padding: "7px 20px",
            fontSize: 20,
            color: C.ink,
            fontFamily: MONO,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={C.muted} strokeWidth={2.4}>
            <rect x="5" y="11" width="14" height="10" rx="2" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
          {url}
        </div>
      </div>
      <div style={{ position: "relative", flex: 1, overflow: "hidden" }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: width / zoom,
            height: (height - bar) / zoom,
            transformOrigin: "0 0",
            transform: `scale(${s}) translate(${-camera.x}px, ${-camera.y}px)`,
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
};

const ICONS: Record<string, React.ReactNode> = {
  Dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  "Product Search": (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  "Draft Tickets": (
    <>
      <path d="M6 3.5h9l4 4V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" />
      <path d="M15 3.5V8h4M9 12h6M9 16h6" />
    </>
  ),
  "Submitted Requests": (
    <>
      <path d="M4 7h16v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7Z" />
      <path d="M4 7l2-3h12l2 3M9 12h6" />
    </>
  ),
  Analytics: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  Settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1" />
    </>
  ),
};

const Brand: React.FC<{ dark: boolean; sub: string }> = ({ dark, sub }) => (
  <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "4px 4px" }}>
    <Logo size={40} />
    <div style={{ fontWeight: 700, fontSize: 19, lineHeight: 1.15, color: dark ? "white" : C.ink }}>
      Agent Dairy
      <div style={{ fontSize: 12.5, fontWeight: 500, color: dark ? "#a9c5eb" : C.muted }}>{sub}</div>
    </div>
  </div>
);

/** Buyer workspace shell (white rail, crumbs, page head with the yellow accent). */
export const ClientShell: React.FC<{
  active: string;
  title: string;
  sub: string;
  children: React.ReactNode;
  width: number;
  height: number;
}> = ({ active, title, sub, children, width, height }) => (
  <div style={{ display: "flex", width, height, background: C.page, fontFamily: FONT, color: C.ink }}>
    <div style={{ width: 248, background: C.white, borderRight: `1px solid ${C.line}`, padding: "26px 16px", flex: "none" }}>
      <Brand dark={false} sub="Valio Aimo" />
      <div style={{ display: "grid", gap: 6, marginTop: 34 }}>
        {Object.keys(ICONS).map((n) => {
          const on = n === active;
          return (
            <div
              key={n}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "11px 12px",
                borderRadius: 8,
                fontSize: 15,
                fontWeight: on ? 700 : 500,
                color: on ? "white" : "#42556e",
                background: on ? C.navy : "transparent",
                boxShadow: on ? `inset 4px 0 ${C.yellow}` : "none",
              }}
            >
              <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                {ICONS[n]}
              </svg>
              {n}
            </div>
          );
        })}
      </div>
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div
        style={{
          height: 56,
          background: C.white,
          borderBottom: `1px solid ${C.line}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 48px",
          fontSize: 13.5,
        }}
      >
        <span style={{ color: C.muted }}>
          Workspace / <b style={{ color: C.ink }}>{title}</b>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 600 }}>
          Workspace
          <span style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "6px 34px 6px 12px" }}>Hotel kitchen</span>
        </span>
      </div>
      <div style={{ padding: "28px 48px" }}>
        <div style={{ display: "flex", gap: 14, alignItems: "stretch", marginBottom: 22 }}>
          <span style={{ width: 5, borderRadius: 3, background: C.yellow }} />
          <div>
            <div style={{ fontSize: 29, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.1 }}>{title}</div>
            <div style={{ fontSize: 14, color: C.muted, marginTop: 4 }}>{sub}</div>
          </div>
        </div>
        {children}
      </div>
    </div>
  </div>
);

/** Aimo operations shell (navy rail, admin top bar). */
export const AdminShell: React.FC<{ children: React.ReactNode; width: number; height: number }> = ({
  children,
  width,
  height,
}) => (
  <div style={{ display: "flex", width, height, background: C.sky, fontFamily: FONT, color: C.ink }}>
    <div style={{ width: 232, background: C.navy, padding: "26px 16px", flex: "none", display: "flex", flexDirection: "column" }}>
      <Brand dark sub="Valio Aimo®" />
      <div
        style={{
          marginTop: 38,
          padding: "11px 12px",
          borderRadius: 8,
          background: "#26466d",
          boxShadow: `inset 4px 0 ${C.yellow}`,
          color: "white",
          fontSize: 15,
        }}
      >
        Aimo operations
      </div>
      <div style={{ marginTop: "auto", fontSize: 12.5, color: "#a9c5eb" }}>Junction 2026 prototype</div>
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div
        style={{
          height: 64,
          background: C.white,
          borderBottom: `1px solid ${C.line}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 40px 0 48px",
          fontSize: 16,
          fontWeight: 600,
        }}
      >
        Admin portal
        <span style={{ border: `1px solid ${C.lineStrong}`, borderRadius: 8, padding: "8px 14px" }}>Sign out</span>
      </div>
      <div style={{ padding: "28px 40px" }}>{children}</div>
    </div>
  </div>
);

export const Card: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ background: C.white, border: `1px solid ${C.line}`, borderRadius: 16, padding: 22, ...style }}>{children}</div>
);

export const YellowButton: React.FC<{ children: React.ReactNode; press?: number; style?: React.CSSProperties }> = ({
  children,
  press = 1,
  style,
}) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      padding: "9px 14px",
      borderRadius: 8,
      background: C.yellow,
      border: `1px solid ${C.yellowDeep}`,
      color: C.navy,
      fontWeight: 700,
      fontSize: 16,
      transform: `scale(${press})`,
      ...style,
    }}
  >
    {children}
  </span>
);

export const GhostButton: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      padding: "9px 14px",
      borderRadius: 8,
      background: C.white,
      border: `1px solid ${C.lineStrong}`,
      color: C.ink,
      fontWeight: 600,
      fontSize: 16,
      ...style,
    }}
  >
    {children}
  </span>
);

export const Pointer: React.FC<{ x: number; y: number; down?: boolean; size?: number }> = ({ x, y, down = false, size = 44 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    style={{
      position: "absolute",
      left: x,
      top: y,
      transform: `scale(${down ? 0.85 : 1})`,
      transformOrigin: "4px 2px",
      filter: "drop-shadow(0 4px 6px rgba(0,0,0,0.25))",
      zIndex: 10,
    }}
  >
    <path d="M4 2l15 10.5-6.6 1.3 3.9 7.3-2.8 1.5-3.9-7.4L4 20z" fill={C.navy} stroke="white" strokeWidth={1.4} strokeLinejoin="round" />
  </svg>
);
