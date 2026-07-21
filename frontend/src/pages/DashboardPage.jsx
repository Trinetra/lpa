import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import { IndianRupee, TrendingUp, TrendingDown, Users as UsersIcon, Clock } from "lucide-react";

function StatCard({ label, value, icon: Icon, tone, testid }) {
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
    </div>
  );
}

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/dashboard").then((r) => setData(r.data)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div data-testid="dashboard-loading" className="uppercase-label">Loading…</div>;
  if (!data) return null;

  const studentsOwing = data.students.filter((s) => s.balance_due > 0);

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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Students" value={data.total_students} icon={UsersIcon} testid="stat-students" />
        <StatCard label="Total billed" value={fmt(data.total_billed)} icon={TrendingUp} testid="stat-billed" />
        <StatCard label="Total paid" value={fmt(data.total_paid)} icon={IndianRupee} tone="var(--success)" testid="stat-paid" />
        <StatCard label="Balance due" value={fmt(data.total_due)} icon={TrendingDown} tone={data.total_due > 0 ? "var(--error)" : "var(--text)"} testid="stat-due" />
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
                  {fmt(s.balance_due)}
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
                    {c.class_date} · {c.hours}h @ ₹{c.rate}/h
                  </div>
                </div>
              </div>
              <div className="font-serif-display" style={{ color: "var(--primary)" }}>
                {fmt(c.amount)}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
