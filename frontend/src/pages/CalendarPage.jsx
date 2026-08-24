import React, { useEffect, useMemo, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { ChevronLeft, ChevronRight, X, CalendarClock, Repeat1, AlertTriangle, RotateCcw } from "lucide-react";
import { toast } from "sonner";

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const pad2 = (n) => String(n).padStart(2, "0");
const toISO = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const fmt12h = (t) => {
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12}${period}` : `${h12}:${String(m).padStart(2, "0")}${period}`;
};
const fmtLongDate = (iso) => {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
};
const fmtShortDate = (iso) => {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};

// Describes what actually changed about a reschedule — a pure time change on
// the same date reads as "was 2PM–3PM", a date change (same time) as "was
// Wed, 7 Oct", and a change to both combines them — rather than always
// implying the date moved.
function describeReschedule(occ) {
  if (!occ.moved_from_date) return null;
  const dateChanged = occ.moved_from_date !== occ.date;
  const timeChanged = occ.moved_from_start_time !== occ.start_time || occ.moved_from_end_time !== occ.end_time;
  const oldTime = occ.moved_from_start_time && occ.moved_from_end_time
    ? `${fmt12h(occ.moved_from_start_time)}–${fmt12h(occ.moved_from_end_time)}` : null;
  const oldDate = fmtShortDate(occ.moved_from_date);
  if (dateChanged && timeChanged) return `Was ${oldDate}, ${oldTime}`;
  if (dateChanged) return `Was ${oldDate}`;
  if (timeChanged) return `Was ${oldTime}`;
  return null;
}

// Monday-first 6-week grid covering the given month, including lead/trail days.
function buildMonthGrid(year, month) {
  const first = new Date(year, month, 1);
  const firstWeekday = (first.getDay() + 6) % 7; // 0=Mon
  const start = new Date(year, month, 1 - firstWeekday);
  const days = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    days.push(d);
  }
  return days;
}

function RescheduleForm({ occurrence, onClose, onDone }) {
  const [date, setDate] = useState(occurrence.date);
  const [startTime, setStartTime] = useState(occurrence.start_time);
  const [endTime, setEndTime] = useState(occurrence.end_time);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post(`/calendar/occurrences/${occurrence.id}/reschedule`, {
        date, start_time: startTime, end_time: endTime,
      });
      toast.success("Class moved — the student has been notified");
      onDone();
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't reschedule");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid={`occ-reschedule-form-${occurrence.id}`} className="mt-3 space-y-3 p-3 rounded"
      style={{ border: "1px solid var(--border)" }}>
      <div className="grid grid-cols-3 gap-2">
        <label className="block">
          <span className="uppercase-label block mb-1 text-[10px]">Date</span>
          <input type="date" required value={date} onChange={(e) => setDate(e.target.value)}
            data-testid={`occ-reschedule-date-${occurrence.id}`}
            className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1 text-[10px]">Start</span>
          <input type="time" required value={startTime} onChange={(e) => setStartTime(e.target.value)}
            data-testid={`occ-reschedule-start-${occurrence.id}`}
            className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1 text-[10px]">End</span>
          <input type="time" required value={endTime} onChange={(e) => setEndTime(e.target.value)}
            data-testid={`occ-reschedule-end-${occurrence.id}`}
            className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
        </label>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-ghost text-xs" data-testid={`occ-reschedule-cancel-${occurrence.id}`}>
          Cancel
        </button>
        <button type="submit" disabled={saving} className="btn-pill text-xs" data-testid={`occ-reschedule-save-${occurrence.id}`}>
          {saving ? "Saving…" : "Move this class"}
        </button>
      </div>
    </form>
  );
}

function OccurrenceRow({ occ, onCancel, onRestore, onUndoReschedule, onReload }) {
  const [rescheduling, setRescheduling] = useState(false);
  const isCancelled = occ.status === "cancelled";
  const isMoved = occ.origin === "rescheduled";
  const rescheduleNote = isMoved ? describeReschedule(occ) : null;

  return (
    <div data-testid={`occ-row-${occ.id}`} className="py-3" style={{ borderTop: "1px solid var(--border)" }}>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm">
            <span style={{ textDecoration: isCancelled ? "line-through" : "none" }}>
              {fmt12h(occ.start_time)}–{fmt12h(occ.end_time)}
            </span>
            {rescheduleNote && (
              <span className="text-[10px] uppercase tracking-widest flex items-center gap-1" style={{ color: "var(--primary)" }}>
                <Repeat1 size={10} /> {rescheduleNote}
              </span>
            )}
            {isCancelled && (
              <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--error)" }}>Cancelled</span>
            )}
          </div>
          <div className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
            {occ.student_names?.length ? occ.student_names.join(", ") : "No students"}
          </div>
          {occ.notes && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{occ.notes}</div>}
        </div>
        {!isCancelled && !rescheduling && (
          <div className="flex items-center gap-2 flex-wrap sm:shrink-0">
            {isMoved && (
              <button type="button" onClick={() => onUndoReschedule(occ.id)} className="btn-ghost text-xs flex items-center gap-1"
                data-testid={`occ-undo-reschedule-btn-${occ.id}`}>
                <RotateCcw size={12} /> Undo
              </button>
            )}
            <button type="button" onClick={() => setRescheduling(true)} className="btn-ghost text-xs"
              data-testid={`occ-reschedule-btn-${occ.id}`}>
              Reschedule
            </button>
            <button type="button" onClick={() => onCancel(occ.id)} className="btn-ghost text-xs" style={{ color: "var(--error)" }}
              data-testid={`occ-cancel-btn-${occ.id}`}>
              Cancel
            </button>
          </div>
        )}
        {isCancelled && (
          <button type="button" onClick={() => onRestore(occ.id)} className="btn-ghost text-xs flex items-center gap-1 sm:shrink-0"
            data-testid={`occ-restore-btn-${occ.id}`}>
            <RotateCcw size={12} /> Restore
          </button>
        )}
      </div>
      {rescheduling && (
        <RescheduleForm occurrence={occ} onClose={() => setRescheduling(false)} onDone={onReload} />
      )}
    </div>
  );
}

function PersonalEventForm({ date, onClose, onSaved }) {
  const [title, setTitle] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("10:00");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await api.post("/calendar/personal-events", {
        title, date, start_time: startTime, end_time: endTime, notes: notes || null,
      });
      if (data.clashes_with_classes) {
        toast.warning("Added — but this clashes with a class on this date. You'll need to reschedule it with the student.");
      } else {
        toast.success("Added to your calendar");
      }
      onSaved();
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="personal-event-form" className="mt-3 space-y-3 p-3 rounded"
      style={{ border: "1px solid var(--border)" }}>
      <label className="block">
        <span className="uppercase-label block mb-1 text-[10px]">Title</span>
        <input type="text" required value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Workshop at Kalakshetra"
          data-testid="personal-event-title-input"
          className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="uppercase-label block mb-1 text-[10px]">Start</span>
          <input type="time" required value={startTime} onChange={(e) => setStartTime(e.target.value)}
            data-testid="personal-event-start-input"
            className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
        </label>
        <label className="block">
          <span className="uppercase-label block mb-1 text-[10px]">End</span>
          <input type="time" required value={endTime} onChange={(e) => setEndTime(e.target.value)}
            data-testid="personal-event-end-input"
            className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
        </label>
      </div>
      <label className="block">
        <span className="uppercase-label block mb-1 text-[10px]">Notes (optional)</span>
        <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)}
          data-testid="personal-event-notes-input"
          className="w-full bg-transparent border border-white/10 rounded px-2 py-1.5 text-sm" />
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-ghost text-xs" data-testid="personal-event-cancel-btn">
          Cancel
        </button>
        <button type="submit" disabled={saving} className="btn-pill text-xs" data-testid="personal-event-save-btn">
          {saving ? "Saving…" : "Add event"}
        </button>
      </div>
    </form>
  );
}

function DayModal({ date, occurrences, events, onClose, onReload }) {
  const [addingEvent, setAddingEvent] = useState(false);
  const dayOccs = occurrences.filter((o) => o.date === date);
  const dayEvents = events.filter((e) => e.date === date);

  const cancel = async (id) => {
    if (!window.confirm("Cancel this one class? The student will be notified. This won't affect any other date.")) return;
    try {
      await api.post(`/calendar/occurrences/${id}/cancel`);
      toast.success("Cancelled");
      onReload();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't cancel");
    }
  };
  const restore = async (id) => {
    try {
      await api.post(`/calendar/occurrences/${id}/restore`);
      toast.success("Restored");
      onReload();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't restore");
    }
  };

  const undoReschedule = async (id) => {
    try {
      await api.post(`/calendar/occurrences/${id}/undo-reschedule`);
      toast.success("Reschedule undone");
      onReload();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't undo");
    }
  };

  const removeEvent = async (id) => {
    if (!window.confirm("Remove this event from your calendar?")) return;
    try {
      await api.delete(`/calendar/personal-events/${id}`);
      toast.success("Removed");
      onReload();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't remove");
    }
  };

  const activeCount = dayOccs.filter((o) => o.status === "scheduled").length;
  const hasPersonalClash = dayEvents.length > 0 && activeCount > 0;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div data-testid="calendar-day-modal" className="surface w-full max-w-lg max-h-[85vh] overflow-y-auto p-6">
        <div className="flex items-start justify-between mb-1">
          <h2 className="font-serif-display text-2xl">{fmtLongDate(date)}</h2>
          <button type="button" onClick={onClose} data-testid="calendar-day-modal-close">
            <X size={20} />
          </button>
        </div>

        {hasPersonalClash && (
          <div className="flex items-start gap-2 text-xs px-3 py-2 rounded mt-3"
            style={{ background: "rgba(212,132,100,0.12)", color: "var(--primary)" }}
            data-testid="calendar-day-clash-banner">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>
              You have a personal event this day and {activeCount} class{activeCount === 1 ? "" : "es"} still scheduled —
              reschedule {activeCount === 1 ? "it" : "them"} once you've spoken to the student{activeCount === 1 ? "" : "s"}.
            </span>
          </div>
        )}

        <section className="mt-5">
          <div className="uppercase-label mb-1">Classes</div>
          {dayOccs.length === 0 ? (
            <div className="text-sm py-3" style={{ color: "var(--text-muted)" }}>No classes on this date.</div>
          ) : (
            <div>
              {dayOccs.map((occ) => (
                <OccurrenceRow key={occ.id} occ={occ} onCancel={cancel} onRestore={restore}
                  onUndoReschedule={undoReschedule} onReload={onReload} />
              ))}
            </div>
          )}
        </section>

        <section className="mt-6">
          <div className="flex items-center justify-between mb-1">
            <div className="uppercase-label">Your events</div>
            {!addingEvent && (
              <button type="button" onClick={() => setAddingEvent(true)} className="btn-ghost text-xs"
                data-testid="calendar-add-event-btn">
                + Add event
              </button>
            )}
          </div>
          {dayEvents.length === 0 && !addingEvent && (
            <div className="text-sm py-2" style={{ color: "var(--text-muted)" }}>Nothing personal noted for this day.</div>
          )}
          {dayEvents.map((ev) => (
            <div key={ev.id} className="py-2 flex items-center justify-between gap-3" style={{ borderTop: "1px solid var(--border)" }}
              data-testid={`personal-event-row-${ev.id}`}>
              <div>
                <div className="text-sm">{ev.title}</div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {fmt12h(ev.start_time)}–{fmt12h(ev.end_time)}
                  {ev.notes && ` · ${ev.notes}`}
                </div>
              </div>
              <button type="button" onClick={() => removeEvent(ev.id)} className="btn-ghost text-xs" style={{ color: "var(--error)" }}
                data-testid={`personal-event-remove-${ev.id}`}>
                Remove
              </button>
            </div>
          ))}
          {addingEvent && (
            <PersonalEventForm date={date} onClose={() => setAddingEvent(false)} onSaved={onReload} />
          )}
        </section>
      </div>
    </div>
  );
}

export default function CalendarPage() {
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });
  const [occurrences, setOccurrences] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState(null);

  const grid = useMemo(() => buildMonthGrid(cursor.year, cursor.month), [cursor]);
  const rangeStart = toISO(grid[0]);
  const rangeEnd = toISO(grid[grid.length - 1]);
  const todayISO = toISO(new Date());

  const load = async () => {
    setLoading(true);
    try {
      const [occRes, evRes] = await Promise.all([
        api.get("/calendar/occurrences", { params: { start: rangeStart, end: rangeEnd } }),
        api.get("/calendar/personal-events", { params: { start: rangeStart, end: rangeEnd } }),
      ]);
      setOccurrences(occRes.data);
      setEvents(evRes.data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Failed to load calendar");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [rangeStart, rangeEnd]); // eslint-disable-line react-hooks/exhaustive-deps

  // Same staleness fix as SchedulePage — refetch on refocus so a reschedule
  // made elsewhere (or by the daily occurrence top-up) shows up without a
  // full app relaunch.
  useEffect(() => {
    const onFocus = () => load();
    const onVisibility = () => { if (document.visibilityState === "visible") load(); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [rangeStart, rangeEnd]); // eslint-disable-line react-hooks/exhaustive-deps

  const byDate = useMemo(() => {
    const m = {};
    for (const o of occurrences) {
      (m[o.date] ||= { occs: [], events: [] }).occs.push(o);
    }
    for (const e of events) {
      (m[e.date] ||= { occs: [], events: [] }).events.push(e);
    }
    return m;
  }, [occurrences, events]);

  const goPrev = () => setCursor(({ year, month }) => (month === 0 ? { year: year - 1, month: 11 } : { year, month: month - 1 }));
  const goNext = () => setCursor(({ year, month }) => (month === 11 ? { year: year + 1, month: 0 } : { year, month: month + 1 }));
  const goToday = () => { const now = new Date(); setCursor({ year: now.getFullYear(), month: now.getMonth() }); };

  return (
    <div data-testid="calendar-page" className="space-y-6">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Day by day</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Calendar</h1>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={goPrev} className="btn-ghost" data-testid="calendar-prev-btn"><ChevronLeft size={18} /></button>
          <button type="button" onClick={goToday} className="btn-ghost text-xs uppercase-label" data-testid="calendar-today-btn">Today</button>
          <button type="button" onClick={goNext} className="btn-ghost" data-testid="calendar-next-btn"><ChevronRight size={18} /></button>
        </div>
      </header>

      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        One-time changes made here only affect that date — your weekly <CalendarClock size={12} className="inline -mt-0.5" /> Schedule stays the master pattern.
      </p>

      <div className="font-serif-display text-2xl">{MONTH_NAMES[cursor.month]} {cursor.year}</div>

      {loading ? (
        <div data-testid="calendar-loading" className="uppercase-label">Loading…</div>
      ) : (
        <div className="surface overflow-hidden">
          <div className="grid grid-cols-7" style={{ borderBottom: "1px solid var(--border)" }}>
            {DAY_SHORT.map((d) => (
              <div key={d} className="uppercase-label text-center py-2 text-[10px]">{d}</div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {grid.map((d, i) => {
              const iso = toISO(d);
              const inMonth = d.getMonth() === cursor.month;
              const isToday = iso === todayISO;
              const cell = byDate[iso] || { occs: [], events: [] };
              const activeOccs = cell.occs.filter((o) => o.status === "scheduled");
              const hasClash = cell.events.length > 0 && activeOccs.length > 0;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => setSelectedDate(iso)}
                  data-testid={`calendar-cell-${iso}`}
                  className="text-left p-2 min-h-[92px] flex flex-col gap-1 transition-colors"
                  style={{
                    borderTop: "1px solid var(--border)",
                    borderLeft: i % 7 !== 0 ? "1px solid var(--border)" : "none",
                    opacity: inMonth ? 1 : 0.35,
                    background: isToday ? "rgba(212,132,100,0.06)" : "transparent",
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm" style={{ fontWeight: isToday ? 700 : 400, color: isToday ? "var(--primary)" : "var(--text)" }}>
                      {d.getDate()}
                    </span>
                    {hasClash && <AlertTriangle size={12} style={{ color: "var(--error)" }} data-testid={`calendar-clash-dot-${iso}`} />}
                  </div>
                  <div className="space-y-0.5">
                    {activeOccs.slice(0, 3).map((o) => (
                      <div key={o.id} className="text-[10px] truncate px-1 rounded"
                        style={{ background: "rgba(212,132,100,0.12)", color: "var(--primary)" }}>
                        {fmt12h(o.start_time)} {o.student_names?.[0] || ""}
                      </div>
                    ))}
                    {activeOccs.length > 3 && (
                      <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>+{activeOccs.length - 3} more</div>
                    )}
                    {cell.events.map((e) => (
                      <div key={e.id} className="text-[10px] truncate px-1 rounded" style={{ background: "var(--border)" }}>
                        {e.title}
                      </div>
                    ))}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {selectedDate && (
        <DayModal
          date={selectedDate}
          occurrences={occurrences}
          events={events}
          onClose={() => setSelectedDate(null)}
          onReload={load}
        />
      )}
    </div>
  );
}
