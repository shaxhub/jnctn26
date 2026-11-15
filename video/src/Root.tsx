import React from "react";
import { Composition, Folder } from "remotion";
import { Pitch, SCENES, TOTAL_FRAMES } from "./Pitch";
import { Demo, DEMO_FRAMES } from "./demo/Demo";
import { FPS, HEIGHT, MAX_FRAMES, WIDTH } from "./theme";

if (DEMO_FRAMES > MAX_FRAMES) {
  throw new Error(`Demo is ${(DEMO_FRAMES / 30).toFixed(2)} s, over the ${MAX_FRAMES / 30} s ceiling (hard limit 2:00). Shorten steps in src/demo/Demo.tsx.`);
}

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Demo" component={Demo} durationInFrames={DEMO_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Composition id="Pitch" component={Pitch} durationInFrames={TOTAL_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    {/* Individual scenes, for previewing and tweaking one at a time in the Studio. */}
    <Folder name="Scenes">
      {SCENES.map((s) => (
        <Composition key={s.id} id={`scene-${s.id}`} component={s.C} durationInFrames={s.frames} fps={FPS} width={WIDTH} height={HEIGHT} />
      ))}
    </Folder>
  </>
);
