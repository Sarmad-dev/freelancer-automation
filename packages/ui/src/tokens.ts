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
} as const;

export const lightTokens = {
  canvas: "#f6f7f9",
  sidebar: "#ffffff",
  surface: "#ffffff",
  elevated: "#eef0f4",
  text: "#14161a",
  textMuted: "#565b66",
  border: "#dcdfe6",
  accent: "#3f7d0f",
  accentContrast: "#ffffff",
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
