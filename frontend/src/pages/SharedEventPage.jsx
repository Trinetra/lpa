import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/lib/api";
import { useTheme } from "@/context/ThemeContext";
import { fmtCurrency } from "@/pages/StudentsPage";
import { Instagram, Facebook, Youtube, Upload, Loader2, CheckCircle2, Sun, Moon } from "lucide-react";
import { toast } from "sonner";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

function RegistrationForm({ event, onRegistered }) {
  const [form, setForm] = useState({ name: "", dob: "", mobile: "", email: "", city: "", country: "", experience: "" });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await axios.post(`${API}/events/${event.id}/register`, {
        ...form,
        dob: form.dob || null,
        city: form.city || null,
        country: form.country || null,
        experience: form.experience || null,
      });
      onRegistered(data);
    } catch (e2) {
      toast.error(e2?.response?.data?.detail || "Registration failed — please try again");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="event-registration-form" className="surface p-6 space-y-3">
      <h2 className="font-serif-display text-2xl mb-2">Register</h2>
      <label className="block">
        <span className="uppercase-label block mb-1">Full name</span>
        <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
          data-testid="reg-name-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="uppercase-label block mb-1">Date of birth</span>
          <input type="date" value={form.dob} onChange={(e) => setForm({ ...form, dob: e.target.value })}
            data-testid="reg-dob-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">Mobile</span>
          <input required value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })}
            data-testid="reg-mobile-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>
      <label className="block">
        <span className="uppercase-label block mb-1">Email</span>
        <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
          data-testid="reg-email-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="uppercase-label block mb-1">City</span>
          <input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })}
            data-testid="reg-city-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1">Country</span>
          <input value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}
            data-testid="reg-country-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>
      <label className="block">
        <span className="uppercase-label block mb-1">Experience (optional)</span>
        <textarea rows={3} value={form.experience} onChange={(e) => setForm({ ...form, experience: e.target.value })}
          placeholder="Tell us a bit about your dance background"
          data-testid="reg-experience-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>
      <div className="flex justify-end pt-2">
        <button type="submit" disabled={saving} data-testid="reg-submit-btn" className="btn-pill flex items-center gap-2">
          {saving && <Loader2 size={14} className="animate-spin" />} Register
        </button>
      </div>
    </form>
  );
}

