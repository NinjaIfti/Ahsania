import type { Rect } from "../imaging/geometry";

/** One photographed page during capture. Unredacted: lives in memory only, never stored. */
export interface PageDraft {
  id: string;
  blob: Blob;
  url: string;
  width: number;
  height: number;
  blur: number;
  boxes: Rect[];
  ocrDone: boolean;
}
