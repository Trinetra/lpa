import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const today = () => new Date().toISOString().slice(0, 10);

export default function PaymentsPage() {
  const [students, setStudents] = useState([]);
  const [payments, setPayments] = useState([]);
  const [dueMap, setDueMap] = useState({});
  const [filterId, setFilterId] = useState("");
  const [form, setForm] = useState({
    student_id: "",
    amount: "",
    paid_on: today(),
    method: "Cash",
    notes: "",
  });
  const [saving, setSaving] = useState(false);

  const load = () => {
    const params = filterId ? { params: { student_id: filterId } } : {};
    Promise.all([
      api.get("/students"),
      api.get("/payments", params),
      api.get("/dashboard"),
    ]).then(([sRes, pRes, dRes]) => {
      setStudents(sRes.data);
      setPayments(pRes.data);
      const m = {};
      dRes.data.students.forEach((s) => (m[s.student_id] = s));
      setDueMap(m);
    });
  };

  useEffect(load, [filterId]);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/payments", {
        student_id: form.student_id,
        amount: Number(form.amount),
        paid_on: form.paid_on,
        method: form.method || null,
        notes: form.notes || null,
      });
      toast.success("Payment recorded");
      setForm({ ...form, amount: "", notes: "" });
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this payment?")) return;
    await api.delete(`/payments/${id}`);
    toast.success("Deleted");
    load();
  };

  const nameOf = (id) => students.find((s) => s.id === id)?.name || "—";

  return (
    <div data-testid="payments-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Ledger</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Payments</h1>
      </header>

      {/* Outstanding grid */}
      <section>
        <div className="uppercase-label mb-3">Outstanding balances</div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {Object.values(dueMap).length === 0 && (
            <div className="col-span-full surface p-6" style={{ color: "var(--text-muted)" }}>
              Nothing to show yet.
            </div>
          )}
          {Object.values(dueMap).map((s) => (
            <button
              key={s.student_id}
              onClick={() => setForm({ ...form, student_id: s.student_id, amount: s.balance_due > 0 ? s.balance_due : "" })}
              data-testid={`due-tile-${s.student_id}`}
              className="surface p-4 text-left surface-hover"
              type="button"
            >
              <div className="text-sm truncate">{s.name}</div>
              <div
                className="font-serif-display text-2xl mt-1"
                style={{ color: s.balance_due > 0 ? "var(--error)" : "var(--success)" }}
              >
                {fmt(s.balance_due)}
              </div>
              <div className="uppercase-label mt-1">
                {s.balance_due > 0 ? "Pending" : "Clear"}
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* Record form */}
      <form onSubmit={submit} data-testid="record-payment-form" className="surface p-6">
        <div className="uppercase-label mb-4">Record a payment</div>
        <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
          <label className="md:col-span-2">
            <span className="uppercase-label block mb-1">Student *</span>
            <select
              required
              value={form.student_id}
              onChange={(e) => setForm({ ...form, student_id: e.target.value })}
              data-testid="pay-student-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}
            >
              <option value="" style={{ background: "var(--surface)" }}>Select student…</option>
              {students.map((s) => (
                <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>{s.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="uppercase-label block mb-1">Amount ₹ *</span>
            <input
              required
              type="number"
              min="0"
              step="1"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              data-testid="pay-amount-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Date</span>
            <input
              required
              type="date"
              value={form.paid_on}
              onChange={(e) => setForm({ ...form, paid_on: e.target.value })}
              data-testid="pay-date-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Method</span>
            <select
              value={form.method}
              onChange={(e) => setForm({ ...form, method: e.target.value })}
              data-testid="pay-method-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}
            >
              {["Cash", "UPI", "Bank transfer", "Card", "Other"].map((m) => (
                <option key={m} value={m} style={{ background: "var(--surface)" }}>{m}</option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={saving}
              data-testid="pay-submit-btn"
              className="btn-pill w-full flex items-center justify-center gap-2"
            >
              <Plus size={14} /> {saving ? "Saving…" : "Record"}
            </button>
          </div>
          <label className="md:col-span-6">
            <span className="uppercase-label block mb-1">Notes</span>
            <input
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              data-testid="pay-notes-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
        </div>
      </form>

      {/* Filter */}
      <div className="flex items-center gap-3">
        <span className="uppercase-label">Filter</span>
        <select
          value={filterId}
          onChange={(e) => setFilterId(e.target.value)}
          data-testid="payments-filter-select"
          className="bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
          style={{ background: "var(--surface)" }}
        >
          <option value="" style={{ background: "var(--surface)" }}>All students</option>
          {students.map((s) => (
            <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>{s.name}</option>
          ))}
        </select>
      </div>

      {/* History */}
      <div className="surface overflow-hidden">
        <div className="grid grid-cols-12 px-6 py-3 uppercase-label" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="col-span-3">Date</div>
          <div className="col-span-3">Student</div>
          <div className="col-span-2">Method</div>
          <div className="col-span-3 text-right">Amount</div>
          <div className="col-span-1 text-right">•</div>
        </div>
        {payments.length === 0 && (
          <div className="p-8 text-center" style={{ color: "var(--text-muted)" }}>
            No payments recorded yet.
          </div>
        )}
        {payments.map((p) => (
          <div
            key={p.id}
            data-testid={`payment-row-${p.id}`}
            className="grid grid-cols-12 items-center px-6 py-3 text-sm"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <div className="col-span-3">
              {p.paid_on}
              {p.notes && (
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>{p.notes}</div>
              )}
            </div>
            <div className="col-span-3 truncate">{nameOf(p.student_id)}</div>
            <div className="col-span-2">{p.method || "-"}</div>
            <div className="col-span-3 text-right font-serif-display" style={{ color: "var(--success)" }}>
              {fmt(p.amount)}
            </div>
            <div className="col-span-1 text-right">
              <button
                onClick={() => remove(p.id)}
                data-testid={`delete-payment-${p.id}`}
                className="p-1 rounded hover:bg-white/5"
                style={{ color: "var(--error)" }}
                type="button"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
