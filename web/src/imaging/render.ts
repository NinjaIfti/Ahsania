import { laplacianVariance, toGray } from "./blur";
import { fitWithin, pageTransform, rotatedSize, type Rect, type Rotation } from "./geometry";

export const MAX_SIDE = 3000;

export interface PreparedPage {
  blob: Blob;
  width: number;
  height: number;
  blur: number;
}

function canvas(width: number, height: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  return c;
}

export function rotateToCanvas(bitmap: ImageBitmap, rotation: Rotation, maxSide: number): HTMLCanvasElement {
  const turned = rotatedSize(bitmap.width, bitmap.height, rotation);
  const { width, height, scale } = fitWithin(turned.width, turned.height, maxSide);
  const out = canvas(width, height);
  const ctx = out.getContext("2d")!;
  ctx.translate(width / 2, height / 2);
  ctx.rotate((rotation * Math.PI) / 180);
  ctx.scale(scale, scale);
  ctx.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
  return out;
}

function toJpeg(source: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    source.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not encode the image"))), "image/jpeg", quality),
  );
}

function blurScore(source: HTMLCanvasElement): number {
  const { width, height } = fitWithin(source.width, source.height, 512);
  const small = canvas(width, height);
  const ctx = small.getContext("2d")!;
  ctx.drawImage(source, 0, 0, width, height);
  return laplacianVariance(toGray(ctx.getImageData(0, 0, width, height).data, width, height), width, height);
}

/** Rotate and crop at full resolution, shrink to MAX_SIDE, and encode a high-quality working copy. */
export async function preparePage(bitmap: ImageBitmap, rotation: Rotation, crop: Rect | null): Promise<PreparedPage> {
  const turned = rotatedSize(bitmap.width, bitmap.height, rotation);
  const area = crop ?? { x: 0, y: 0, w: turned.width, h: turned.height };
  const { width, height, scale } = fitWithin(area.w, area.h, MAX_SIDE);
  const out = canvas(width, height);
  const ctx = out.getContext("2d")!;
  const t = pageTransform(bitmap.width, bitmap.height, rotation, area, scale);
  ctx.setTransform(t.a, t.b, t.c, t.d, t.e, t.f);
  ctx.drawImage(bitmap, 0, 0);
  return { blob: await toJpeg(out, 0.92), width, height, blur: blurScore(out) };
}

/** Burn solid black boxes into the page and re-encode it; the re-encode also drops EXIF/GPS metadata. */
export async function burnRedactions(page: Blob, boxes: Rect[]): Promise<Blob> {
  const bitmap = await createImageBitmap(page);
  const out = canvas(bitmap.width, bitmap.height);
  const ctx = out.getContext("2d")!;
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  ctx.fillStyle = "#000";
  for (const box of boxes) ctx.fillRect(box.x, box.y, box.w, box.h);
  return toJpeg(out, 0.85);
}
