/** Small colour helpers for deriving Ionic colour variants from the configured base colours. */

export type Rgb = [number, number, number];

export function hexToRgb(hex: string): Rgb {
  const value = hex.replace('#', '');
  return [
    Number.parseInt(value.slice(0, 2), 16),
    Number.parseInt(value.slice(2, 4), 16),
    Number.parseInt(value.slice(4, 6), 16),
  ];
}

export function rgbToHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map((channel) => Math.round(channel).toString(16).padStart(2, '0')).join('')}`.toUpperCase();
}

/** Linear blend of two colours. weight 0 returns base, weight 1 returns target. */
export function mixHex(base: string, target: string, weight: number): string {
  const from = hexToRgb(base);
  const to = hexToRgb(target);
  return rgbToHex(from.map((channel, index) => channel + (to[index] - channel) * weight) as Rgb);
}

/** WCAG relative luminance in 0..1. */
export function relativeLuminance(hex: string): number {
  const channels = hexToRgb(hex).map((channel) => {
    const srgb = channel / 255;
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}
