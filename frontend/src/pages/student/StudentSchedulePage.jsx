import React, { useEffect, useState } from "react";
import { studentApi } from "@/lib/api";
import ChangeRequestModal from "@/components/student/ChangeRequestModal";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const fmt12h = (t) => {
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12}${period}` : `${h12}:${String(m).padStart(2, "0")}${period}`;
};

const STATUS_COLOR = {
  pending: "var(--text-muted)",
  approved: "var(--success)",
  denied: "var(--error)",
};

export default function StudentSchedulePage() {
  const [blocks, setBlocks] = useState([]);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(null);

  const load = () => {
    setLoading(true);
    Promise.all([
      studentApi.get("/student/schedule"),
      studentApi.get("/student/change-requests"),
    ])
      .then(([sched, reqs]) => {
        setBlocks(sched.data);
        setRequests(reqs.data);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div data-testid="portal-schedule-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="portal-schedule-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Your classes</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Schedule</h1>
      </header>

      <div className="surface">
        {blocks.length === 0 && (
          <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            No classes on your schedule yet.
          </div>
        )}
        {blocks.map((b) => (
          <div key={b.id} className="flex items-center justify-between px-6 py-4 text-sm"
            style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`portal-schedule-block-${b.id}`}>
            <div>
              <div className="font-serif-display text-xl">{DAYS[b.day_of_week]}</div>
              <div style={{ color: "var(--text-muted)" }}>
                {fmt12h(b.start_time)}–{fmt12h(b.end_time)}
                {b.next_occurrence && ` · next on ${b.next_occurrence}`}
              </div>
              {b.notes && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{b.notes}</div>}
            </div>
            <button type="button" className="btn-ghost" onClick={() => setRequesting(b)}
              data-testid={`portal-schedule-request-change-${b.id}`}>
              Request change
            </button>
          </div>
        ))}
      </div>

      {requests.length > 0 && (
        <section>
          <div className="uppercase-label mb-3">Your requests</div>
          <div className="surface">
            {requests.map((r) => (
              <div key={r.id} className="flex justify-between px-6 py-3 text-sm"
                style={{ borderTop: "1px solid var(--border)" }} data-testid={`portal-change-request-row-${r.id}`}>
                <div>
                  <div>
                    {r.type === "cancel" ? "Cancel" : "Reschedule"} · {r.scope === "one_time" ? "one time" : "permanent"}
                  </div>
                  {r.reason && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{r.reason}</div>}
                  {r.status === "denied" && r.denial_reason && (
                    <div className="text-xs mt-1" style={{ color: "var(--error)" }}>{r.denial_reason}</div>
                  )}
                </div>
                <div className="uppercase-label" style={{ color: STATUS_COLOR[r.status] || "var(--text)" }}>
                  {r.status}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {requesting && (
        <ChangeRequestModal
          block={requesting}
          onClose={() => setRequesting(null)}
          onDone={() => load()}
        />
      )}
    </div>
  );
}
