import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** A plain <select> styled like the shadcn inputs (best on phones). */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-9 rounded-md border border-input bg-transparent px-2 text-sm text-foreground shadow-xs focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
