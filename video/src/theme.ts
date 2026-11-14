import { loadFont } from "@remotion/google-fonts/InstrumentSans";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

const sans = loadFont("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin", "latin-ext"],
});
const mono = loadMono("normal", { weights: ["400", "600"], subsets: ["latin"] });

export const FONT = sans.fontFamily;
export const MONO = mono.fontFamily;

// The redesigned Agent Dairy portal palette (app/ui/portal.css, app/ui/workspace.css).
export const C = {
  navy: "#0b2440",
  navy2: "#0f2d4e",
  navyLift: "#163556",
  ink: "#0f2744",
  muted: "#5b6b80",
  blue: "#235e94",
  page: "#f7f9fc",
  sky: "#f4f7fb",
  pale: "#eef3fb",
  line: "#e3e9f2",
  lineStrong: "#d5deea",
  white: "#ffffff",
  green: "#047857",
  greenBg: "#e4f6ef",
  amber: "#8a4b00",
  amberBg: "#fff0ce",
  red: "#9b2c1f",
  redBg: "#ffe9e5",
  yellow: "#ffd700",
  yellowDeep: "#e6c200",
  yellowSoft: "#f0e68c",
  railText: "#c9d6e8",
  ring: "#1d3f8f",
} as const;

// Gemini accent, used only on AI elements (text only, no Google or DeepMind logos).
export const GEMINI = {
  gradient: "linear-gradient(90deg, #4796e3 0%, #9177c7 55%, #ca6673 100%)",
  a: "#4796e3",
  b: "#9177c7",
  c: "#ca6673",
};

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const TRANSITION = 12;
/** Hard ceiling: the submission limit is 2:00, we keep a 2 s buffer. */
export const MAX_FRAMES = 118 * FPS;

export const CLIENT_URL = "agentdairy.ai";
export const OPS_URL = "agentdairy.ai/operations";
