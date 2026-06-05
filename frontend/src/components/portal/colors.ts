export const COLOR_MAP: Record<string, { accent: string; text: string; badge: string }> = {
  blue:   { accent: "border-l-blue-500",   text: "text-blue-700 dark:text-blue-400",   badge: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" },
  violet: { accent: "border-l-violet-500",  text: "text-violet-700 dark:text-violet-400", badge: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-400" },
  amber:  { accent: "border-l-amber-500",   text: "text-amber-700 dark:text-amber-400",  badge: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" },
  rose:   { accent: "border-l-rose-500",     text: "text-rose-700 dark:text-rose-400",    badge: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-400" },
};

export const DEFAULT_COLOR = COLOR_MAP.blue;

export const COLOR_DOT: Record<string, string> = {
  blue: "bg-blue-500",
  violet: "bg-violet-500",
  amber: "bg-amber-500",
  rose: "bg-rose-500",
};

export const COLOR_TEXT: Record<string, string> = {
  blue: "text-blue-600 dark:text-blue-400",
  violet: "text-violet-600 dark:text-violet-400",
  amber: "text-amber-600 dark:text-amber-400",
  rose: "text-rose-600 dark:text-rose-400",
};
