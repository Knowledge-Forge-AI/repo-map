import type { Widget } from "./types";

export interface ServiceConfig {
  name: string;
}

type Mode = "fast" | "safe";

enum Status {
  Ready,
  Done,
}

export const loadPanel = () => import("./component");
export const loadDynamic = () => import(`./pages/${name}.tsx`);
