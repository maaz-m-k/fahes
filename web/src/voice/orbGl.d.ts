export type OrbGl = { draw(t: number, ph: number, user: number, self: number): void };
export const TEAL: { id: string; style: number; seed: number; c: string[]; w: number[]; en: string };
export function makeOrb(canvas: HTMLCanvasElement, cand: typeof TEAL): OrbGl | null;
