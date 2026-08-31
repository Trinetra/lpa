import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { fmtDate } from "@/lib/utils";
import AuthImage from "@/components/AuthImage";
import { toast } from "sonner";
import {
  IndianRupee, TrendingUp, TrendingDown, Users as UsersIcon, Clock,
  CalendarClock, ListChecks, ArrowRight, AlertTriangle, PlaneTakeoff, Loader2,
} from "lucide-react";

const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const fmtTime = (t) => {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, "0")} ${period}`;
};
const fmtDueDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "");

function StatCard({ label, value, secondary, icon: Icon, tone, testid }) {
  return (
    <div data-testid={testid} className="surface p-6">
      <div className="flex items-center justify-between mb-4">
        <span className="uppercase-label">{label}</span>
        <Icon size={16} strokeWidth={1.5} style={{ color: tone || "var(--text-muted)" }} />
      </div>
      <div
        className="font-serif-display text-3xl"
        style={{ color: tone || "var(--text)" }}
      >
        {value}
      </div>
      {secondary && (
        <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{secondary}</div>
      )}
    </div>
  );
}

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const CURRENCY_SYMBOLS = { INR: "₹", EUR: "€", USD: "$", GBP: "£" };
const fmtCur = (n, currency) => `${CURRENCY_SYMBOLS[currency] || currency + " "}${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

// A deliberate, visible on/off switch for a temporary whole-studio pause —
// e.g. while she's travelling. While on: the 30-min-before class reminder
// emails stop going out, and every student's schedule/calendar view and
// reschedule-request flow show a "classes are paused" state instead of
// their normal data (nothing is deleted — schedule_blocks and
// class_occurrences are untouched, so turning it back off just resumes
// exactly where things left off).
function SuspensionCard({ suspended, onChanged }) {
  const [toggling, setToggling] = useState(false);

  const toggle = async () => {
    const next = !suspended;
    if (next && !window.confirm("Pause classes for every student? Reminder emails will stop and students won't see their schedule until you turn this back on.")) {
      return;
    }
    setToggling(true);
    try {
      const { data } = await api.post("/classes-suspension", { suspended: next });
      onChanged(data.classes_suspended);
      toast.success(data.classes_suspended ? "Classes paused" : "Classes resumed");
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't update that");
    } finally {
      setToggling(false);
    }
  };

  return (
    <div
      data-testid="classes-suspension-card"
      className="surface p-6 flex items-center justify-between gap-4 flex-wrap"
      style={suspended ? { borderColor: "var(--error)", borderWidth: 1, borderStyle: "solid" } : undefined}
    >
      <div className="flex items-center gap-3">
        <PlaneTakeoff size={20} strokeWidth={1.5} style={{ color: suspended ? "var(--error)" : "var(--text-muted)" }} />
        <div>
          <div className="font-serif-display text-xl">{suspended ? "Classes are paused" : "Classes are running"}</div>
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>
            {suspended
              ? "Reminder emails are off and students can't see their schedule. Turn this off when you're back."
              : "Pause everything temporarily — e.g. while you're travelling."}
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={toggle}
        disabled={toggling}
        data-testid="classes-suspension-toggle"
        role="switch"
        aria-checked={suspended}
        className="btn-pill flex items-center gap-2 shrink-0"
        style={suspended ? { background: "var(--error)", color: "#fff" } : undefined}
      >
        {toggling ? <Loader2 size={14} className="animate-spin" /> : null}
        {suspended ? "Resume classes" : "Pause classes"}
      </button>
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => api.get("/dashboard").then((r) => setData(r.data)).finally(() => setLoading(false));
    load();
    // A PWA left open in the background can sit on a stale dashboard
    // indefinitely — refetch on refocus so "upcoming today" (time-sensitive)
    // and anything changed elsewhere/on another device shows up without
    // needing to fully close and reopen the app.
    const onFocus = () => load();
    const onVisibility = () => { if (document.visibilityState === "visible") load(); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  if (loading) return <div data-testid="dashboard-loading" className="uppercase-label">Loading…</div>;
  if (!data) return null;

  const studentsOwing = data.students.filter((s) => s.balance_due > 0);
  const jsDay = new Date().getDay(); // 0=Sunday..6=Saturday
  const todayName = DAY_NAMES[jsDay === 0 ? 6 : jsDay - 1]; // convert to 0=Monday..6=Sunday

  const totals = data.totals_by_currency || [];
  const inrTotals = totals.find((t) => t.currency === "INR") || { total_billed: 0, total_paid: 0, total_due: 0 };
  const otherTotals = totals.filter((t) => t.currency !== "INR");
  const secondaryLine = (field) =>
    otherTotals.length > 0
      ? otherTotals.map((t) => `+ ${fmtCur(t[field], t.currency)}`).join("  ")
      : null;

  return (
    <div data-testid="dashboard-page" className="space-y-10">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Overview</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">
            Your studio at a glance
          </h1>
        </div>
        <Link to="/classes" data-testid="log-class-cta" className="btn-pill">
          Log a class
        </Link>
      </header>

      <SuspensionCard
        suspended={!!data.classes_suspended}
        onChanged={(next) => setData((prev) => ({ ...prev, classes_suspended: next }))}
      />

      {(data.shortcuts?.length > 0) && (
        <section data-testid="dashboard-shortcuts">
          <div className="uppercase-label mb-3">Shortcuts</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {data.shortcuts.map((s) => (
              <Link
                key={s.dest_key}
                to={s.path}
                data-testid={`shortcut-${s.dest_key.replace(/[:/]/g, "-")}`}
                className="surface surface-hover p-4 flex items-center justify-between gap-2"
              >
                <span className="text-sm truncate">{s.label}</span>
                <ArrowRight size={14} strokeWidth={1.5} style={{ color: "var(--text-muted)" }} className="shrink-0" />
              </Link>
            ))}
          </div>
        </section>
      )}

      {(data.today_classes?.length > 0 || data.todos_due?.length > 0) && (
        <section data-testid="dashboard-today" className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="surface p-6">
            <div className="flex items-center gap-2 mb-4">
              <CalendarClock size={16} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
              <div className="uppercase-label">Upcoming today · {todayName}</div>
            </div>
            {data.today_classes.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No more classes scheduled today.</p>
            ) : (
              <div className="space-y-3">
                {data.today_classes.map((c) => (
                  <div key={c.id} data-testid={`today-class-${c.id}`} className="flex items-center justify-between gap-3">
                    <span className="text-sm truncate flex items-center gap-2">
                      {c.is_one_off && (
                        <span title="One-off (doesn't repeat)" style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--success)", display: "inline-block" }} />
                      )}
                      {c.student_names.join(", ") || "Class"}
                    </span>
                    <span className="text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
                      {fmtTime(c.start_time)} – {fmtTime(c.end_time)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="surface p-6">
            <div className="flex items-center gap-2 mb-4">
              <ListChecks size={16} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
              <div className="uppercase-label">Tour to-dos due</div>
            </div>
            {data.todos_due.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>Nothing due — you're all caught up.</p>
            ) : (
              <div className="space-y-3">
                {data.todos_due.map((t) => (
                  <Link
                    key={t.id}
                    to={`/tours/${t.tour_id}?tab=todos`}
                    data-testid={`todo-due-${t.id}`}
                    className="flex items-center justify-between gap-3 hover:text-[color:var(--primary)] transition-colors"
                  >
                    <span className="text-sm truncate flex items-center gap-2">
                      {t.overdue && <AlertTriangle size={13} style={{ color: "var(--error)" }} className="shrink-0" />}
                      {t.text}
                    </span>
                    <span className="text-xs shrink-0" style={{ color: t.overdue ? "var(--error)" : "var(--text-muted)" }}>
                      {t.tour_name} · {fmtDueDate(t.due_date)}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Students" value={data.total_students} icon={UsersIcon} testid="stat-students" />
        <StatCard label="Total billed" value={fmt(inrTotals.total_billed)} secondary={secondaryLine("total_billed")}
          icon={TrendingUp} testid="stat-billed" />
        <StatCard label="Total paid" value={fmt(inrTotals.total_paid)} secondary={secondaryLine("total_paid")}
          icon={IndianRupee} tone="var(--success)" testid="stat-paid" />
        <StatCard label="Balance due" value={fmt(inrTotals.total_due)} secondary={secondaryLine("total_due")}
          icon={TrendingDown} tone={inrTotals.total_due > 0 ? "var(--error)" : "var(--text)"} testid="stat-due" />
      </div>

      <section>
        <div className="flex items-end justify-between mb-4">
          <div>
            <div className="uppercase-label mb-1">Outstanding by student</div>
            <h2 className="font-serif-display text-2xl">Who owes you</h2>
          </div>
          <Link to="/students" className="btn-ghost text-xs" data-testid="view-students-link">
            View all
          </Link>
        </div>
        <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
          {data.students.length === 0 && (
            <div className="p-8 text-center" style={{ color: "var(--text-muted)" }}>
              No students yet. <Link to="/students" className="underline">Add your first student.</Link>
            </div>
          )}
          {data.students.length > 0 && studentsOwing.length === 0 && (
            <div className="p-8 text-center" style={{ color: "var(--text-muted)" }}>
              Nobody owes you right now.
            </div>
          )}
          {studentsOwing.map((s) => (
            <div
              key={s.student_id}
              data-testid={`due-row-${s.student_id}`}
              className="flex items-center justify-between px-6 py-4 gap-4"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-4 min-w-0">
                <div className="w-11 h-11 rounded-full overflow-hidden shrink-0"
                     style={{ background: "var(--surface-2)" }}>
                  <AuthImage
                    path={s.photo_path}
                    className="w-full h-full object-cover"
                    fallback={
                      <div className="w-full h-full flex items-center justify-center font-serif-display text-lg"
                        style={{ color: "var(--primary)" }}>
                        {(s.name || "?").charAt(0)}
                      </div>
                    }
                  />
                </div>
                <div className="min-w-0">
                  <div className="truncate">{s.name}</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {s.level || "—"} · {s.classes_count} classes · {s.hours_total}h
                  </div>
                </div>
              </div>
              <div className="text-right shrink-0">
                <div
                  className="font-serif-display text-lg"
                  style={{ color: s.balance_due > 0 ? "var(--error)" : "var(--success)" }}
                >
                  {fmtCur(s.balance_due, s.currency)}
                </div>
                <div className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
                  {s.balance_due > 0 ? "Due" : "Cleared"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="flex items-end justify-between mb-4">
          <div>
            <div className="uppercase-label mb-1">Recent activity</div>
            <h2 className="font-serif-display text-2xl">Last classes logged</h2>
          </div>
          <Link to="/classes" className="btn-ghost text-xs" data-testid="view-classes-link">
            View all
          </Link>
        </div>
        <div className="surface">
          {data.recent_classes.length === 0 && (
            <div className="p-8 text-center" style={{ color: "var(--text-muted)" }}>
              No classes logged yet.
            </div>
          )}
          {data.recent_classes.map((c) => (
            <div
              key={c.id}
              data-testid={`recent-class-${c.id}`}
              className="flex items-center justify-between px-6 py-3"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-3">
                <Clock size={14} strokeWidth={1.5} style={{ color: "var(--text-muted)" }} />
                <div>
                  <div className="text-sm">{c.student_name}</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {fmtDate(c.class_date)} · {c.hours}h @ {fmtCur(c.rate, c.currency)}/h
                  </div>
                </div>
              </div>
              <div className="font-serif-display" style={{ color: "var(--primary)" }}>
                {fmtCur(c.amount, c.currency)}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
