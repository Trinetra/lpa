import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, X, MapPin, Trash2, Globe } from "lucide-react";
import { toast } from "sonner";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

function TourForm({ onClose, onSaved }) {
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [location, setLocation] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/tours", {
        name,
        start_date: startDate,
        end_date: endDate,
        location: location || null,
      });
      toast.success("Tour created");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed to create tour");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="tour-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">New tour</h3>
          <button type="button" onClick={onClose} data-testid="tour-form-close" className="p-1"><X size={18} /></button>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Tour name</span>
          <input required value={name} onChange={(e) => setName(e.target.value)}
            data-testid="tour-name-input"
            placeholder="e.g. Europe Tour 2026"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Start date</span>
            <input required type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
              data-testid="tour-start-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">End date</span>
            <input required type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
              data-testid="tour-end-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <label className="block mb-6">
          <span className="uppercase-label block mb-1">Location (optional)</span>
          <input value={location} onChange={(e) => setLocation(e.target.value)}
            data-testid="tour-location-input"
            placeholder="e.g. Europe"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-ghost" data-testid="tour-cancel-btn">Cancel</button>
          <button type="submit" disabled={saving} className="btn-pill" data-testid="tour-save-btn">
            {saving ? "Creating…" : "Create tour"}
          </button>
        </div>
      </form>
    </div>
  );
}

