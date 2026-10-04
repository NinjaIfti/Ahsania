import type Konva from "konva";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Image as KonvaImage, Layer, Rect as KonvaRect, Stage, Transformer } from "react-konva";
import type { Rect } from "../imaging/geometry";
import { useHtmlImage } from "../imaging/useHtmlImage";

interface Props {
  url: string;
  width: number;
  height: number;
  boxes: Rect[];
  disabled: boolean;
  selected: number | null;
  onSelect: (index: number | null) => void;
  onChange: (boxes: Rect[]) => void;
  /** Called once the page picture is loaded and drawn, so the step knows this page was seen. */
  onShown: () => void;
}

export function RedactionCanvas({ url, width, height, boxes, disabled, selected, onSelect, onChange, onShown }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const transformerRef = useRef<Konva.Transformer>(null);
  const shapes = useRef(new Map<number, Konva.Rect>());
  const { image, failed } = useHtmlImage(url);
  const [displayWidth, setDisplayWidth] = useState(0);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDisplayWidth(Math.min(el.clientWidth, 900));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const scale = displayWidth > 0 ? displayWidth / width : 0;

  useEffect(() => {
    if (image && scale > 0) onShown();
    // Fires once per page shown; the callback identity is deliberately not a dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [image, scale, url]);

  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) return;
    const node = selected === null ? undefined : shapes.current.get(selected);
    transformer.nodes(node && !disabled ? [node] : []);
    transformer.getLayer()?.batchDraw();
  }, [selected, boxes, disabled, scale]);

  const update = (index: number, box: Rect) => onChange(boxes.map((b, i) => (i === index ? box : b)));
  const deselectOnBackground = (e: Konva.KonvaEventObject<Event>) => {
    if (e.target === e.target.getStage() || e.target.getClassName() === "Image") onSelect(null);
  };

  return (
    <div ref={containerRef} className="w-full">
      {failed && (
        <p role="alert" className="text-red-700">
          This page could not be shown — go back and retake it.
        </p>
      )}
      {!failed && scale > 0 && image && (
        <Stage width={displayWidth} height={Math.round(height * scale)} onMouseDown={deselectOnBackground} onTouchStart={deselectOnBackground}>
          <Layer>
            <KonvaImage image={image} width={displayWidth} height={Math.round(height * scale)} />
            {boxes.map((box, i) => (
              <KonvaRect
                key={i}
                ref={(node) => {
                  if (node) shapes.current.set(i, node);
                  else shapes.current.delete(i);
                }}
                x={box.x * scale}
                y={box.y * scale}
                width={box.w * scale}
                height={box.h * scale}
                fill="black"
                opacity={0.85}
                stroke={i === selected ? "#dc2626" : undefined}
                strokeWidth={2}
                draggable={!disabled}
                onMouseDown={() => onSelect(i)}
                onTouchStart={() => onSelect(i)}
                onDragEnd={(e) => update(i, { ...box, x: e.target.x() / scale, y: e.target.y() / scale })}
                onTransformEnd={(e) => {
                  const node = e.target;
                  const w = (node.width() * node.scaleX()) / scale;
                  const h = (node.height() * node.scaleY()) / scale;
                  node.scaleX(1);
                  node.scaleY(1);
                  update(i, { x: node.x() / scale, y: node.y() / scale, w, h });
                }}
              />
            ))}
            <Transformer ref={transformerRef} rotateEnabled={false} keepRatio={false} />
          </Layer>
        </Stage>
      )}
    </div>
  );
}
