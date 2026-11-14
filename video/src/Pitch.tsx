import React from "react";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { MAX_FRAMES, TRANSITION } from "./theme";
import { ColdOpen } from "./scenes/ColdOpen";
import { Title } from "./scenes/Title";
import { Challenge } from "./scenes/Challenge";
import { HowItWorks } from "./scenes/HowItWorks";
import { Request } from "./scenes/Request";
import { Quote } from "./scenes/Quote";
import { Checks } from "./scenes/Checks";
import { GeminiReview } from "./scenes/GeminiReview";
import { Approval } from "./scenes/Approval";
import { Receipts } from "./scenes/Receipts";
import { Guardrails } from "./scenes/Guardrails";
import { Beyond } from "./scenes/Beyond";
import { Close } from "./scenes/Close";

type Scene = { id: string; frames: number; C: React.FC; enter?: "fade" | "slide" };

// Frame counts at 30 fps. Edit here to retime the cut; the total is checked against MAX_FRAMES below.
export const SCENES: Scene[] = [
  { id: "cold-open", frames: 330, C: ColdOpen },
  { id: "title", frames: 150, C: Title },
  { id: "challenge", frames: 225, C: Challenge },
  { id: "how-it-works", frames: 255, C: HowItWorks },
  { id: "request", frames: 405, C: Request, enter: "slide" },
  { id: "quote", frames: 270, C: Quote, enter: "slide" },
  { id: "checks", frames: 330, C: Checks },
  { id: "gemini-review", frames: 330, C: GeminiReview },
  { id: "approval", frames: 360, C: Approval, enter: "slide" },
  { id: "receipts", frames: 255, C: Receipts },
  { id: "guardrails", frames: 300, C: Guardrails },
  { id: "beyond", frames: 210, C: Beyond },
  { id: "close", frames: 225, C: Close },
];

export const TOTAL_FRAMES = SCENES.reduce((sum, s) => sum + s.frames, 0) - TRANSITION * (SCENES.length - 1);

if (TOTAL_FRAMES > MAX_FRAMES) {
  throw new Error(
    `Pitch is ${(TOTAL_FRAMES / 30).toFixed(2)} s, over the ${MAX_FRAMES / 30} s ceiling (hard limit 2:00). Trim scene frames in Pitch.tsx.`,
  );
}

export const Pitch: React.FC = () => (
  <TransitionSeries>
    {SCENES.flatMap((s, i) => {
      const items = [];
      if (i > 0) {
        items.push(
          <TransitionSeries.Transition
            key={`${s.id}-t`}
            presentation={s.enter === "slide" ? slide({ direction: "from-right" }) : fade()}
            timing={linearTiming({ durationInFrames: TRANSITION })}
          />,
        );
      }
      items.push(
        <TransitionSeries.Sequence key={s.id} durationInFrames={s.frames}>
          <s.C />
        </TransitionSeries.Sequence>,
      );
      return items;
    })}
  </TransitionSeries>
);
