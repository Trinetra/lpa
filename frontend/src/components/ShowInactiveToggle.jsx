import React from "react";

// Consistent "hide inactive students, with an opt-in toggle" behavior across
// every page that lists/picks students (Students, Payments, Classes,
// Invoices). Schedule intentionally does NOT use this — it hard-filters
// inactive students with no toggle, since you can't schedule someone who
// isn't active.
export function filterActive(students, showInactive) {
  return students.filter((s) => showInactive || s.is_active !== false);
}

export function inactiveCountOf(students) {
  return students.filter((s) => s.is_active === false).length;
}

export default function ShowInactiveToggle({ count, checked, onChange, testid = "show-inactive-toggle" }) {
  if (count === 0) return null;
  return (
    <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} data-testid={testid} />
      Show inactive ({count})
    </label>
  );
}
