import React, { useId } from "react";
import { C } from "../theme";

// Geometry from assets/logo.svg (viewBox 0 0 2048 2048): an A flowing into a D, an arrow through both.
const BODY = "M355.2 1580 L693 689.2 L965 1460 L1100 1460 C1400 1460 1610 1330 1610 1080 C1610 820 1350 615 930 615";
const SHAFT_FROM = 300;
const SHAFT_TO = 1800;
const SHAFT_Y = 1042;
const HEAD = "M1892 1042 L1785 983 L1785 1101 Z";

/**
 * The Agent Dairy mark. `draw` traces the A and D (0→1); `arrow` fires the arrow through them (0→1).
 * `tile` puts it on the yellow rounded square used in the portals.
 */
export const Logo: React.FC<{
  size: number;
  draw?: number;
  arrow?: number;
  tile?: boolean;
  color?: string;
  shadow?: string | null;
}> = ({ size, draw = 1, arrow = 1, tile = true, color = C.navy, shadow }) => {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const shadowColor = shadow === undefined ? (tile ? C.yellowDeep : null) : shadow;
  const shaftEnd = SHAFT_FROM + (SHAFT_TO - SHAFT_FROM) * Math.min(1, arrow * 1.08);
  const headIn = Math.max(0, Math.min(1, (arrow - 0.82) / 0.18));

  const mark = (stroke: string, dx = 0, dy = 0) => (
    <g transform={`translate(${dx} ${dy})`} clipPath={`url(#base-${id})`}>
      <path
        d={BODY}
        fill="none"
        stroke={stroke}
        strokeWidth={96}
        strokeLinecap="butt"
        strokeLinejoin="miter"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
      />
      {arrow > 0 ? (
        <path d={`M${SHAFT_FROM} ${SHAFT_Y} L${shaftEnd} ${SHAFT_Y}`} stroke={stroke} strokeWidth={58} fill="none" />
      ) : null}
      {headIn > 0 ? (
        <path d={HEAD} fill={stroke} opacity={headIn} transform={`translate(${(1 - headIn) * -70} 0)`} />
      ) : null}
    </g>
  );

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: tile ? size * 0.22 : 0,
        background: tile ? C.yellow : "transparent",
        flex: "none",
        overflow: "hidden",
      }}
    >
      <svg width={size} height={size} viewBox="0 0 2048 2048">
        <defs>
          <clipPath id={`base-${id}`} clipPathUnits="userSpaceOnUse">
            <rect x={0} y={0} width={2048} height={1508} />
          </clipPath>
        </defs>
        {shadowColor ? mark(shadowColor, 5, 22) : null}
        {mark(color)}
      </svg>
    </div>
  );
};
