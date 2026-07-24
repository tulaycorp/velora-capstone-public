"use client";

import * as React from "react";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

function assignRef<T>(ref: React.ForwardedRef<T>, value: T | null) {
  if (typeof ref === "function") {
    ref(value);
    return;
  }

  if (ref) {
    ref.current = value;
  }
}

const AutoResizeTextarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<typeof Textarea>
>(({ className, onInput, value, ...props }, forwardedRef) => {
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);

  const resizeToContent = React.useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "0px";
    const borderHeight = textarea.offsetHeight - textarea.clientHeight;
    textarea.style.height = `${textarea.scrollHeight + borderHeight}px`;
  }, []);

  const setTextareaRef = React.useCallback(
    (textarea: HTMLTextAreaElement | null) => {
      textareaRef.current = textarea;
      assignRef(forwardedRef, textarea);
    },
    [forwardedRef]
  );

  React.useLayoutEffect(() => {
    resizeToContent();
  }, [resizeToContent, value]);

  React.useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea || typeof ResizeObserver === "undefined") {
      return;
    }

    let previousWidth = textarea.clientWidth;
    const observer = new ResizeObserver(() => {
      const nextWidth = textarea.clientWidth;
      if (nextWidth !== previousWidth) {
        previousWidth = nextWidth;
        resizeToContent();
      }
    });
    observer.observe(textarea);

    return () => observer.disconnect();
  }, [resizeToContent]);

  return (
    <Textarea
      {...props}
      ref={setTextareaRef}
      rows={1}
      value={value}
      onInput={(event) => {
        resizeToContent();
        onInput?.(event);
      }}
      className={cn("min-h-10 resize-none overflow-hidden", className)}
    />
  );
});

AutoResizeTextarea.displayName = "AutoResizeTextarea";

export { AutoResizeTextarea };
