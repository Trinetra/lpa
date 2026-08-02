import React, { useEffect, useState } from "react";
import { studentApi } from "@/lib/api";

export default function StudentProgressPage() {
  const [classes, setClasses] = useState(null);

  useEffect(() => {
    studentApi.get("/student/progress").then((r) => setClasses(r.data));
  }, []);

  if (!classes) return <div data-testid="portal-progress-loading" className="uppercase-label">Loading…</div>;

  const recentTopics = [...new Set(classes.slice(0, 5).flatMap((c) => c.topics || []))];

  return (
    <div data-testid="portal-progress-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">What you've learned</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Progress</h1>
      </header>

      {recentTopics.length > 0 && (
        <section>
          <div className="uppercase-label mb-3">Recently taught</div>
          <div className="surface p-4 flex flex-wrap gap-2">
            {recentTopics.map((t) => (
              <span key={t} className="text-xs px-2.5 py-1 rounded-full"
                style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)", border: "1px solid rgba(212,132,100,0.4)" }}>
                {t}
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <div className="uppercase-label mb-3">Class history</div>
        <div className="surface">
          {classes.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No classes logged yet.</div>
          )}
          {classes.map((c) => (
            <div key={c.id} className="flex justify-between px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
              <div>
                <div>{c.class_date}</div>
                {c.topics && c.topics.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {c.topics.map((t) => (
                      <span key={t} className="text-[10px] px-2 py-0.5 rounded-full"
                        style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)" }}>
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ color: "var(--text-muted)" }}>{c.hours}h</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
