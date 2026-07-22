import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, X, MapPin, Trash2 } from "lucide-react";
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

      {showForm && (
        <TourForm onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); }} />
      )}
    </div>
  );
}
