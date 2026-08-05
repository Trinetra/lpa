import React, { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { fmtCurrency } from "@/pages/StudentsPage";
import AuthImage from "@/components/AuthImage";
import { ArrowLeft, Upload, Save, Loader2, Link2, Send, CheckCircle2, FileText } from "lucide-react";
import { toast } from "sonner";

const ROOT_DOMAIN = "pravaahacfm.com";
const CURRENCIES = ["INR", "EUR", "USD", "GBP"];

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

function CustomLinkEditor({ eventId, customSlug, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(customSlug || "");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/events/${eventId}`, { custom_slug: value.trim() });
      toast.success(value.trim() ? "Custom link saved" : "Custom link removed");
      setEditing(false);
      onSaved();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't save that link");
    } finally {
      setSaving(false);
    }
  };

  const copy = () => {
    navigator.clipboard.writeText(`https://${ROOT_DOMAIN}/${customSlug}`);
    toast.success("Link copied");
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2 text-xs" data-testid="event-custom-link-editor">
        <span style={{ color: "var(--text-muted)" }}>{ROOT_DOMAIN}/</span>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
          placeholder="workshop2026"
          data-testid="event-custom-link-input"
          className="bg-transparent border border-white/10 rounded px-2 py-1 w-36"
        />
        <button type="button" onClick={save} disabled={saving} data-testid="event-custom-link-save"
          className="btn-ghost px-2 py-1">{saving ? "Saving…" : "Save"}</button>
        <button type="button" onClick={() => { setEditing(false); setValue(customSlug || ""); }}
          data-testid="event-custom-link-cancel" className="btn-ghost px-2 py-1">Cancel</button>
      </div>
    );
  }

  return customSlug ? (
    <div className="flex items-center gap-2 text-xs">
      <button type="button" onClick={copy} data-testid="event-custom-link-copy" className="btn-ghost text-xs flex items-center gap-1">
        <Link2 size={12} /> {ROOT_DOMAIN}/{customSlug}
      </button>
      <button type="button" onClick={() => setEditing(true)} data-testid="event-custom-link-edit" className="btn-ghost px-2 py-1 text-xs">Edit</button>
    </div>
  ) : (
    <button type="button" onClick={() => setEditing(true)} data-testid="event-custom-link-add"
      className="btn-ghost text-xs flex items-center gap-1">
      <Link2 size={12} /> Set a custom link
    </button>
  );
}

