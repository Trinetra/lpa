import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTheme } from "@/context/ThemeContext";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, PieChart, Pie, Cell,
} from "recharts";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

const COLORS = ["#D48464", "#7C9082", "#D4B064", "#B85C5C", "#a67e60", "#4a7c8c", "#87604a"];

const TooltipDark = ({ active, payload, label, formatter }) => {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div
      className="surface px-3 py-2 text-xs"
      style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}
    >
      {label && <div className="uppercase-label mb-1">{label}</div>}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: p.color || p.payload?.fill }}
          />
          <span style={{ color: "var(--text-muted)" }}>{p.name}</span>
          <span className="ml-auto" style={{ color: "var(--text)" }}>
            {formatter ? formatter(p.value, p.name) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
};

export default function ChartsPage() {
  const [months, setMonths] = useState(6);
  const [monthly, setMonthly] = useState(null);
  const [byStudent, setByStudent] = useState(null);
  const { theme } = useTheme();

  // Recharts needs real color strings (not CSS vars) so we branch here.
  const axisColor = theme === "light" ? "#7a6f5f" : "#a89886";
  const gridColor = theme === "light" ? "rgba(44,41,38,0.09)" : "rgba(245,230,211,0.08)";
  const cursorFill = theme === "light" ? "rgba(176,104,70,0.10)" : "rgba(212,132,100,0.08)";
  const cursorStroke = theme === "light" ? "rgba(44,41,38,0.15)" : "rgba(245,230,211,0.15)";
  const primary = theme === "light" ? "#B06846" : "#D48464";
  const success = theme === "light" ? "#4D7358" : "#7C9082";

  useEffect(() => {
    api.get("/stats/monthly", { params: { months } }).then((r) => setMonthly(r.data));
  }, [months]);
  useEffect(() => {
    api.get("/stats/by-student").then((r) => setByStudent(r.data));
  }, []);

  return (
    <div data-testid="charts-page" className="space-y-10">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Analytics</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Studio charts</h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="uppercase-label">Range</span>
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            data-testid="months-range-select"
            className="bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
            style={{ background: "var(--surface)" }}
          >
            {[3, 6, 12].map((m) => (
              <option key={m} value={m} style={{ background: "var(--surface)" }}>
                Last {m} months
              </option>
            ))}
          </select>
        </div>
      </header>

      {/* Monthly Earnings */}
      <section className="surface p-6">
        <div className="uppercase-label mb-1">Monthly earnings</div>
        <h2 className="font-serif-display text-2xl mb-6">Revenue over time</h2>
        <div style={{ width: "100%", height: 300 }} data-testid="monthly-earnings-chart">
          {monthly && (
            <ResponsiveContainer>
              <BarChart data={monthly.series} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                <XAxis dataKey="month" stroke={axisColor} tick={{ fontSize: 11 }} />
                <YAxis stroke={axisColor} tick={{ fontSize: 11 }} />
                <Tooltip
                  content={<TooltipDark formatter={(v) => fmt(v)} />}
                  cursor={{ fill: cursorFill }}
                />
                <Bar dataKey="earnings" fill={primary} radius={[4, 4, 0, 0]} name="Earnings" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {/* Monthly Hours */}
      <section className="surface p-6">
        <div className="uppercase-label mb-1">Teaching hours</div>
        <h2 className="font-serif-display text-2xl mb-6">Hours taught per month</h2>
        <div style={{ width: "100%", height: 260 }} data-testid="monthly-hours-chart">
          {monthly && (
            <ResponsiveContainer>
              <LineChart data={monthly.series} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                <XAxis dataKey="month" stroke={axisColor} tick={{ fontSize: 11 }} />
                <YAxis stroke={axisColor} tick={{ fontSize: 11 }} />
                <Tooltip
                  content={<TooltipDark formatter={(v) => `${v}h`} />}
                  cursor={{ stroke: cursorStroke }}
                />
                <Line
                  type="monotone"
                  dataKey="hours"
                  stroke={success}
                  strokeWidth={2}
                  dot={{ r: 4, fill: success }}
                  activeDot={{ r: 6 }}
                  name="Hours"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {/* By student */}
      <section className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="surface p-6 lg:col-span-3">
          <div className="uppercase-label mb-1">Per student</div>
          <h2 className="font-serif-display text-2xl mb-6">Total billed by student</h2>
          <div style={{ width: "100%", height: 320 }} data-testid="by-student-bar-chart">
            {byStudent && byStudent.length > 0 && (
              <ResponsiveContainer>
                <BarChart data={byStudent} layout="vertical"
                  margin={{ top: 8, right: 16, left: 30, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                  <XAxis type="number" stroke={axisColor} tick={{ fontSize: 11 }} />
                  <YAxis dataKey="name" type="category" stroke={axisColor}
                    tick={{ fontSize: 11 }} width={100} />
                  <Tooltip
                    content={<TooltipDark formatter={(v) => fmt(v)} />}
                    cursor={{ fill: cursorFill }}
                  />
                  <Bar dataKey="amount" fill={primary} radius={[0, 4, 4, 0]} name="Billed" />
                </BarChart>
              </ResponsiveContainer>
            )}
            {byStudent && byStudent.length === 0 && (
              <div className="h-full flex items-center justify-center text-sm"
                style={{ color: "var(--text-muted)" }}>
                No class data yet.
              </div>
            )}
          </div>
        </div>

        <div className="surface p-6 lg:col-span-2">
          <div className="uppercase-label mb-1">Hours share</div>
          <h2 className="font-serif-display text-2xl mb-6">Time by student</h2>
          <div style={{ width: "100%", height: 320 }} data-testid="hours-pie-chart">
            {byStudent && byStudent.length > 0 && (
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={byStudent}
                    dataKey="hours"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    innerRadius={55}
                    paddingAngle={2}
                    stroke="var(--bg)"
                  >
                    {byStudent.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<TooltipDark formatter={(v) => `${v}h`} />} />
                  <Legend wrapperStyle={{ fontSize: 11, color: axisColor }} />
                </PieChart>
              </ResponsiveContainer>
            )}
            {byStudent && byStudent.length === 0 && (
              <div className="h-full flex items-center justify-center text-sm"
                style={{ color: "var(--text-muted)" }}>
                No class data yet.
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
