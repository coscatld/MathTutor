import type { Scene } from "./scene-types";

/** Content, rather than object references or surrounding prose, defines a scene version. */
export function sceneSessionKey(scene: Scene, sceneId: string): string {
  const content = JSON.stringify(scene, (_key, value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return value;
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
  });
  return JSON.stringify([sceneId, content]);
}
