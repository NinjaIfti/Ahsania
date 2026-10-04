export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type Rotation = 0 | 90 | 180 | 270;

export function fitWithin(width: number, height: number, maxSide: number) {
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return { width: Math.round(width * scale), height: Math.round(height * scale), scale };
}

export function rotatedSize(width: number, height: number, rotation: Rotation) {
  return rotation === 90 || rotation === 270 ? { width: height, height: width } : { width, height };
}

export function clampRect(r: Rect, width: number, height: number): Rect {
  const x = Math.max(0, Math.min(r.x, width));
  const y = Math.max(0, Math.min(r.y, height));
  return { x, y, w: Math.max(1, Math.min(r.w, width - x)), h: Math.max(1, Math.min(r.h, height - y)) };
}

export function scaleRect(r: Rect, s: number): Rect {
  return { x: r.x * s, y: r.y * s, w: r.w * s, h: r.h * s };
}

/** Canvas 2D transform matrix mapping bitmap pixel (x,y) to output canvas after rotation, crop, and scale. */
export function pageTransform(
  width: number,
  height: number,
  rotation: Rotation,
  area: Rect,
  scale: number,
): { a: number; b: number; c: number; d: number; e: number; f: number } {
  const turned = rotatedSize(width, height, rotation);
  const tw = turned.width;
  const th = turned.height;

  // Use exact integer trig values for quarter turns to avoid floating-point noise
  let cos: number, sin: number;
  switch (rotation) {
    case 0:
      cos = 1;
      sin = 0;
      break;
    case 90:
      cos = 0;
      sin = 1;
      break;
    case 180:
      cos = -1;
      sin = 0;
      break;
    case 270:
      cos = 0;
      sin = -1;
      break;
  }

  const a = scale * cos;
  const b = scale * sin;
  const c = -scale * sin;
  const d = scale * cos;
  const e = scale * (-(cos * width / 2 - sin * height / 2) + tw / 2 - area.x);
  const f = scale * (-(sin * width / 2 + cos * height / 2) + th / 2 - area.y);

  return { a, b, c, d, e, f };
}
