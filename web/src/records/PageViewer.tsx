import { useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import type { FileOut } from "../api/types";
import { card, secondaryButton } from "../ui/styles";

export function PageViewer({ files }: { files: FileOut[] }) {
  const pages = files.filter((f) => f.kind === "page");
  const [index, setIndex] = useState(0);
  if (pages.length === 0) return <p className={card}>No images.</p>;
  const current = Math.min(index, pages.length - 1);
  const file = pages[current];
  return (
    <details open className={`${card} space-y-2 self-start`}>
      <summary className="cursor-pointer font-medium">
        Page {current + 1} of {pages.length} — pinch or scroll to zoom
      </summary>
      <TransformWrapper key={file.id}>
        <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
          <img src={`/api/files/${file.id}`} alt={`Page ${current + 1}`} className="w-full" />
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
