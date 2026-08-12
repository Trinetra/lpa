import React, { useEffect, useState } from "react";
import { studentApi } from "@/lib/api";
import { useTheme } from "@/context/ThemeContext";
import StudentAudioPlayer from "@/components/student/StudentAudioPlayer";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

const TooltipDark = ({ active, payload, label }) => {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0];
  return (
    <div className="surface px-3 py-2 text-xs" style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}>
      <div className="uppercase-label mb-1">{label}</div>
      <div className="flex items-center gap-2">
        <span style={{ color: "var(--text-muted)" }}>Classes</span>
        <span className="ml-auto" style={{ color: "var(--text)" }}>{p.value}</span>
      </div>
      {p.payload?.hours != null && (
        <div className="flex items-center gap-2">
          <span style={{ color: "var(--text-muted)" }}>Hours</span>
          <span className="ml-auto" style={{ color: "var(--text)" }}>{p.payload.hours}</span>
        </div>
      )}
    </div>
  );
};

function MonthlyClassesChart() {
  const [months, setMonths] = useState(6);
  const [monthly, setMonthly] = useState(null);
  const { theme } = useTheme();

  const axisColor = theme === "light" ? "#7a6f5f" : "#a89886";
  const gridColor = theme === "light" ? "rgba(44,41,38,0.09)" : "rgba(245,230,211,0.08)";
  const cursorFill = theme === "light" ? "rgba(176,104,70,0.10)" : "rgba(212,132,100,0.08)";
  const primary = theme === "light" ? "#B06846" : "#D48464";

  useEffect(() => {
    studentApi.get("/student/progress-monthly", { params: { months } }).then((r) => setMonthly(r.data));
  }, [months]);

  return (
    <section className="surface p-6">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-1">
        <div>
          <div className="uppercase-label mb-1">Consistency</div>
          <h2 className="font-serif-display text-2xl">Classes per month</h2>
        </div>
        <select
          value={months}
          onChange={(e) => setMonths(Number(e.target.value))}
          data-testid="portal-progress-months-select"
          className="bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
          style={{ background: "var(--surface)" }}
        >
          {[3, 6, 12].map((m) => (
            <option key={m} value={m} style={{ background: "var(--surface)" }}>Last {m} months</option>
          ))}
        </select>
      </div>
      <div style={{ width: "100%", height: 260 }} className="mt-4" data-testid="portal-progress-chart">
        {monthly && (
          <ResponsiveContainer>
            <BarChart data={monthly.series} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
              <XAxis dataKey="month" stroke={axisColor} tick={{ fontSize: 11 }} />
              <YAxis stroke={axisColor} tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip content={<TooltipDark />} cursor={{ fill: cursorFill }} />
              <Bar dataKey="classes" fill={primary} radius={[4, 4, 0, 0]} name="Classes" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

export default function StudentProgressPage() {
  const [classes, setClasses] = useState(null);

  useEffect(() => {
    studentApi.get("/student/progress").then((r) => setClasses(r.data));
  }, []);

  if (!classes) return <div data-testid="portal-progress-loading" className="uppercase-label">Loading…</div>;

  const recentTopics = [...new Set(classes.slice(0, 5).flatMap((c) => c.topics || []))];

  return (
    <div data-testid="portal-progress-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">What you've learned</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Progress</h1>
      </header>

      <MonthlyClassesChart />

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
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No classes logged yet.</div>
          )}
          {classes.map((c) => (
            <div key={c.id} className="flex justify-between gap-4 px-6 py-3 text-sm" style={{ borderTop: "1px solid var(--border)" }}>
              <div className="min-w-0">
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
                {c.notes && (
                  <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{c.notes}</div>
                )}
                {c.has_audio && (
                  <div className="mt-1.5">
                    <StudentAudioPlayer classId={c.id} durationSeconds={c.audio_duration_seconds} testid={`portal-audio-${c.id}`} />
                    {c.transcript && (
                      <p className="text-xs mt-1 italic" style={{ color: "var(--text-muted)" }}>"{c.transcript}"</p>
                    )}
                  </div>
                )}
              </div>
              <div className="shrink-0" style={{ color: "var(--text-muted)" }}>{c.hours}h</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
