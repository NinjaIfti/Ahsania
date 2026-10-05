import { useEffect, useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import type { FileOut, SourceBox } from "../api/types";
import { card, secondaryButton } from "../ui/styles";

/** A box drawn over a page: where a value was read ("source") or where the safety net found an identifier ("hit"). */
export type PageMark = SourceBox & { tone: "source" | "hit" };

export function PageViewer({ files, marks = [] }: { files: FileOut[]; marks?: PageMark[] }) {
  const pages = files.filter((f) => f.kind === "page");
  const [index, setIndex] = useState(0);
  const [size, setSize] = useState<{ id: string; w: number; h: number } | null>(null);
  const marksKey = marks.map((m) => `${m.page}:${m.box.join(",")}`).join("|");

  // Show the page of the first mark whenever the marks change (e.g. another field was tapped).
  useEffect(() => {
    if (marks.length > 0) setIndex(marks[0].page - 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marksKey]);

  if (pages.length === 0) return <p className={card}>No images.</p>;
  const current = Math.min(Math.max(index, 0), pages.length - 1);
  const file = pages[current];
  const natural = size?.id === file.id ? size : null;
  const shown = natural ? marks.filter((m) => m.page === current + 1) : [];
  const pct = (value: number, total: number) => `${(value / total) * 100}%`;
  return (
    <details open className={`${card} space-y-2 self-start`}>
      <summary className="cursor-pointer font-medium">
        Page {current + 1} of {pages.length} — pinch or scroll to zoom
      </summary>
      <TransformWrapper key={file.id}>
        <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
          <div className="relative w-full">
            <img
              src={`/api/files/${file.id}`}
              alt={`Page ${current + 1}`}
              className="w-full"
              onLoad={(e) => setSize({ id: file.id, w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            />
            {natural &&
              shown.map((m, i) => (
                <div
                  key={i}
                  data-testid={m.tone === "hit" ? "phi-box" : "source-box"}
                  className={`pointer-events-none absolute border-2 ${m.tone === "hit" ? "border-red-600 bg-red-500/10" : "border-blue-600 bg-blue-500/10"}`}
                  style={{
                    left: pct(m.box[0], natural.w),
                    top: pct(m.box[1], natural.h),
                    width: pct(m.box[2] - m.box[0], natural.w),
                    height: pct(m.box[3] - m.box[1], natural.h),
                  }}
                />
              ))}
          </div>
        </TransformComponent>
      </TransformWrapper>
      {pages.length > 1 && (
        <div className="flex gap-2">
          <button type="button" disabled={current === 0} onClick={() => setIndex(current - 1)} className={secondaryButton}>Previous</button>
          <button type="button" disabled={current === pages.length - 1} onClick={() => setIndex(current + 1)} className={secondaryButton}>Next</button>
        </div>
      )}
    </details>
  );
}
