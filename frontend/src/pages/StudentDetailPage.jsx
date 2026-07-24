import React, { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import { ArrowLeft, Phone, Mail, Calendar } from "lucide-react";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

export default function StudentDetailPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const [student, setStudent] = useState(null);
  const [summary, setSummary] = useState(null);
  const [classes, setClasses] = useState([]);
  const [payments, setPayments] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get(`/students/${id}`),
      api.get(`/students/${id}/summary`),
      api.get("/classes", { params: { student_id: id } }),
      api.get("/payments", { params: { student_id: id } }),
    ])
      .then(([s, sum, c, p]) => {
        setStudent(s.data);
        setSummary(sum.data);
        setClasses(c.data);
        setPayments(p.data);
      })
      .catch(() => nav("/students"));
  }, [id, nav]);

  if (!student) return <div className="uppercase-label">Loading…</div>;

  // Distinct topics from the last 5 classes (already sorted newest-first by
  // the API) — a quick "where did we leave off" glance without needing a
  // full curriculum/syllabus model.
  const recentTopics = [...new Set(classes.slice(0, 5).flatMap((c) => c.topics || []))];

  return (
    <div data-testid="student-detail-page" className="space-y-8">
      <Link to="/students" className="inline-flex items-center gap-2 text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
        <ArrowLeft size={12} /> Back to roster
      </Link>

      <header className="surface p-6 flex items-center gap-6">
        <div className="w-24 h-24 rounded-full overflow-hidden shrink-0" style={{ background: "var(--surface-2)" }}>
          <AuthImage
            path={student.photo_path}
            className="w-full h-full object-cover"
            fallback={
              <div className="w-full h-full flex items-center justify-center font-serif-display text-3xl" style={{ color: "var(--primary)" }}>
                {(student.name || "?").charAt(0)}
              </div>
            }
          />
        </div>
        <div className="flex-1 min-w-0">
          <div className="uppercase-label mb-1">{student.level || "Student"}</div>
          <h1 className="font-serif-display text-3xl">{student.name}</h1>
          <div className="flex flex-wrap gap-4 mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
            {student.phone && <span className="flex items-center gap-1"><Phone size={12} /> {student.phone}</span>}
            {student.email && <span className="flex items-center gap-1"><Mail size={12} /> {student.email}</span>}
            {student.joined_on && <span className="flex items-center gap-1"><Calendar size={12} /> since {student.joined_on}</span>}
          </div>
          {student.description && (
            <p className="mt-3 text-sm" style={{ color: "var(--text-muted)" }}>{student.description}</p>
          )}
        </div>
        <div className="text-right shrink-0 hidden md:block">
          <div className="uppercase-label">Rate</div>
          <div className="font-serif-display text-2xl">{fmt(student.hourly_rate)}/hr</div>
        </div>
      </header>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="surface p-4"><div className="uppercase-label">Classes</div><div className="font-serif-display text-2xl">{summary.classes_count}</div></div>
          <div className="surface p-4"><div className="uppercase-label">Hours</div><div className="font-serif-display text-2xl">{summary.hours_total}</div></div>
          <div className="surface p-4"><div className="uppercase-label">Billed</div><div className="font-serif-display text-2xl">{fmt(summary.total_billed)}</div></div>
          <div className="surface p-4"><div className="uppercase-label">Due</div><div className="font-serif-display text-2xl" style={{ color: summary.balance_due > 0 ? "var(--error)" : "var(--success)" }}>{fmt(summary.balance_due)}</div></div>
        </div>
      )}

      {recentTopics.length > 0 && (
        <section>
          <div className="uppercase-label mb-3">Recently taught</div>
          <div className="surface p-4 flex flex-wrap gap-2">
            {recentTopics.map((t) => (
              <span key={t} className="text-xs px-2.5 py-1 rounded-full"
                style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)", border: "1px solid rgba(212,132,100,0.4)" }}>
                {t}
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <div className="uppercase-label mb-3">Class history</div>
        <div className="surface">
          {classes.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No classes yet.</div>
          )}
          {classes.map((c) => (
            <div key={c.id} className="flex justify-between px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
              <div>
                <div>{c.class_date}</div>
                {c.topics && c.topics.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {c.topics.map((t) => (
                      <span key={t} className="text-[10px] px-2 py-0.5 rounded-full"
                        style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)" }}>
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                {c.notes && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{c.notes}</div>}
              </div>
              <div className="text-right">
                <div>{c.hours}h · {fmt(c.rate)}/h</div>
                <div className="font-serif-display" style={{ color: "var(--primary)" }}>{fmt(c.amount)}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="uppercase-label mb-3">Payments</div>
        <div className="surface">
          {payments.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No payments yet.</div>
          )}
          {payments.map((p) => (
            <div key={p.id} className="flex justify-between px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
              <div>
                <div>{p.paid_on}</div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>{p.method}</div>
              </div>
              <div className="font-serif-display" style={{ color: "var(--success)" }}>{fmt(p.amount)}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
