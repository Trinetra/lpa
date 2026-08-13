import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// "Wed, 1 June 2026" — the app-wide human-friendly rendering for a bare ISO
// date string (class dates, payment dates, "next on", "since", etc). Never
// render a raw yyyy-MM-dd in the UI.
export function fmtDate(isoDate) {
  if (!isoDate) return "";
  const d = new Date(`${isoDate}T00:00:00`);
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "long", year: "numeric" });
}
