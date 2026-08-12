import React, { useEffect, useState } from "react";
import { studentApi } from "@/lib/api";
import StudentAuthImage from "@/components/student/StudentAuthImage";

const fmtWhen = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
};

export default function StudentAnnouncementsPage() {
  const [items, setItems] = useState(null);

  useEffect(() => {
    studentApi.get("/student/announcements").then((r) => {
      setItems(r.data);
      // Mark every unread post as read now that they've actually seen this
      // page — no separate "mark read" click needed.
      r.data.filter((a) => !a.read).forEach((a) => {
        studentApi.post(`/student/announcements/${a.id}/read`).catch(() => {});
      });
    });
  }, []);

  if (!items) return <div data-testid="portal-announcements-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="portal-announcements-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Studio</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Announcements</h1>
      </header>

      {items.length === 0 ? (
        <div className="surface p-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
          No updates yet — check back soon.
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((a) => (
            <div key={a.id} data-testid={`portal-announcement-${a.id}`} className="surface p-6">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>{fmtWhen(a.created_at)}</div>
                {!a.read && (
                  <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full"
                    style={{ color: "var(--primary)", border: "1px solid var(--primary)" }}>
                    New
                  </span>
                )}
              </div>
              <p className="text-sm mt-2 whitespace-pre-wrap">{a.body}</p>
              {a.image_path && (
                <StudentAuthImage path={a.image_path} className="mt-3 rounded-lg max-h-64 object-cover w-full" />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
