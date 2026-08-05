import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { fmtCurrency } from "@/pages/StudentsPage";
import { Plus, X, Trash2 } from "lucide-react";
import { toast } from "sonner";

const CURRENCIES = ["INR", "EUR", "USD", "GBP"];

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

function EventForm({ onClose, onSaved }) {
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/events", {
        name,
        start_date: startDate,
        end_date: endDate || startDate,
        price: price === "" ? 0 : Number(price),
        currency,
      });
      toast.success("Event created");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed to create event");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="event-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">New event</h3>
          <button type="button" onClick={onClose} data-testid="event-form-close" className="p-1"><X size={18} /></button>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Event name</span>
          <input required value={name} onChange={(e) => setName(e.target.value)}
            data-testid="event-name-input"
            placeholder="e.g. Bharatanatyam Intensive"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Start date</span>
            <input required type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
              data-testid="event-start-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">End date</span>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
              data-testid="event-end-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3 mb-6">
          <label className="block">
            <span className="uppercase-label block mb-1">Price</span>
            <input type="number" min="0" value={price} onChange={(e) => setPrice(e.target.value)}
              data-testid="event-price-input"
              placeholder="0"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Currency</span>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}
              data-testid="event-currency-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}>
              {CURRENCIES.map((c) => (
                <option key={c} value={c} style={{ background: "var(--surface)" }}>{c}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-ghost" data-testid="event-cancel-btn">Cancel</button>
          <button type="submit" disabled={saving} className="btn-pill" data-testid="event-save-btn">
            {saving ? "Creating…" : "Create event"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function EventsPage() {
  const [events, setEvents] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const load = () => {
    api.get("/events").then((r) => setEvents(r.data)).catch(() => setEvents([]));
  };

  useEffect(() => { load(); }, []);

  const remove = async (e, eventId, name) => {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm(`Delete "${name}"? This removes all its registrations too.`)) return;
    try {
      await api.delete(`/events/${eventId}`);
      toast.success("Event deleted");
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    }
  };

  if (events === null) return <div data-testid="events-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="events-page" className="space-y-8">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Workshops</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Events</h1>
        </div>
        <button onClick={() => setShowForm(true)} data-testid="new-event-btn" className="btn-pill flex items-center gap-2">
          <Plus size={16} /> New event
        </button>
      </header>

      {events.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>
          No events yet. <button onClick={() => setShowForm(true)} className="underline">Create your first event.</button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {events.map((ev) => (
          <Link
            key={ev.id}
            to={`/events/${ev.id}`}
            data-testid={`event-card-${ev.id}`}
            className="surface surface-hover p-5 block relative group"
          >
            <button
              onClick={(e) => remove(e, ev.id, ev.name)}
              data-testid={`event-delete-${ev.id}`}
              className="absolute top-4 right-4 p-1 opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ color: "var(--error)" }}
            >
              <Trash2 size={14} />
            </button>
            <div className="flex items-center gap-2 mb-2 pr-6">
              <h3 className="font-serif-display text-xl">{ev.name}</h3>
              <span
                className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full shrink-0"
                style={{
                  color: ev.status === "published" ? "var(--success)" : "var(--text-muted)",
                  border: `1px solid ${ev.status === "published" ? "var(--success)" : "var(--border)"}`,
                }}
              >
                {ev.status}
              </span>
            </div>
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>
              {fmtDate(ev.start_date)}{ev.end_date && ev.end_date !== ev.start_date ? ` – ${fmtDate(ev.end_date)}` : ""}
            </div>
            <div className="text-sm mt-1" style={{ color: "var(--primary)" }}>
              {fmtCurrency(ev.price, ev.currency)}
            </div>
          </Link>
        ))}
      </div>

      {showForm && (
        <EventForm onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); }} />
      )}
    </div>
  );
}
