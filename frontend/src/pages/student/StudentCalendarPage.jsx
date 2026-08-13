import React, { useEffect, useMemo, useState } from "react";
import { studentApi } from "@/lib/api";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

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

function buildMonthGrid(year, month) {
  const first = new Date(year, month, 1);
  const firstWeekday = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - firstWeekday);
  const days = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    days.push(d);
  }
  return days;
}

function DayModal({ date, occurrences, onClose }) {
  const dayOccs = occurrences.filter((o) => o.date === date);
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div data-testid="portal-calendar-day-modal" className="surface w-full max-w-lg max-h-[85vh] overflow-y-auto p-6">
        <div className="flex items-start justify-between mb-3">
          <h2 className="font-serif-display text-2xl">{fmtLongDate(date)}</h2>
          <button type="button" onClick={onClose} data-testid="portal-calendar-day-modal-close">
            <X size={20} />
          </button>
        </div>
        {dayOccs.length === 0 ? (
          <div className="text-sm py-3" style={{ color: "var(--text-muted)" }}>No classes on this date.</div>
        ) : (
          dayOccs.map((occ) => (
            <div key={occ.id} className="py-3" style={{ borderTop: "1px solid var(--border)" }}
              data-testid={`portal-calendar-occ-${occ.id}`}>
              <div className="text-sm">{fmt12h(occ.start_time)}–{fmt12h(occ.end_time)}</div>
              {occ.origin === "rescheduled" && (
                <div className="text-[10px] uppercase tracking-widest mt-1" style={{ color: "var(--primary)" }}>Rescheduled</div>
              )}
              {occ.notes && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{occ.notes}</div>}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function StudentCalendarPage() {
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });
  const [occurrences, setOccurrences] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState(null);

  const grid = useMemo(() => buildMonthGrid(cursor.year, cursor.month), [cursor]);
  const rangeStart = toISO(grid[0]);
  const rangeEnd = toISO(grid[grid.length - 1]);
  const todayISO = toISO(new Date());

  const load = () => {
    setLoading(true);
    studentApi.get("/student/calendar", { params: { start: rangeStart, end: rangeEnd } })
      .then((r) => setOccurrences(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [rangeStart, rangeEnd]); // eslint-disable-line react-hooks/exhaustive-deps

  const byDate = useMemo(() => {
    const m = {};
    for (const o of occurrences) (m[o.date] ||= []).push(o);
    return m;
  }, [occurrences]);

  const goPrev = () => setCursor(({ year, month }) => (month === 0 ? { year: year - 1, month: 11 } : { year, month: month - 1 }));
  const goNext = () => setCursor(({ year, month }) => (month === 11 ? { year: year + 1, month: 0 } : { year, month: month + 1 }));
  const goToday = () => { const now = new Date(); setCursor({ year: now.getFullYear(), month: now.getMonth() }); };

  return (
    <div data-testid="portal-calendar-page" className="space-y-6">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Your classes</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Calendar</h1>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={goPrev} className="btn-ghost" data-testid="portal-calendar-prev-btn"><ChevronLeft size={18} /></button>
          <button type="button" onClick={goToday} className="btn-ghost text-xs uppercase-label" data-testid="portal-calendar-today-btn">Today</button>
          <button type="button" onClick={goNext} className="btn-ghost" data-testid="portal-calendar-next-btn"><ChevronRight size={18} /></button>
        </div>
      </header>

      <div className="font-serif-display text-2xl">{MONTH_NAMES[cursor.month]} {cursor.year}</div>

      {loading ? (
        <div data-testid="portal-calendar-loading" className="uppercase-label">Loading…</div>
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
              const dayOccs = byDate[iso] || [];
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => setSelectedDate(iso)}
                  data-testid={`portal-calendar-cell-${iso}`}
                  className="text-left p-2 min-h-[80px] flex flex-col gap-1"
                  style={{
                    borderTop: "1px solid var(--border)",
                    borderLeft: i % 7 !== 0 ? "1px solid var(--border)" : "none",
                    opacity: inMonth ? 1 : 0.35,
                    background: isToday ? "rgba(212,132,100,0.06)" : "transparent",
                  }}
                >
                  <span className="text-sm" style={{ fontWeight: isToday ? 700 : 400, color: isToday ? "var(--primary)" : "var(--text)" }}>
                    {d.getDate()}
                  </span>
                  <div className="space-y-0.5">
                    {dayOccs.slice(0, 2).map((o) => (
                      <div key={o.id} className="text-[10px] truncate px-1 rounded"
                        style={{ background: "rgba(212,132,100,0.12)", color: "var(--primary)" }}>
                        {fmt12h(o.start_time)}
                      </div>
                    ))}
                    {dayOccs.length > 2 && (
                      <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>+{dayOccs.length - 2} more</div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {selectedDate && (
        <DayModal date={selectedDate} occurrences={occurrences} onClose={() => setSelectedDate(null)} />
      )}
    </div>
  );
}
