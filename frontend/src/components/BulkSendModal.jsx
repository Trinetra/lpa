import React, { useEffect, useMemo, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { X, Mail, MessageCircle, CheckCircle2, AlertCircle, Loader2, Send } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

function firstOfThisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
function today() {
  return new Date().toISOString().slice(0, 10);
}

export default function BulkSendModal({ onClose, onDone }) {
  const [range, setRange] = useState({ start: firstOfThisMonth(), end: today() });
  const [channels, setChannels] = useState({ email: true, whatsapp: true });
  const [message, setMessage] = useState("This is a friendly reminder for your outstanding balance. Thank you!");
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState({});
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState(null);

  const loadPreview = () => {
    setLoading(true);
    const params = { start_date: range.start || undefined, end_date: range.end || undefined };
    api.get("/invoices/bulk-preview", { params }).then((r) => {
      setPreview(r.data);
      // Default: select students with outstanding balance
      const sel = {};
      r.data.forEach((s) => { if (s.balance_due > 0) sel[s.student_id] = true; });
      setSelected(sel);
    }).finally(() => setLoading(false));
  };

  useEffect(loadPreview, []); // initial load
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadPreview(); }, [range.start, range.end]);

  const selectedCount = useMemo(
    () => Object.values(selected).filter(Boolean).length,
    [selected]
  );

  const submit = async () => {
    const ids = Object.entries(selected).filter(([, v]) => v).map(([k]) => k);
    if (!ids.length) return toast.error("Select at least one student");
    const chans = Object.entries(channels).filter(([, v]) => v).map(([k]) => k);
    if (!chans.length) return toast.error("Choose at least one channel");
    setSending(true);
    try {
      const { data } = await api.post("/invoices/bulk-send", {
        start_date: range.start || null,
        end_date: range.end || null,
        student_ids: ids,
        channels: chans,
        public_link_base: window.location.origin,
        message: message || null,
      });
      setResults(data);
      // Auto-open WhatsApp links (browser will likely only allow one to auto-open,
      // rest need manual click on the results row).
      const waLinks = data.results
        .map((r) => r.channels?.whatsapp?.url)
        .filter(Boolean);
      if (waLinks.length === 1) window.open(waLinks[0], "_blank", "noreferrer");
      onDone && onDone();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Bulk send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }}>
      <div data-testid="bulk-send-modal" className="surface w-full max-w-2xl p-6 max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="uppercase-label mb-1">Month-end</div>
            <h3 className="font-serif-display text-2xl">Send outstanding invoices</h3>
          </div>
          <button type="button" onClick={onClose} data-testid="bulk-close-btn" className="p-1"><X size={18} /></button>
        </div>

        {results ? (
          <div>
            <div className="surface p-4 mb-4" style={{ background: "var(--surface-2)" }}>
              <div className="uppercase-label mb-1">Result</div>
              <div className="text-sm">
                <span data-testid="bulk-summary" className="font-serif-display text-xl">
                  {results.summary.emails_sent}
                </span> emails sent · {" "}
                <span className="font-serif-display text-xl">{results.summary.whatsapp_links}</span> WhatsApp links ready
              </div>
            </div>
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {results.results.map((r) => (
                <div key={r.student_id} data-testid={`bulk-result-${r.student_id}`}
                  className="flex items-center justify-between py-3">
                  <div className="min-w-0">
                    <div className="truncate">{r.name}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>Due: {fmt(r.balance_due)}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {r.channels?.email && (
                      <ChannelBadge
                        icon={Mail}
                        label={r.channels.email.status === "sent" ? r.channels.email.to : r.channels.email.reason || r.channels.email.detail}
                        ok={r.channels.email.status === "sent"}
                        skipped={r.channels.email.status === "skipped"}
                      />
                    )}
                    {r.channels?.whatsapp?.status === "ready" && (
                      <a
                        href={r.channels.whatsapp.url}
                        target="_blank"
                        rel="noreferrer"
                        data-testid={`bulk-wa-${r.student_id}`}
                        className="btn-pill flex items-center gap-1 text-xs"
                        style={{ background: "#25D366", color: "#0b1f13" }}
                      >
                        <MessageCircle size={12} /> Open
                      </a>
                    )}
                    {r.channels?.whatsapp && r.channels.whatsapp.status !== "ready" && (
                      <ChannelBadge icon={MessageCircle} label={r.channels.whatsapp.reason} skipped />
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-end mt-6">
              <button type="button" onClick={onClose} className="btn-pill" data-testid="bulk-done-btn">Done</button>
            </div>
          </div>
        ) : (
          <>
            {/* Range + channels + message */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              <label>
                <span className="uppercase-label block mb-1">From</span>
                <input type="date" value={range.start}
                  onChange={(e) => setRange({ ...range, start: e.target.value })}
                  data-testid="bulk-start-input"
                  className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
              </label>
              <label>
                <span className="uppercase-label block mb-1">To</span>
                <input type="date" value={range.end}
                  onChange={(e) => setRange({ ...range, end: e.target.value })}
                  data-testid="bulk-end-input"
                  className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
              </label>
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
              <ChannelToggle active={channels.email} onClick={() => setChannels({ ...channels, email: !channels.email })}
                icon={Mail} label="Email" testid="bulk-toggle-email" />
              <ChannelToggle active={channels.whatsapp} onClick={() => setChannels({ ...channels, whatsapp: !channels.whatsapp })}
                icon={MessageCircle} label="WhatsApp" testid="bulk-toggle-whatsapp" />
            </div>

            <label className="block mb-4">
              <span className="uppercase-label block mb-1">Message (used in email & WhatsApp)</span>
              <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)}
                data-testid="bulk-message-input"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
            </label>

            <div className="uppercase-label mb-2">Recipients</div>
            {loading ? (
              <div className="p-6 text-center uppercase-label">Loading…</div>
            ) : (
              <div className="surface divide-y max-h-[280px] overflow-y-auto"
                style={{ borderColor: "var(--border)" }}>
                {preview && preview.length === 0 && (
                  <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
                    No students yet.
                  </div>
                )}
                {preview && preview.map((s) => {
                  const disabled = s.balance_due <= 0 && !(selected[s.student_id]);
                  return (
                    <label key={s.student_id}
                      data-testid={`bulk-row-${s.student_id}`}
                      className={`flex items-center justify-between gap-4 px-4 py-3 cursor-pointer ${disabled ? "opacity-60" : ""}`}
                      style={{ borderTop: "1px solid var(--border)" }}>
                      <div className="flex items-center gap-3 min-w-0">
                        <input type="checkbox"
                          checked={!!selected[s.student_id]}
                          onChange={(e) => setSelected({ ...selected, [s.student_id]: e.target.checked })}
                          data-testid={`bulk-check-${s.student_id}`}
                          className="accent-[color:var(--primary)]" />
                        <div className="min-w-0">
                          <div className="text-sm truncate">{s.name}</div>
                          <div className="text-xs flex gap-2" style={{ color: "var(--text-muted)" }}>
                            {s.email ? <span className="flex items-center gap-1"><Mail size={11} />{s.email}</span> : <span style={{ color: "var(--error)" }}>no email</span>}
                            {s.phone ? <span className="flex items-center gap-1"><MessageCircle size={11} />{s.phone}</span> : <span>no phone</span>}
                          </div>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="font-serif-display" style={{ color: s.balance_due > 0 ? "var(--error)" : "var(--success)" }}>
                          {fmt(s.balance_due)}
                        </div>
                        <div className="uppercase-label">Due</div>
                      </div>
                    </label>
                  );
                })}
              </div>
            )}

            <div className="flex items-center justify-between mt-6 gap-3 flex-wrap">
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {selectedCount} student{selectedCount === 1 ? "" : "s"} selected
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={onClose} className="btn-ghost" data-testid="bulk-cancel-btn">Cancel</button>
                <button type="button" onClick={submit} disabled={sending || selectedCount === 0}
                  data-testid="bulk-send-btn"
                  className="btn-pill flex items-center gap-2">
                  {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  {sending ? "Sending…" : `Send to ${selectedCount}`}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ChannelToggle({ active, onClick, icon: Icon, label, testid }) {
  return (
    <button type="button" onClick={onClick} data-testid={testid}
      className="flex items-center gap-2 px-3 py-2 rounded-full text-xs transition-colors"
      style={{
        background: active ? "rgba(212,132,100,0.15)" : "transparent",
        color: active ? "var(--primary)" : "var(--text-muted)",
        border: `1px solid ${active ? "rgba(212,132,100,0.4)" : "var(--border)"}`,
      }}>
      <Icon size={13} /> {label}
    </button>
  );
}

function ChannelBadge({ icon: Icon, label, ok, skipped }) {
  const color = ok ? "var(--success)" : skipped ? "var(--text-muted)" : "var(--error)";
  const IconRight = ok ? CheckCircle2 : AlertCircle;
  return (
    <div className="text-xs flex items-center gap-1" style={{ color }}>
      <Icon size={12} />
      <span className="hidden sm:inline max-w-[140px] truncate">{label}</span>
      <IconRight size={12} />
    </div>
  );
}