function DetailsForm({ event, onSaved }) {
  const [form, setForm] = useState({
    name: event.name || "",
    start_date: event.start_date || "",
    end_date: event.end_date || "",
    time: event.time || "",
    description: event.description || "",
    image_path: event.image_path || null,
    social_instagram: event.social_instagram || "",
    social_facebook: event.social_facebook || "",
    price: event.price ?? 0,
    currency: event.currency || "INR",
    zoom_meeting_id: event.zoom_meeting_id || "",
    zoom_passcode: event.zoom_passcode || "",
  });
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const { data } = await api.post("/uploads/photo", body, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setForm((f) => ({ ...f, image_path: data.path }));
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const save = async (statusOverride) => {
    await api.patch(`/events/${event.id}`, {
      ...form,
      price: Number(form.price) || 0,
      social_instagram: form.social_instagram || null,
      social_facebook: form.social_facebook || null,
      zoom_meeting_id: form.zoom_meeting_id || null,
      zoom_passcode: form.zoom_passcode || null,
      description: form.description || null,
      time: form.time || null,
      ...(statusOverride ? { status: statusOverride } : {}),
    });
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await save();
      toast.success("Event updated");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Update failed");
    } finally {
      setSaving(false);
    }
  };

  // Publishing also saves the rest of the form (image, description, price,
  // etc.) in the same request — otherwise a teacher who uploads an image or
  // edits details and then clicks "Publish" (reasonably expecting that to
  // save everything) would have those edits silently discarded, since only
  // the status field would reach the server.
  const togglePublish = async () => {
    setSaving(true);
    try {
      await save(event.status === "published" ? "draft" : "published");
      toast.success(event.status === "published" ? "Event unpublished" : "Event published");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="event-details-form" className="surface p-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <span
            className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full"
            style={{
              color: event.status === "published" ? "var(--success)" : "var(--text-muted)",
              border: `1px solid ${event.status === "published" ? "var(--success)" : "var(--border)"}`,
            }}
          >
            {event.status}
          </span>
          <button type="button" onClick={togglePublish} disabled={saving} data-testid="event-publish-toggle" className="btn-ghost text-xs">
            {event.status === "published" ? "Unpublish" : "Publish"}
          </button>
        </div>
        <CustomLinkEditor eventId={event.id} customSlug={event.custom_slug} onSaved={onSaved} />
      </div>

      <div className="flex items-start gap-4">
        <div className="w-28 h-28 rounded overflow-hidden shrink-0" style={{ background: "var(--surface-2)" }}>
          <AuthImage
            path={form.image_path}
            className="w-full h-full object-cover"
            fallback={<div className="w-full h-full flex items-center justify-center text-xs" style={{ color: "var(--text-muted)" }}>No image</div>}
          />
        </div>
        <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading} data-testid="event-image-upload-btn"
          className="btn-ghost flex items-center gap-2 text-xs">
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} Upload image
        </button>
        <input ref={fileRef} type="file" accept="image/*" onChange={handleUpload} className="hidden" data-testid="event-image-input" />
      </div>

      <label className="block">
        <span className="uppercase-label block mb-1">Event name</span>
        <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
          data-testid="event-detail-name-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="block">
          <span className="uppercase-label block mb-1">Start date</span>
          <input required type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            data-testid="event-detail-start-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">End date</span>
          <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            data-testid="event-detail-end-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">Time</span>
          <input value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })}
            placeholder="6:00 PM - 8:00 PM IST"
            data-testid="event-detail-time-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>

      <label className="block">
        <span className="uppercase-label block mb-1">Description</span>
        <textarea rows={4} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
          data-testid="event-detail-description-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="uppercase-label block mb-1">Instagram link</span>
          <input value={form.social_instagram} onChange={(e) => setForm({ ...form, social_instagram: e.target.value })}
            placeholder="https://instagram.com/…"
            data-testid="event-detail-instagram-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">Facebook link</span>
          <input value={form.social_facebook} onChange={(e) => setForm({ ...form, social_facebook: e.target.value })}
            placeholder="https://facebook.com/…"
            data-testid="event-detail-facebook-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="uppercase-label block mb-1">Price</span>
          <input type="number" min="0" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })}
            data-testid="event-detail-price-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">Currency</span>
          <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}
            data-testid="event-detail-currency-select"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            style={{ background: "var(--surface)" }}>
            {CURRENCIES.map((c) => (
              <option key={c} value={c} style={{ background: "var(--surface)" }}>{c}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="uppercase-label block mb-1">Zoom meeting ID</span>
          <input value={form.zoom_meeting_id} onChange={(e) => setForm({ ...form, zoom_meeting_id: e.target.value })}
            data-testid="event-detail-zoom-id-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">Zoom passcode</span>
          <input value={form.zoom_passcode} onChange={(e) => setForm({ ...form, zoom_passcode: e.target.value })}
            data-testid="event-detail-zoom-passcode-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>

      <div className="flex justify-end">
        <button type="submit" disabled={saving} className="btn-pill flex items-center gap-2" data-testid="event-detail-save-btn">
          {saving && <Loader2 size={14} className="animate-spin" />} <Save size={14} /> Save changes
        </button>
      </div>
    </form>
  );
}

function StatusPill({ status }) {
  const colors = {
    pending: "var(--text-muted)",
    approved: "var(--primary)",
    invited: "var(--success)",
  };
  return (
    <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full"
      style={{ color: colors[status] || "var(--text-muted)", border: `1px solid ${colors[status] || "var(--border)"}` }}>
      {status}
    </span>
  );
}

function RegistrationsPanel({ eventId, currency }) {
  const [regs, setRegs] = useState(null);
  const [approving, setApproving] = useState(null);
  const [pushing, setPushing] = useState(false);

  const load = () => {
    api.get(`/events/${eventId}/registrations`).then((r) => setRegs(r.data)).catch(() => setRegs([]));
  };

  useEffect(() => { load(); }, [eventId]);

  const approve = async (reg) => {
    const amountStr = window.prompt(`Amount received from ${reg.name} (optional):`, reg.payment_reference ? "" : "");
    if (amountStr === null) return;
    setApproving(reg.id);
    try {
      await api.post(`/events/${eventId}/registrations/${reg.id}/approve`, {
        payment_amount: amountStr ? Number(amountStr) : null,
      });
      toast.success(`${reg.name} approved`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Approve failed");
    } finally {
      setApproving(null);
    }
  };

  const pushInvite = async () => {
    setPushing(true);
    try {
      const { data } = await api.post(`/events/${eventId}/push-invite`, {});
      toast.success(`Invite sent to ${data.sent.length} registrant(s)${data.failed.length ? `, ${data.failed.length} failed` : ""}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Push invite failed");
    } finally {
      setPushing(false);
    }
  };

  if (regs === null) return <div className="uppercase-label">Loading…</div>;

  const approvedNotInvited = regs.filter((r) => r.status === "approved");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="uppercase-label">{regs.length} registration{regs.length === 1 ? "" : "s"}</div>
        <button
          onClick={pushInvite}
          disabled={pushing || approvedNotInvited.length === 0}
          data-testid="event-push-invite-btn"
          className="btn-pill flex items-center gap-2 text-sm disabled:opacity-40"
        >
          {pushing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Push invite ({approvedNotInvited.length})
        </button>
      </div>

      {regs.length === 0 && (
        <div className="surface p-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>No registrations yet.</div>
      )}

      <div className="surface overflow-hidden">
        {regs.map((r) => (
          <div key={r.id} data-testid={`event-reg-row-${r.id}`} className="px-6 py-4 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-serif-display text-base">{r.name}</span>
                  <StatusPill status={r.status} />
                </div>
                <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  {r.email} · {r.mobile} {r.city ? `· ${r.city}` : ""} {r.country ? `, ${r.country}` : ""}
                </div>
                {r.experience && (
                  <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Experience: {r.experience}</div>
                )}
                {r.payment_method && (
                  <div className="text-xs mt-2 flex items-center gap-2 flex-wrap">
                    <span className="uppercase-label">{r.payment_method === "upi" ? "UPI" : "Bank transfer"}</span>
                    <span>Ref: {r.payment_reference}</span>
                    {r.payment_proof_path && (
                      <a href={`${api.defaults.baseURL}/events/${eventId}/registrations/${r.id}/proof`}
                        target="_blank" rel="noreferrer"
                        data-testid={`event-reg-proof-${r.id}`}
                        className="flex items-center gap-1 underline">
                        <FileText size={12} /> View proof
                      </a>
                    )}
                  </div>
                )}
                {r.payment_amount != null && (
                  <div className="text-xs mt-1" style={{ color: "var(--success)" }}>
                    Reconciled: {fmtCurrency(r.payment_amount, currency)} {r.payment_notes ? `— ${r.payment_notes}` : ""}
                  </div>
                )}
              </div>
              {r.status === "pending" && (
                <button
                  onClick={() => approve(r)}
                  disabled={approving === r.id}
                  data-testid={`event-reg-approve-${r.id}`}
                  className="btn-ghost text-xs flex items-center gap-1 shrink-0"
                >
                  {approving === r.id ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />} Approve
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function EventDetailPage() {
  const { id } = useParams();
  const [event, setEvent] = useState(null);

  const load = () => {
    api.get(`/events/${id}`).then((r) => setEvent(r.data)).catch(() => setEvent(false));
  };

  useEffect(() => { load(); }, [id]);

  if (event === null) return <div className="uppercase-label">Loading…</div>;
  if (event === false) return <div className="uppercase-label">Event not found.</div>;

  return (
    <div data-testid="event-detail-page" className="space-y-6">
      <Link to="/events" className="flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
        <ArrowLeft size={14} /> Events
      </Link>
      <header>
        <div className="uppercase-label mb-2">Workshops</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">{event.name}</h1>
        <div className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
          {fmtDate(event.start_date)}{event.end_date && event.end_date !== event.start_date ? ` – ${fmtDate(event.end_date)}` : ""}
        </div>
      </header>

      <DetailsForm event={event} onSaved={load} />

      <section>
        <div className="uppercase-label mb-3">Registrations</div>
        <RegistrationsPanel eventId={event.id} currency={event.currency} />
      </section>
    </div>
  );
}
