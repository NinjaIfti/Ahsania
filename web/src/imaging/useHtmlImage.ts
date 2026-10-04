import { useEffect, useState } from "react";

export interface HtmlImageState {
  image: HTMLImageElement | null;
  failed: boolean;
}

export function useHtmlImage(url: string): HtmlImageState {
  const [state, setState] = useState<HtmlImageState>({ image: null, failed: false });
  useEffect(() => {
    // A new url never shows the previous page's picture.
    setState({ image: null, failed: false });
    const img = new window.Image();
    img.onload = () => setState({ image: img, failed: false });
    img.onerror = () => setState({ image: null, failed: true });
    img.src = url;
    return () => {
      img.onload = null;
      img.onerror = null;
    };
  }, [url]);
  return state;
}