// One-off performance: a single show, not part of a multi-stop tour. Shown
// in Upcoming on www.pravaahacfm.com when "Show on website" is on, and
// suggested for Past events (Website page) once its date has passed.
function PerformanceForm({ perf, onClose, onSaved }) {
  const isNew = !perf.id;
  const [title, setTitle] = useState(perf.title || "");
  const [city, setCity] = useState(perf.city || "");
  const [venue, setVenue] = useState(perf.venue || "");
  const [date, setDate] = useState(perf.date || "");
  const [time, setTime] = useState(perf.time || "");
  const [notes, setNotes] = useState(perf.notes || "");
  const [instagram, setInstagram] = useState(perf.instagram || "");
  const [showOnWebsite, setShowOnWebsite] = useState(!!perf.show_on_website);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { title, city, venue: venue || null, date, time: time || null, notes: notes || null,
        instagram: instagram.trim(), show_on_website: showOnWebsite };
      if (isNew) await api.post("/performances", body);
      else await api.patch(`/performances/${perf.id}`, body);
      toast.success(isNew ? "Performance added" : "Performance updated");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete "${perf.title}"?`)) return;
    setDeleting(true);
    try {
      await api.delete(`/performances/${perf.id}`);
      toast.success("Performance deleted");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
      setDeleting(false);
    }
  };

  const input = "w-full bg-transparent border border-white/10 rounded px-3 py-2";
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="performance-form" className="surface w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">{isNew ? "New performance" : "Edit performance"}</h3>
          <button type="button" onClick={onClose} className="p-1"><X size={18} /></button>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Title</span>
          <input required value={title} onChange={(e) => setTitle(e.target.value)} data-testid="performance-title-input"
            placeholder="e.g. Margazhi Festival recital" className={input} />
        </label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">City</span>
            <input required value={city} onChange={(e) => setCity(e.target.value)} data-testid="performance-city-input" className={input} />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Venue (optional)</span>
            <input value={venue} onChange={(e) => setVenue(e.target.value)} data-testid="performance-venue-input" className={input} />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Date</span>
            <input required type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="performance-date-input" className={input} />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Time (optional)</span>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} data-testid="performance-time-input" className={input} />
          </label>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Notes (private)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="performance-notes-input" className={input} />
        </label>
        <label className="block mb-4">
          <span className="uppercase-label block mb-1">Instagram post (optional)</span>
          <input value={instagram} onChange={(e) => setInstagram(e.target.value)} data-testid="performance-instagram-input"
            placeholder="https://www.instagram.com/p/…" className={input} />
        </label>
        <label className="flex items-center gap-2 text-sm mb-6 cursor-pointer">
          <input type="checkbox" checked={showOnWebsite} onChange={(e) => setShowOnWebsite(e.target.checked)}
            data-testid="performance-website-toggle" />
          Show on website (Upcoming)
        </label>
        <div className="flex justify-between gap-3">
          <div>
            {!isNew && (
              <button type="button" onClick={remove} disabled={deleting} data-testid="performance-delete-btn"
                className="btn-ghost text-sm" style={{ color: "var(--error)" }}>
                {deleting ? "Deleting…" : "Delete"}
              </button>
            )}
          </div>
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={saving} className="btn-pill" data-testid="performance-save-btn">
              {saving ? "Saving…" : isNew ? "Add performance" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function PerformancesSection() {
  const [perfs, setPerfs] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = () => {
    api.get("/performances").then((r) => setPerfs(r.data)).catch(() => setPerfs([]));
  };
  useEffect(() => { load(); }, []);

  if (perfs === null) return null;
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  // Upcoming soonest-first, then past most-recent-first.
  const upcoming = perfs.filter((p) => p.date >= today).reverse();
  const past = perfs.filter((p) => p.date < today);

  const row = (p) => (
    <button key={p.id} onClick={() => setEditing(p)} data-testid={`performance-row-${p.id}`}
      className="surface surface-hover p-4 w-full text-left flex items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="font-serif-display text-lg">{p.title}</div>
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          {fmtDate(p.date)}{p.time ? ` · ${p.time}` : ""}
        </div>
        <div className="text-sm flex items-center gap-1 mt-1" style={{ color: "var(--text-muted)" }}>
          <MapPin size={12} /> {[p.venue, p.city].filter(Boolean).join(", ")}
        </div>
      </div>
      {p.show_on_website && (
        <span className="text-xs flex items-center gap-1 shrink-0" style={{ color: "var(--primary)" }}>
          <Globe size={12} /> On website
        </span>
      )}
    </button>
  );

  return (
    <section data-testid="performances-section" className="space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="font-serif-display text-2xl">One-off performances</h2>
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>
            Single shows that aren't part of a tour. Past ones appear under Website → Past events → Recently finished.
          </div>
        </div>
        <button onClick={() => setEditing({})} data-testid="new-performance-btn" className="btn-pill flex items-center gap-2 text-sm">
          <Plus size={14} /> New performance
        </button>
      </div>
      {perfs.length === 0 && (
        <div className="surface p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No one-off performances yet.</div>
      )}
      {upcoming.length > 0 && <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{upcoming.map(row)}</div>}
      {past.length > 0 && (
        <>
          <div className="uppercase-label pt-2">Past</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 opacity-70">{past.map(row)}</div>
        </>
      )}
      {editing && (
        <PerformanceForm perf={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}
    </section>
  );
}

export default function ToursPage() {
  const [tours, setTours] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const load = () => {
    api.get("/tours").then((r) => setTours(r.data)).catch(() => setTours([]));
  };

  useEffect(() => { load(); }, []);

  const remove = async (e, tourId, name) => {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm(`Delete "${name}"? This removes its schedule, expenses, check-ins, contacts, and to-dos too.`)) return;
    try {
      await api.delete(`/tours/${tourId}`);
      toast.success("Tour deleted");
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    }
  };

  if (tours === null) return <div data-testid="tours-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="tours-page" className="space-y-8">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Touring</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Tours</h1>
        </div>
        <button onClick={() => setShowForm(true)} data-testid="new-tour-btn" className="btn-pill flex items-center gap-2">
          <Plus size={16} /> New tour
        </button>
      </header>

      {tours.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>
          No tours yet. <button onClick={() => setShowForm(true)} className="underline">Create your first tour.</button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {tours.map((t) => (
          <Link
            key={t.id}
            to={`/tours/${t.id}`}
            data-testid={`tour-card-${t.id}`}
            className="surface surface-hover p-5 block relative group"
          >
            <button
              onClick={(e) => remove(e, t.id, t.name)}
              data-testid={`tour-delete-${t.id}`}
              className="absolute top-4 right-4 p-1 opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ color: "var(--error)" }}
            >
              <Trash2 size={14} />
            </button>
            <h3 className="font-serif-display text-xl mb-2 pr-6">{t.name}</h3>
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>
              {fmtDate(t.start_date)} – {fmtDate(t.end_date)}
            </div>
            {t.location && (
              <div className="text-sm flex items-center gap-1 mt-1" style={{ color: "var(--text-muted)" }}>
                <MapPin size={12} /> {t.location}
              </div>
            )}
          </Link>
        ))}
      </div>

      <PerformancesSection />

      {showForm && (
        <TourForm onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); }} />
      )}
    </div>
  );
}
