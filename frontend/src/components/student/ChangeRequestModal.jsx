import React, { useState } from "react";
import { studentApi, formatApiErrorDetail } from "@/lib/api";
import { X } from "lucide-react";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export default function ChangeRequestModal({ block, onClose, onDone }) {
  const [type, setType] = useState("cancel");
  const [scope, setScope] = useState("one_time");
  const [requestedDay, setRequestedDay] = useState(block.day_of_week);
  const [requestedStart, setRequestedStart] = useState(block.start_time);
  const [requestedEnd, setRequestedEnd] = useState(block.end_time);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setSubmitting(true);
    try {
      const body = { block_id: block.id, type, scope, reason: reason || null };
      if (type === "reschedule") {
        body.requested_day_of_week = Number(requestedDay);
        body.requested_start_time = requestedStart;
        body.requested_end_time = requestedEnd;
      }
      const { data } = await studentApi.post("/student/change-requests", body);
      setResult(data);
      onDone?.(data);
    } catch (e2) {
      setErr(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't submit that request");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div data-testid="portal-change-request-modal" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">Request a change</h3>
          <button type="button" onClick={onClose} data-testid="portal-change-request-close" className="p-1">
            <X size={18} />
          </button>
        </div>

        {result ? (
          <div data-testid="portal-change-request-result" className="space-y-4">
            {result.status === "denied" ? (
              <>
                <div className="uppercase-label" style={{ color: "var(--error)" }}>Not available</div>
                <p className="text-sm" style={{ color: "var(--text)" }}>{result.denial_reason}</p>
              </>
            ) : (
              <>
                <div className="uppercase-label" style={{ color: "var(--success)" }}>Sent</div>
                <p className="text-sm" style={{ color: "var(--text)" }}>
                  Your request has been sent to your teacher for approval.
                </p>
              </>
            )}
            <button type="button" onClick={onClose} className="btn-pill w-full" data-testid="portal-change-request-done">
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <span className="uppercase-label block mb-2">What do you need?</span>
              <div className="flex gap-2">
                {[["cancel", "Cancel"], ["reschedule", "Reschedule"]].map(([v, label]) => (
                  <button key={v} type="button" onClick={() => setType(v)}
                    data-testid={`portal-change-type-${v}`}
                    className="flex-1 px-3 py-2 rounded text-sm border"
                    style={{
                      borderColor: type === v ? "var(--primary)" : "var(--border)",
                      color: type === v ? "var(--primary)" : "var(--text)",
                    }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className="uppercase-label block mb-2">Just this once, or going forward?</span>
              <div className="flex gap-2">
                {[["one_time", "Just this class"], ["permanent", "Permanently"]].map(([v, label]) => (
                  <button key={v} type="button" onClick={() => setScope(v)}
                    data-testid={`portal-change-scope-${v}`}
                    className="flex-1 px-3 py-2 rounded text-sm border"
                    style={{
                      borderColor: scope === v ? "var(--primary)" : "var(--border)",
                      color: scope === v ? "var(--primary)" : "var(--text)",
                    }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {type === "reschedule" && (
              <>
                <label className="block">
                  <span className="uppercase-label block mb-1">New day</span>
                  <select value={requestedDay} onChange={(e) => setRequestedDay(e.target.value)}
                    data-testid="portal-change-day-select"
                    className="w-full bg-transparent border border-white/10 rounded px-3 py-2">
                    {DAYS.map((d, i) => (
                      <option key={i} value={i} style={{ color: "#000" }}>{d}</option>
                    ))}
                  </select>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block">
                    <span className="uppercase-label block mb-1">Start</span>
                    <input type="time" required value={requestedStart}
                      onChange={(e) => setRequestedStart(e.target.value)}
                      data-testid="portal-change-start-input"
                      className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
                  </label>
                  <label className="block">
                    <span className="uppercase-label block mb-1">End</span>
                    <input type="time" required value={requestedEnd}
                      onChange={(e) => setRequestedEnd(e.target.value)}
                      data-testid="portal-change-end-input"
                      className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
                  </label>
                </div>
              </>
            )}

            <label className="block">
              <span className="uppercase-label block mb-1">Reason (optional)</span>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
                data-testid="portal-change-reason-input"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
            </label>

            {err && <div className="text-sm" style={{ color: "var(--error)" }}>{err}</div>}

            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={onClose} className="btn-ghost" data-testid="portal-change-cancel-btn">
                Cancel
              </button>
              <button type="submit" disabled={submitting} className="btn-pill" data-testid="portal-change-submit-btn">
                {submitting ? "Sending…" : "Send request"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
