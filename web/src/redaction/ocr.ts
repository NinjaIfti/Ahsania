import { createWorker, type Worker } from "tesseract.js";
import type { OcrLine } from "./labels";

let workerPromise: Promise<Worker> | null = null;

function getWorker(): Promise<Worker> {
  workerPromise ??= createWorker("eng", undefined, {
    workerPath: "/tesseract/worker.min.js",
    corePath: "/tesseract/core",
    langPath: "/tesseract/lang",
    workerBlobURL: false,
  });
  return workerPromise;
}

/** Text lines with pixel boxes, recognised entirely on this device. */
export async function ocrLines(image: Blob): Promise<OcrLine[]> {
  const worker = await getWorker();
  const { data } = await worker.recognize(image, {}, { blocks: true });
  return (data.blocks ?? []).flatMap((block) =>
    block.paragraphs.flatMap((paragraph) => paragraph.lines.map((line) => ({ text: line.text, bbox: line.bbox }))),
  );
}
