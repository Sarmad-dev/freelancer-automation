export const darkTokens = {
  canvas: "#101114",
  sidebar: "#141519",
  surface: "#181a20",
  elevated: "#20232b",
  text: "#f3f4f6",
  textMuted: "#a1a1aa",
  border: "#2b2e36",
  accent: "#a8e66b",
  accentContrast: "#0f1a05",
  success: "#4ade80",
  warning: "#fbbf24",
  danger: "#f87171",
  info: "#60a5fa",
} as const;

export const lightTokens = {
  canvas: "#f6f7f9",
  sidebar: "#ffffff",
  surface: "#ffffff",
  elevated: "#eef0f4",
  text: "#14161a",
  textMuted: "#565b66",
  border: "#dcdfe6",
  accent: "#386f0d",
  accentContrast: "#ffffff",
  success: "#11693a",
  warning: "#855608",
  danger: "#b42318",
  info: "#1d4ed8",
} as const;

function channel(v: number): number {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return (
    0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
  );
}

/** WCAG 2.x contrast ratio between two #rrggbb colours. */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Colour `fg` blended over `bg` at `alpha` (0-1), as #rrggbb. Mirrors Tailwind's `bg-x/10` tints. */
export function blend(fg: string, bg: string, alpha: number): string {
  const f = parseInt(fg.slice(1), 16);
  const b = parseInt(bg.slice(1), 16);
  const mix = (shift: number) =>
    Math.round(((f >> shift) & 255) * alpha + ((b >> shift) & 255) * (1 - alpha));
  return `#${[16, 8, 0].map((s) => mix(s).toString(16).padStart(2, "0")).join("")}`;
}
