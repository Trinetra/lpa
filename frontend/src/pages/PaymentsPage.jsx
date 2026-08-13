import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, Trash2, X, ArrowRight, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import ShowInactiveToggle, { filterActive, inactiveCountOf } from "@/components/ShowInactiveToggle";

const CURRENCY_SYMBOLS = { INR: "₹", EUR: "€", USD: "$", GBP: "£" };
const fmtCur = (n, currency) => `${CURRENCY_SYMBOLS[currency] || (currency ? currency + " " : "₹")}${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const today = () => new Date().toISOString().slice(0, 10);
const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

// For a foreign-currency student: she enters what actually landed in the
// bank (usually INR), we fetch a live reference rate and suggest an
// oldest-first allocation across her outstanding classes — adjustable
// before saving, since the bank's real conversion rate/fees will differ
// slightly from the market rate this uses.
function ReconcilePaymentModal({ student, onClose, onSaved }) {
  const [receivedAmount, setReceivedAmount] = useState("");
  const [receivedCurrency, setReceivedCurrency] = useState("INR");
  const [paidOn, setPaidOn] = useState(today());
  const [method, setMethod] = useState("Bank transfer");
  const [notes, setNotes] = useState("");
  const [preview, setPreview] = useState(null);
  const [editedAllocations, setEditedAllocations] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchPreview = async () => {
    if (!receivedAmount || Number(receivedAmount) <= 0) return;
    setLoadingPreview(true);
    try {
      const { data } = await api.get(`/students/${student.id}/reconcile-preview`, {
        params: { received_amount: Number(receivedAmount), received_currency: receivedCurrency },
      });
      setPreview(data);
      setEditedAllocations(data.allocations.map((a) => ({ ...a })));
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't fetch conversion");
      setPreview(null);
      setEditedAllocations(null);
    } finally {
      setLoadingPreview(false);
    }
  };

  const updateAllocation = (classId, value) => {
    setEditedAllocations((prev) => prev.map((a) => (a.class_id === classId ? { ...a, amount: value } : a)));
  };

  const totalAllocated = (editedAllocations || []).reduce((sum, a) => sum + (Number(a.amount) || 0), 0);

  const save = async () => {
    if (!preview) return;
    setSaving(true);
    try {
      await api.post("/payments", {
        student_id: student.id,
        amount: round2(totalAllocated),
        paid_on: paidOn,
        method: method || null,
        notes: notes || null,
        received_amount: preview.received_amount,
        received_currency: preview.received_currency,
        fx_rate: preview.fx_rate,
        allocations: (editedAllocations || [])
          .filter((a) => Number(a.amount) > 0)
          .map((a) => ({ class_id: a.class_id, amount: Number(a.amount) })),
      });
      toast.success("Payment recorded and allocated");
      onSaved();
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const round2 = (n) => Math.round(n * 100) / 100;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div data-testid="reconcile-payment-modal" className="surface w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="uppercase-label mb-1">Reconcile payment</div>
            <h3 className="font-serif-display text-2xl">{student.name} <span className="text-sm" style={{ color: "var(--text-muted)" }}>({student.currency})</span></h3>
          </div>
          <button type="button" onClick={onClose} data-testid="reconcile-close" className="p-1"><X size={18} /></button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-4">
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Amount received</span>
            <input type="number" min="0" step="0.01" value={receivedAmount}
              onChange={(e) => { setReceivedAmount(e.target.value); setPreview(null); }}
              data-testid="reconcile-received-input"
              placeholder="e.g. 4120"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">In</span>
            <select value={receivedCurrency} onChange={(e) => { setReceivedCurrency(e.target.value); setPreview(null); }}
              data-testid="reconcile-received-currency"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}>
              {Object.keys(CURRENCY_SYMBOLS).map((c) => (
                <option key={c} value={c} style={{ background: "var(--surface)" }}>{c}</option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <button type="button" onClick={fetchPreview} disabled={loadingPreview || !receivedAmount}
              data-testid="reconcile-fetch-btn"
              className="btn-pill w-full flex items-center justify-center gap-2 text-sm">
              <RefreshCw size={14} className={loadingPreview ? "animate-spin" : ""} /> Convert
            </button>
          </div>
        </div>

        {preview && (
          <>
            <div className="surface p-4 mb-4 flex items-center justify-between flex-wrap gap-2" style={{ background: "var(--surface-2)" }}>
              <div className="text-sm">
                {fmtCur(preview.received_amount, preview.received_currency)}
                <ArrowRight size={12} className="inline mx-2" style={{ color: "var(--text-muted)" }} />
                <span className="font-serif-display" style={{ color: "var(--primary)" }}>{fmtCur(preview.converted_amount, student.currency)}</span>
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                Rate: 1 {preview.received_currency} = {preview.fx_rate?.toFixed(4)} {student.currency}
              </div>
            </div>

            <div className="uppercase-label mb-2">Suggested allocation (oldest first)</div>
            <div className="surface divide-y mb-4" style={{ borderColor: "var(--border)" }}>
              {editedAllocations.length === 0 && (
                <div className="p-4 text-sm text-center" style={{ color: "var(--text-muted)" }}>Nothing outstanding to allocate against.</div>
              )}
              {editedAllocations.map((a) => (
                <div key={a.class_id} className="flex items-center justify-between px-4 py-2.5 gap-3" style={{ borderTop: "1px solid var(--border)" }}
                  data-testid={`reconcile-allocation-${a.class_id}`}>
                  <div className="text-sm">
                    <div>{fmtDate(a.class_date)}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {fmtCur(a.outstanding_before, student.currency)} outstanding of {fmtCur(a.class_amount, student.currency)}
                    </div>
                  </div>
                  <input type="number" min="0" step="0.01" value={a.amount}
                    onChange={(e) => updateAllocation(a.class_id, e.target.value)}
                    data-testid={`reconcile-allocation-input-${a.class_id}`}
                    className="w-28 bg-transparent border border-white/10 rounded px-2 py-1 text-right text-sm" />
                </div>
              ))}
            </div>

            <div className="flex justify-between text-sm mb-4 px-1">
              <span style={{ color: "var(--text-muted)" }}>Allocated</span>
              <span className="font-serif-display">{fmtCur(totalAllocated, student.currency)}</span>
            </div>
            {preview.unallocated > 0 && (
              <div className="text-xs mb-4 px-1" style={{ color: "var(--text-muted)" }}>
                {fmtCur(preview.unallocated, student.currency)} left over (nothing outstanding to apply it to) — she may have overpaid or paid in advance.
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
              <label>
                <span className="uppercase-label block mb-1">Date</span>
                <input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)}
                  data-testid="reconcile-date-input"
                  className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
              </label>
              <label>
                <span className="uppercase-label block mb-1">Method</span>
                <select value={method} onChange={(e) => setMethod(e.target.value)}
                  data-testid="reconcile-method-select"
                  className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
                  style={{ background: "var(--surface)" }}>
                  {["Bank transfer", "Cash", "UPI", "Card", "Other"].map((m) => (
                    <option key={m} value={m} style={{ background: "var(--surface)" }}>{m}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="uppercase-label block mb-1">Notes</span>
                <input value={notes} onChange={(e) => setNotes(e.target.value)}
                  data-testid="reconcile-notes-input"
                  className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
              </label>
            </div>
          </>
        )}

        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-ghost" data-testid="reconcile-cancel-btn">Cancel</button>
          <button type="button" onClick={save} disabled={saving || !preview || totalAllocated <= 0}
            data-testid="reconcile-save-btn" className="btn-pill">
            {saving ? "Saving…" : "Confirm & save payment"}
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const [reconciling, setReconciling] = useState(null); // student object, or null
  const [showInactive, setShowInactive] = useState(false);

  const studentMap = students.reduce((m, s) => ({ ...m, [s.id]: s }), {});
  const selectedStudent = studentMap[form.student_id];
  const isForeignCurrency = selectedStudent && selectedStudent.currency && selectedStudent.currency !== "INR";
  const visibleStudents = filterActive(students, showInactive);
  const inactiveCount = inactiveCountOf(students);
  const visibleDueEntries = filterActive(Object.values(dueMap), showInactive);

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
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Ledger</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Payments</h1>
        </div>
        <ShowInactiveToggle count={inactiveCount} checked={showInactive} onChange={setShowInactive} />
      </header>

      {/* Outstanding grid */}
      <section>
        <div className="uppercase-label mb-3">Outstanding balances</div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {visibleDueEntries.length === 0 && (
            <div className="col-span-full surface p-6" style={{ color: "var(--text-muted)" }}>
              Nothing to show yet.
            </div>
          )}
          {visibleDueEntries.map((s) => (
            <button
              key={s.student_id}
              onClick={() => {
                const student = studentMap[s.student_id];
                if (student && student.currency && student.currency !== "INR") {
                  setReconciling(student);
                } else {
                  setForm({ ...form, student_id: s.student_id, amount: s.balance_due > 0 ? s.balance_due : "" });
                }
              }}
              data-testid={`due-tile-${s.student_id}`}
              className="surface p-4 text-left surface-hover"
              type="button"
            >
              <div className="text-sm truncate">{s.name}</div>
              <div
                className="font-serif-display text-2xl mt-1"
                style={{ color: s.balance_due > 0 ? "var(--error)" : "var(--success)" }}
              >
                {fmtCur(s.balance_due, s.currency)}
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
              {visibleStudents.map((s) => (
                <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>
                  {s.name}{s.currency && s.currency !== "INR" ? ` (${s.currency})` : ""}
                </option>
              ))}
            </select>
          </label>
          {isForeignCurrency ? (
            <div className="md:col-span-4 flex items-end">
              <div className="surface p-3 w-full flex items-center justify-between gap-3" style={{ background: "var(--surface-2)" }}>
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                  {selectedStudent.name} pays in {selectedStudent.currency} — use the reconciliation flow to convert and allocate a payment.
                </span>
                <button type="button" onClick={() => setReconciling(selectedStudent)} data-testid="open-reconcile-btn"
                  className="btn-pill text-sm shrink-0">Reconcile payment</button>
              </div>
            </div>
          ) : (
          <>
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
          </>
          )}
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
        <div className="hidden sm:grid sm:grid-cols-12 px-6 py-3 uppercase-label" style={{ borderBottom: "1px solid var(--border)" }}>
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
        {payments.map((p) => {
          const pStudent = studentMap[p.student_id];
          const currency = pStudent?.currency || "INR";
          return (
          <div
            key={p.id}
            data-testid={`payment-row-${p.id}`}
            className="px-4 sm:px-6 py-3 text-sm"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <div className="flex flex-col sm:grid sm:grid-cols-12 sm:items-center gap-2 sm:gap-0">
              <div className="sm:col-span-3 flex sm:block justify-between">
                <span>{fmtDate(p.paid_on)}</span>
                <span className="sm:hidden font-serif-display" style={{ color: "var(--success)" }}>{fmtCur(p.amount, currency)}</span>
              </div>
              <div className="sm:col-span-3 truncate" style={{ color: "var(--text-muted)" }}>{nameOf(p.student_id)}</div>
              <div className="sm:col-span-2 flex sm:block items-center justify-between">
                <span className="sm:hidden uppercase-label">Method</span>
                <span>{p.method || "-"}</span>
              </div>
              <div className="hidden sm:block sm:col-span-3 text-right font-serif-display" style={{ color: "var(--success)" }}>
                {fmtCur(p.amount, currency)}
              </div>
              <div className="sm:col-span-1 flex justify-end pt-2 sm:pt-0 mt-1 sm:mt-0" style={{ borderTop: "1px dashed var(--border)" }}>
                <button
                  onClick={() => remove(p.id)}
                  data-testid={`delete-payment-${p.id}`}
                  className="px-3 py-1.5 sm:p-1 rounded hover:bg-white/5 inline-flex items-center gap-1 text-xs"
                  style={{ color: "var(--error)" }}
                  type="button"
                >
                  <Trash2 size={14} /> <span className="sm:hidden">Delete</span>
                </button>
              </div>
            </div>
            {p.received_currency && p.received_currency !== currency && (
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Received {fmtCur(p.received_amount, p.received_currency)} (converted at 1 {p.received_currency} = {p.fx_rate?.toFixed(4)} {currency})
              </div>
            )}
            {p.notes && (
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{p.notes}</div>
            )}
          </div>
          );
        })}
      </div>

      {reconciling && (
        <ReconcilePaymentModal
          student={reconciling}
          onClose={() => setReconciling(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
