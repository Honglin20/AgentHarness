interface LogoProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeMap = {
  sm: "h-5 w-auto",
  md: "h-7 w-auto",
  lg: "h-10 w-auto",
};

export function Logo({ size = "md", className = "" }: LogoProps) {
  return (
    <span
      className={`text-sm font-extrabold tracking-[0.35em] select-none ${sizeMap[size]} ${className}`}
      aria-label="TARS"
    >
      TARS
    </span>
  );
}
