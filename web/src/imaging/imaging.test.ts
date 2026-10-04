import { describe, expect, it } from "vitest";
import { BLUR_THRESHOLD, isBlurry, laplacianVariance, toGray } from "./blur";
import { clampRect, fitWithin, rotatedSize, scaleRect } from "./geometry";

function image(width: number, height: number, f: (x: number, y: number) => number): Float32Array {
  const gray = new Float32Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) gray[y * width + x] = f(x, y);
  return gray;
}

describe("geometry", () => {
  it("shrinks large images to the size limit", () => {
    expect(fitWithin(6000, 4000, 3000)).toEqual({ width: 3000, height: 2000, scale: 0.5 });
  });
  it("never enlarges small images", () => {
    expect(fitWithin(800, 600, 3000)).toEqual({ width: 800, height: 600, scale: 1 });
  });
  it("swaps sides for quarter turns", () => {
    expect(rotatedSize(400, 300, 90)).toEqual({ width: 300, height: 400 });
    expect(rotatedSize(400, 300, 180)).toEqual({ width: 400, height: 300 });
  });
  it("keeps a crop rectangle inside the image", () => {
    expect(clampRect({ x: -10, y: 50, w: 500, h: 500 }, 400, 300)).toEqual({ x: 0, y: 50, w: 400, h: 250 });
  });
  it("scales rectangles", () => {
    expect(scaleRect({ x: 10, y: 20, w: 30, h: 40 }, 2)).toEqual({ x: 20, y: 40, w: 60, h: 80 });
  });
});

describe("blur detection", () => {
  it("finds no detail in a flat image", () => {
    expect(laplacianVariance(image(20, 20, () => 128), 20, 20)).toBe(0);
  });
  it("treats a smooth gradient as blurry", () => {
    expect(isBlurry(laplacianVariance(image(50, 50, (x) => x * 2), 50, 50))).toBe(true);
  });
  it("treats sharp black-and-white detail as sharp", () => {
    const score = laplacianVariance(image(50, 50, (x, y) => ((x + y) % 2 ? 255 : 0)), 50, 50);
    expect(score).toBeGreaterThan(BLUR_THRESHOLD);
    expect(isBlurry(score)).toBe(false);
  });
  it("treats tiny images as blurry", () => {
    expect(laplacianVariance(new Float32Array(4), 2, 2)).toBe(0);
  });
  it("converts RGBA to luma", () => {
    const gray = toGray(new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255]), 2, 1);
    expect(gray[0]).toBeCloseTo(76.245);
    expect(gray[1]).toBeCloseTo(29.07);
  });
});
