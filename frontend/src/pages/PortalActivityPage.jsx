import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Check, X, Eye } from "lucide-react";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const fmt12h = (t) => {
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12}${period}` : `${h12}:${String(m).padStart(2, "0")}${period}`;
};

function ChangeRequestsTab() {
  const [requests, setRequests] = useState(null);
  const [denyingId, setDenyingId] = useState(null);
  const [denyReason, setDenyReason] = useState("");

  const load = () => {
    api.get("/change-requests").then((r) => setRequests(r.data));
  };

  useEffect(() => { load(); }, []);

  const approve = async (id) => {
    try {
      await api.post(`/change-requests/${id}/approve`);
      toast.success("Approved");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't approve that request");
    }
  };

  const deny = async (id) => {
    try {
      await api.post(`/change-requests/${id}/deny`, { reason: denyReason || null });
      setDenyingId(null);
      setDenyReason("");
      toast.success("Denied");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't deny that request");
    }
  };

  if (!requests) return <div className="uppercase-label">Loading…</div>;
  const pending = requests.filter((r) => r.status === "pending");
  const decided = requests.filter((r) => r.status !== "pending");

  return (
    <div className="space-y-8">
      <section>
        <div className="uppercase-label mb-3">Pending ({pending.length})</div>
        <div className="surface">
          {pending.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>Nothing waiting on you.</div>
          )}
          {pending.map((r) => (
            <div key={r.id} className="px-6 py-4 text-sm" style={{ borderTop: "1px solid var(--border)" }}
              data-testid={`change-request-${r.id}`}>
              <div className="flex justify-between items-start gap-4">
                <div>
                  <div className="font-serif-display text-lg">{r.student_name}</div>
                  <div style={{ color: "var(--text-muted)" }}>
                    {r.type === "cancel" ? "Cancel" : "Reschedule"} · {r.scope === "one_time" ? "just this class" : "permanently"}
                    {r.type === "reschedule" && r.requested_day_of_week != null && (
                      <> → {DAYS[r.requested_day_of_week]} {fmt12h(r.requested_start_time)}–{fmt12h(r.requested_end_time)}</>
                    )}
                  </div>
                  {r.reason && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>"{r.reason}"</div>}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button type="button" onClick={() => approve(r.id)} className="btn-ghost p-2" style={{ color: "var(--success)" }}
                    data-testid={`approve-request-${r.id}`}>
                    <Check size={16} />
                  </button>
                  <button type="button" onClick={() => setDenyingId(r.id)} className="btn-ghost p-2" style={{ color: "var(--error)" }}
                    data-testid={`deny-request-${r.id}`}>
                    <X size={16} />
                  </button>
                </div>
              </div>
              {denyingId === r.id && (
                <div className="mt-3 flex gap-2">
                  <input value={denyReason} onChange={(e) => setDenyReason(e.target.value)} placeholder="Reason (optional)"
                    className="flex-1 bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
                    data-testid={`deny-reason-${r.id}`} />
                  <button type="button" onClick={() => deny(r.id)} className="btn-pill" data-testid={`deny-confirm-${r.id}`}>Confirm deny</button>
                  <button type="button" onClick={() => setDenyingId(null)} className="btn-ghost">Cancel</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {decided.length > 0 && (
        <section>
          <div className="uppercase-label mb-3">History</div>
          <div className="surface">
            {decided.map((r) => (
              <div key={r.id} className="flex justify-between px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
                <div>
                  <div>{r.student_name} · {r.type === "cancel" ? "Cancel" : "Reschedule"}</div>
                  {r.denial_reason && <div className="text-xs" style={{ color: "var(--text-muted)" }}>{r.denial_reason}</div>}
                </div>
                <div className="uppercase-label" style={{ color: r.status === "approved" ? "var(--success)" : "var(--error)" }}>
                  {r.status}{r.auto_denied ? " (auto)" : ""}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function PaymentProofsTab() {
  const [proofs, setProofs] = useState(null);

  const load = () => {
    api.get("/payment-proofs").then((r) => setProofs(r.data));
  };

  useEffect(() => { load(); }, []);

  const view = async (id) => {
    // Safari (iOS and macOS) only allows window.open() to succeed when it's
    // called synchronously inside the click handler — one made after an
    // await (fetching the file as a blob, since this needs the auth token
    // a plain link can't carry) is treated as a popup, not a user action,
    // and silently dropped. No error, nothing happens — exactly this bug.
    // Chrome is lenient about the timing, which is why this worked on
    // Android. Opening the tab first, then filling in its location once the
    // blob is ready, keeps it inside the click's own gesture window.
    const tab = window.open("", "_blank", "noopener,noreferrer");
    try {
      const res = await api.get(`/payment-proofs/${id}/file`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      if (tab) tab.location = url;
      else window.open(url, "_blank", "noopener,noreferrer"); // popup already blocked outright — fall back
    } catch (e) {
      tab?.close();
      toast.error("Couldn't open that file");
    }
  };

  const markReviewed = async (id) => {
    try {
      await api.post(`/payment-proofs/${id}/mark-reviewed`);
      toast.success("Marked reviewed");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't update that");
    }
  };

  if (!proofs) return <div className="uppercase-label">Loading…</div>;
  const pending = proofs.filter((p) => p.status === "pending");
  const reviewed = proofs.filter((p) => p.status !== "pending");

  return (
    <div className="space-y-8">
      <section>
        <div className="uppercase-label mb-3">Pending review ({pending.length})</div>
        <div className="surface">
          {pending.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>Nothing waiting on you.</div>
          )}
          {pending.map((p) => (
            <div key={p.id} className="flex justify-between items-center px-6 py-3 text-sm"
              style={{ borderTop: "1px solid var(--border)" }} data-testid={`payment-proof-${p.id}`}>
              <div>
                <div className="font-serif-display text-lg">{p.student_name}</div>
                <div style={{ color: "var(--text-muted)" }}>
                  {p.uploaded_at?.slice(0, 10)}
                  {p.amount_claimed != null && <> · ₹{Number(p.amount_claimed).toLocaleString("en-IN")} claimed</>}
                </div>
                {p.note && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{p.note}</div>}
              </div>
              <div className="flex gap-2 shrink-0">
                <button type="button" onClick={() => view(p.id)} className="btn-ghost p-2" data-testid={`view-proof-${p.id}`}>
                  <Eye size={16} />
                </button>
                <button type="button" onClick={() => markReviewed(p.id)} className="btn-ghost p-2" style={{ color: "var(--success)" }}
                  data-testid={`mark-reviewed-${p.id}`}>
                  <Check size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {reviewed.length > 0 && (
        <section>
          <div className="uppercase-label mb-3">Reviewed</div>
          <div className="surface">
            {reviewed.map((p) => (
              <div key={p.id} className="flex justify-between px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
                <div>{p.student_name} · {p.uploaded_at?.slice(0, 10)}</div>
                <button type="button" onClick={() => view(p.id)} className="btn-ghost p-1"><Eye size={14} /></button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default function PortalActivityPage() {
  const [tab, setTab] = useState("requests");

  return (
    <div data-testid="portal-activity-page" className="space-y-6">
      <header>
        <div className="uppercase-label mb-2">Student portal</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Requests</h1>
      </header>

      <div className="flex gap-2">
        <button type="button" onClick={() => setTab("requests")} data-testid="portal-activity-tab-requests"
          className="px-4 py-2 rounded text-sm border"
          style={{ borderColor: tab === "requests" ? "var(--primary)" : "var(--border)", color: tab === "requests" ? "var(--primary)" : "var(--text)" }}>
          Change requests
        </button>
        <button type="button" onClick={() => setTab("proofs")} data-testid="portal-activity-tab-proofs"
          className="px-4 py-2 rounded text-sm border"
          style={{ borderColor: tab === "proofs" ? "var(--primary)" : "var(--border)", color: tab === "proofs" ? "var(--primary)" : "var(--text)" }}>
          Payment proofs
        </button>
      </div>

      {tab === "requests" ? <ChangeRequestsTab /> : <PaymentProofsTab />}
    </div>
  );
}
