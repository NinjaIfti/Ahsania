/** One photographed page during capture. Lives in memory until it is uploaded. */
export interface PageDraft {
  id: string;
  blob: Blob;
  url: string;
  width: number;
  height: number;
  blur: number;
}