function PaymentStep({ event, registration }) {
  const [method, setMethod] = useState("upi");
  const [reference, setReference] = useState("");
  const [qrUrl, setQrUrl] = useState(null);
  const [bank, setBank] = useState(null);
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (method === "upi") {
      setQrUrl(`${API}/events/${event.id}/registrations/${registration.id}/qr`);
    } else if (method === "bank_transfer" && !bank) {
      axios.get(`${API}/events/${event.id}/bank-details`).then((r) => setBank(r.data)).catch(() => setBank({}));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [method]);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await axios.post(`${API}/events/${event.id}/registrations/${registration.id}/payment`, {
        payment_method: method,
        payment_reference: reference,
      });
      if (file) {
        const body = new FormData();
        body.append("file", file);
        await axios.post(`${API}/events/${event.id}/registrations/${registration.id}/payment-proof`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
      setSubmitted(true);
      toast.success("Payment details submitted");
    } catch (e2) {
      toast.error(e2?.response?.data?.detail || "Couldn't submit payment details");
    } finally {
      setSaving(false);
    }
  };

  if (submitted) {
    return (
      <div className="surface p-8 text-center" data-testid="event-payment-submitted">
        <CheckCircle2 size={28} style={{ color: "var(--success)", margin: "0 auto 12px" }} />
        <h2 className="font-serif-display text-2xl mb-2">Thank you, {registration.name}!</h2>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Your registration and payment details are in. We'll confirm your spot and email your Zoom details soon.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} data-testid="event-payment-form" className="surface p-6 space-y-4">
      <h2 className="font-serif-display text-2xl">Complete your payment</h2>
      <div className="font-serif-display text-3xl" style={{ color: "var(--primary)" }}>
        {fmtCurrency(event.price, event.currency)}
      </div>

      <div className="flex gap-2">
        <button type="button" onClick={() => setMethod("upi")} data-testid="pay-method-upi"
          className="btn-pill text-xs" style={{ opacity: method === "upi" ? 1 : 0.5 }}>UPI</button>
        <button type="button" onClick={() => setMethod("bank_transfer")} data-testid="pay-method-bank"
          className="btn-pill text-xs" style={{ opacity: method === "bank_transfer" ? 1 : 0.5 }}>Bank transfer</button>
      </div>

      {method === "upi" ? (
        <div className="text-center py-2">
          {qrUrl && (
            <img src={qrUrl} alt="UPI QR code" data-testid="event-upi-qr" className="mx-auto rounded"
              style={{ maxWidth: 220, background: "#fff", padding: 8 }}
              onError={(e) => { e.target.style.display = "none"; }} />
          )}
          <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>Scan to pay via any UPI app</div>
        </div>
      ) : (
        <div className="text-sm space-y-1 p-4 rounded" style={{ background: "var(--surface-2)" }} data-testid="event-bank-details">
          {bank?.bank_name && <div>Bank: <b>{bank.bank_name}</b></div>}
          {bank?.bank_account_number && <div>Account: <b>{bank.bank_account_number}</b></div>}
          {bank?.bank_ifsc_code && <div>IFSC: <b>{bank.bank_ifsc_code}</b></div>}
          {bank?.bank_swift_code && <div>SWIFT: <b>{bank.bank_swift_code}</b></div>}
          {!bank && <div style={{ color: "var(--text-muted)" }}>Loading bank details…</div>}
        </div>
      )}

      <label className="block">
        <span className="uppercase-label block mb-1">
          {method === "upi" ? "UPI transaction reference" : "Transaction reference / remarks"}
        </span>
        <input required value={reference} onChange={(e) => setReference(e.target.value)}
          placeholder={method === "upi" ? "UTR number" : "Transaction ID or remarks"}
          data-testid="pay-reference-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>

      <label className="block">
        <span className="uppercase-label block mb-1">Payment screenshot (optional)</span>
        <div className="flex items-center gap-2">
          <label className="btn-ghost text-xs flex items-center gap-2 cursor-pointer">
            <Upload size={14} /> {file ? file.name : "Choose file"}
            <input type="file" accept="image/*,.pdf" className="hidden"
              data-testid="pay-proof-input"
              onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
        </div>
      </label>

      <div className="flex justify-end pt-2">
        <button type="submit" disabled={saving} data-testid="pay-submit-btn" className="btn-pill flex items-center gap-2">
          {saving && <Loader2 size={14} className="animate-spin" />} Submit payment details
        </button>
      </div>
    </form>
  );
}

export default function SharedEventPage({ bySlug = false }) {
  const { token, slug } = useParams();
  const [event, setEvent] = useState(null);
  const [err, setErr] = useState("");
  const [registration, setRegistration] = useState(null);

  useEffect(() => {
    const url = bySlug ? `${API}/events/slug/${slug}` : `${API}/events/share/${token}`;
    axios.get(url).then((r) => setEvent(r.data)).catch(() => setErr(bySlug ? "Page not found." : "Event not found."));
  }, [bySlug, token, slug]);

  if (err)
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="surface p-8 text-center">
          <div className="uppercase-label mb-2">Not found</div>
          <div className="font-serif-display text-2xl">{err}</div>
        </div>
      </div>
    );
  if (!event) return <div className="min-h-screen flex items-center justify-center uppercase-label">Loading…</div>;

  const studio = event.studio || {};

  return (
    <div className="min-h-screen py-14 px-6" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto space-y-6">
        <TopBar />
        <header>
          <div className="uppercase-label mb-2">{studio.studio_name || "Workshop"}</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl mb-3" data-testid="shared-event-name">{event.name}</h1>
          <div className="text-sm mb-1" style={{ color: "var(--text-muted)" }}>
            {fmtDate(event.start_date)}{event.end_date && event.end_date !== event.start_date ? ` – ${fmtDate(event.end_date)}` : ""}
            {event.time && ` · ${event.time}`}
          </div>
          <div className="font-serif-display text-2xl mt-2" style={{ color: "var(--primary)" }}>
            {fmtCurrency(event.price, event.currency)}
          </div>
          {(event.social_instagram || event.social_facebook) && (
            <div className="flex gap-3 mt-3">
              {event.social_instagram && (
                <a href={event.social_instagram} target="_blank" rel="noreferrer" data-testid="shared-event-instagram">
                  <Instagram size={18} />
                </a>
              )}
              {event.social_facebook && (
                <a href={event.social_facebook} target="_blank" rel="noreferrer" data-testid="shared-event-facebook">
                  <Facebook size={18} />
                </a>
              )}
            </div>
          )}
        </header>

        {event.image_path && (
          <img src={`${API}/events/${event.id}/image`} alt={event.name} data-testid="shared-event-image"
            className="w-full rounded-lg object-cover" style={{ maxHeight: 480 }} />
        )}

        {event.description && (
          <div className="surface p-6 text-sm whitespace-pre-wrap" style={{ color: "var(--text)" }} data-testid="shared-event-description">
            {event.description}
          </div>
        )}

        {registration ? (
          <PaymentStep event={event} registration={registration} />
        ) : (
          <RegistrationForm event={event} onRegistered={setRegistration} />
        )}

        {(studio.social_youtube || studio.social_instagram || studio.social_facebook) && (
          <footer className="flex justify-center gap-4 pt-6" style={{ color: "var(--text-muted)" }}>
            {studio.social_youtube && (
              <a href={studio.social_youtube} target="_blank" rel="noreferrer" data-testid="shared-event-studio-youtube">
                <Youtube size={18} />
              </a>
            )}
            {studio.social_instagram && (
              <a href={studio.social_instagram} target="_blank" rel="noreferrer" data-testid="shared-event-studio-instagram">
                <Instagram size={18} />
              </a>
            )}
            {studio.social_facebook && (
              <a href={studio.social_facebook} target="_blank" rel="noreferrer" data-testid="shared-event-studio-facebook">
                <Facebook size={18} />
              </a>
            )}
          </footer>
        )}
      </div>
    </div>
  );
}

function TopBar() {
  const { theme, toggle } = useTheme();
  return (
    <div className="flex items-center justify-between">
      <img src="/icon-192.png" alt="Pravaaha Center for Movement" data-testid="shared-event-logo" style={{ height: 32, width: 32 }} />
      <button type="button" onClick={toggle} data-testid="shared-event-theme-toggle" className="btn-ghost p-2">
        {theme === "dark" ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
      </button>
    </div>
  );
}
