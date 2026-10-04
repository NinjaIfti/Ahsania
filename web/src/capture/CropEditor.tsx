import type Konva from "konva";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Image as KonvaImage, Layer, Rect as KonvaRect, Stage, Transformer } from "react-konva";
import { clampRect, rotatedSize, scaleRect, type Rect, type Rotation } from "../imaging/geometry";
import { preparePage, rotateToCanvas, type PreparedPage } from "../imaging/render";
import { primaryButton, secondaryButton } from "../ui/styles";

interface Props {
  bitmap: ImageBitmap;
  onCancel: () => void;
  onDone: (page: PreparedPage) => void;
}

export function CropEditor({ bitmap, onCancel, onDone }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<Konva.Rect>(null);
  const transformerRef = useRef<Konva.Transformer>(null);
  const [rotation, setRotation] = useState<Rotation>(0);
  const [displayWidth, setDisplayWidth] = useState(0);
  const [crop, setCrop] = useState<Rect | null>(null); // stage pixels; null = whole image
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDisplayWidth(Math.min(el.clientWidth, 900));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const preview = useMemo(() => rotateToCanvas(bitmap, rotation, 1200), [bitmap, rotation]);
  const stageWidth = displayWidth;
  const stageHeight = displayWidth > 0 ? Math.round((preview.height * displayWidth) / preview.width) : 0;
  const frame = crop ?? { x: 0, y: 0, w: stageWidth, h: stageHeight };

  useEffect(() => setCrop(null), [rotation, stageWidth]);
  useEffect(() => {
    if (transformerRef.current && frameRef.current) {
      transformerRef.current.nodes([frameRef.current]);
      transformerRef.current.getLayer()?.batchDraw();
    }
  }, [stageWidth, stageHeight, rotation]);

  async function done() {
    setBusy(true);
    setError(null);
    try {
      const full = rotatedSize(bitmap.width, bitmap.height, rotation);
      const cropInFullPixels = crop === null ? null : clampRect(scaleRect(crop, full.width / stageWidth), full.width, full.height);
      onDone(await preparePage(bitmap, rotation, cropInFullPixels));
    } catch {
      setError("Could not prepare this page. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const turn = (delta: 90 | 270) => setRotation(((rotation + delta) % 360) as Rotation);

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">Crop and straighten</h2>
      <p className="text-sm text-slate-600">Drag the blue frame's corners so only the document is inside.</p>
      <div ref={containerRef} className="w-full">
        {stageWidth > 0 && (
          <Stage width={stageWidth} height={stageHeight}>
            <Layer>
              <KonvaImage image={preview} width={stageWidth} height={stageHeight} />
              <KonvaRect
                ref={frameRef}
                x={frame.x}
                y={frame.y}
                width={frame.w}
                height={frame.h}
                stroke="#1d4ed8"
                strokeWidth={3}
                draggable
                onDragEnd={(e) => setCrop({ ...frame, x: e.target.x(), y: e.target.y() })}
                onTransformEnd={(e) => {
                  const node = e.target;
                  const w = Math.max(20, node.width() * node.scaleX());
                  const h = Math.max(20, node.height() * node.scaleY());
                  node.scaleX(1);
                  node.scaleY(1);
                  setCrop({ x: node.x(), y: node.y(), w, h });
                }}
              />
              <Transformer ref={transformerRef} rotateEnabled={false} keepRatio={false} />
            </Layer>
          </Stage>
        )}
      </div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => turn(270)} className={secondaryButton}>Rotate left</button>
        <button type="button" onClick={() => turn(90)} className={secondaryButton}>Rotate right</button>
        <button type="button" onClick={() => setCrop(null)} className={secondaryButton}>Reset crop</button>
        <button type="button" onClick={onCancel} className={secondaryButton}>Cancel</button>
        <button type="button" disabled={busy || stageWidth === 0} onClick={done} className={primaryButton}>
          {busy ? "Preparing…" : "Use this page"}
        </button>
      </div>
    </div>
  );
}
