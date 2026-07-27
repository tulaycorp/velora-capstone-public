import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type CodeInputProps = React.ComponentProps<typeof Input> & {
  codeKind?: "numeric" | "alphanumeric";
};

const CodeInput = React.forwardRef<HTMLInputElement, CodeInputProps>(
  (
    {
      className,
      codeKind = "numeric",
      inputMode,
      autoComplete,
      autoCapitalize,
      pattern,
      spellCheck,
      ...props
    },
    ref
  ) => (
    <Input
      ref={ref}
      type="text"
      inputMode={inputMode ?? (codeKind === "numeric" ? "numeric" : "text")}
      autoComplete={autoComplete ?? (codeKind === "numeric" ? "one-time-code" : "off")}
      autoCapitalize={autoCapitalize ?? (codeKind === "alphanumeric" ? "characters" : undefined)}
      pattern={pattern ?? (codeKind === "numeric" ? "[0-9]*" : undefined)}
      spellCheck={spellCheck ?? false}
      className={cn(
        "font-mono text-base tabular-nums tracking-[0.18em]",
        codeKind === "alphanumeric" && "uppercase",
        className
      )}
      {...props}
    />
  )
);

CodeInput.displayName = "CodeInput";

export { CodeInput };
