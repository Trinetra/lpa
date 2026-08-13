import React, { useEffect, useState } from "react";
import { studentApi } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

export default function StudentDuesPage() {
  const [data, setData] = useState(null);

  useEffect(() => {
    studentApi.get("/student/dues").then((r) => setData(r.data));
  }, []);

  if (!data) return <div data-testid="portal-dues-loading" className="uppercase-label">Loading…</div>;

  const { summary, outstanding_classes: outstanding } = data;

  return (
    <div data-testid="portal-dues-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Your account</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Dues</h1>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="surface p-4"><div className="uppercase-label">Classes</div><div className="font-serif-display text-2xl">{summary.classes_count}</div></div>
        <div className="surface p-4"><div className="uppercase-label">Hours</div><div className="font-serif-display text-2xl">{summary.hours_total}</div></div>
        <div className="surface p-4"><div className="uppercase-label">Billed</div><div className="font-serif-display text-2xl">{fmt(summary.total_billed)}</div></div>
        <div className="surface p-4">
          <div className="uppercase-label">Due</div>
          <div className="font-serif-display text-2xl" style={{ color: summary.balance_due > 0 ? "var(--error)" : "var(--success)" }}>
            {fmt(summary.balance_due)}
          </div>
        </div>
      </div>

      <section>
        <div className="uppercase-label mb-3">Outstanding classes</div>
        <div className="surface">
          {outstanding.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>Nothing outstanding — you're all caught up.</div>
          )}
          {outstanding.map((c) => (
            <div key={c.id} className="flex justify-between px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
              <div>{fmtDate(c.class_date)}</div>
              <div className="font-serif-display" style={{ color: "var(--primary)" }}>{fmt(c.outstanding)}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
