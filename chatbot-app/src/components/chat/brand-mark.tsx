import { GraduationCap } from "lucide-react";
import { cn } from "@/lib/utils";

const SIZES = {
  sm: { box: "h-7 w-7 rounded-lg", icon: "h-3.5 w-3.5" },
  md: { box: "h-8 w-8 rounded-lg", icon: "h-4 w-4" },
  lg: { box: "h-12 w-12 rounded-2xl", icon: "h-6 w-6" },
} as const;

export function BrandMark({
  size = "md",
  className,
}: {
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const s = SIZES[size];
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center bg-primary text-primary-foreground shadow-sm",
        s.box,
        className
      )}
      aria-hidden
    >
      <GraduationCap className={s.icon} />
    </div>
  );
}
