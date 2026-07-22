import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatApiErrorDetail, API } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import {
  ArrowLeft, Plus, X, Trash2, MapPin, Download, FileText,
  Navigation, Users, CheckSquare, Square, Link2, Copy, Upload,
} from "lucide-react";
import { toast } from "sonner";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

const TABS = [
  { key: "schedule", label: "Schedule" },
  { key: "expenses", label: "Expenses" },
  { key: "invoices", label: "Invoices" },
  { key: "checkins", label: "Check-ins" },
  { key: "contacts", label: "Contacts" },
  { key: "todos", label: "To-dos" },
];

const CURRENCIES = ["INR", "EUR", "USD", "GBP"];
const CURRENCY_SYMBOLS = { INR: "₹", EUR: "€", USD: "$", GBP: "£" };
const fmtMoney = (n, currency) => `${CURRENCY_SYMBOLS[currency] || currency + " "}${Number(n || 0).toLocaleString("en-IN")}`;

function TabButton({ active, onClick, children, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      className="nav-link"
      style={{
        display: "inline-flex",
        borderBottom: active ? "2px solid var(--primary)" : "2px solid transparent",
        color: active ? "var(--text)" : "var(--text-muted)",
        borderRadius: 0,
      }}
    >
      {children}
    </button>
  );
}

// --------------- Schedule (stops) tab -----------------
function ScheduleTab({ tourId }) {
  const [stops, setStops] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = () => api.get(`/tours/${tourId}/stops`).then((r) => setStops(r.data));
  useEffect(() => { load(); }, [tourId]);

  if (stops === null) return <div className="uppercase-label">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setEditing({})} data-testid="add-stop-btn" className="btn-pill flex items-center gap-2 text-sm">
          <Plus size={14} /> Add stop
        </button>
      </div>
      {stops.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>No stops scheduled yet.</div>
      )}
      <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
        {stops.map((s) => (
          <div key={s.id} className="flex items-center justify-between px-6 py-4 gap-4" style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`stop-row-${s.id}`}>
            <div className="min-w-0">
              <div className="truncate">{s.city}{s.venue ? ` — ${s.venue}` : ""}</div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {fmtDate(s.stop_date)}{s.stop_time ? ` · ${s.stop_time}` : ""}
              </div>
              {s.notes && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{s.notes}</div>}
            </div>
            <button onClick={() => setEditing(s)} data-testid={`edit-stop-${s.id}`} className="btn-ghost text-xs shrink-0">Edit</button>
          </div>
        ))}
      </div>
      {editing && (
        <StopForm tourId={tourId} stop={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

function StopForm({ tourId, stop, onClose, onSaved }) {
  const isNew = !stop.id;
  const [city, setCity] = useState(stop.city || "");
  const [venue, setVenue] = useState(stop.venue || "");
  const [stopDate, setStopDate] = useState(stop.stop_date || "");
  const [stopTime, setStopTime] = useState(stop.stop_time || "");
  const [notes, setNotes] = useState(stop.notes || "");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { city, venue: venue || null, stop_date: stopDate, stop_time: stopTime || null, notes: notes || null };
      if (isNew) await api.post(`/tours/${tourId}/stops`, body);
      else await api.patch(`/tours/${tourId}/stops/${stop.id}`, body);
      toast.success(isNew ? "Stop added" : "Stop updated");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove this stop?")) return;
    setDeleting(true);
    try {
      await api.delete(`/tours/${tourId}/stops/${stop.id}`);
      toast.success("Stop removed");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="stop-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">{isNew ? "Add stop" : "Edit stop"}</h3>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">City</span>
          <input required value={city} onChange={(e) => setCity(e.target.value)} data-testid="stop-city-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Venue (optional)</span>
          <input value={venue} onChange={(e) => setVenue(e.target.value)} data-testid="stop-venue-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Date</span>
            <input required type="date" value={stopDate} onChange={(e) => setStopDate(e.target.value)} data-testid="stop-date-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Time (optional)</span>
            <input type="time" value={stopTime} onChange={(e) => setStopTime(e.target.value)} data-testid="stop-time-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <label className="block mb-6">
          <span className="uppercase-label block mb-1">Notes (optional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="stop-notes-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="flex justify-between gap-3">
          {!isNew ? (
            <button type="button" onClick={remove} disabled={deleting} data-testid="stop-delete-btn"
              className="btn-ghost flex items-center gap-2" style={{ color: "var(--error)" }}>
              <Trash2 size={14} /> Remove
            </button>
          ) : <span />}
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={saving} data-testid="stop-save-btn" className="btn-pill">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

// --------------- Expenses tab -----------------
const EXPENSE_CATEGORIES = ["Flights", "Accommodation", "Local Transport", "Food", "Venue/Equipment", "Other"];

function ExpensesTab({ tourId }) {
  const [expenses, setExpenses] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = () => api.get(`/tours/${tourId}/expenses`).then((r) => setExpenses(r.data));
  useEffect(() => { load(); }, [tourId]);

  if (expenses === null) return <div className="uppercase-label">Loading…</div>;

  // Expenses can span more than one currency on a tour (flights in USD,
  // local transport in GBP, etc.) — a single blended sum would be
  // meaningless, so totals are shown per currency actually used.
  const totalsByCurrency = {};
  expenses.forEach((e) => {
    const c = e.currency || "INR";
    totalsByCurrency[c] = (totalsByCurrency[c] || 0) + Number(e.amount || 0);
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Total:{" "}
          {Object.entries(totalsByCurrency).map(([c, t], i) => (
            <span key={c} style={{ color: "var(--text)" }} className="font-medium">
              {i > 0 && " · "}{fmtMoney(t, c)}
            </span>
          ))}
          {Object.keys(totalsByCurrency).length === 0 && <span style={{ color: "var(--text)" }} className="font-medium">{fmtMoney(0, "INR")}</span>}
        </div>
        <div className="flex gap-2">
          <a href={`${API}/tours/${tourId}/expenses/export.csv`} target="_blank" rel="noreferrer"
            data-testid="export-csv-btn" className="btn-ghost text-xs flex items-center gap-1">
            <Download size={13} /> CSV
          </a>
          <a href={`${API}/tours/${tourId}/expenses/export.pdf`} target="_blank" rel="noreferrer"
            data-testid="export-pdf-btn" className="btn-ghost text-xs flex items-center gap-1">
            <FileText size={13} /> PDF
          </a>
          <button onClick={() => setEditing({})} data-testid="add-expense-btn" className="btn-pill flex items-center gap-2 text-sm">
            <Plus size={14} /> Add expense
          </button>
        </div>
      </div>
      {expenses.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>No expenses logged yet.</div>
      )}
      <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
        {expenses.map((e) => (
          <div key={e.id} className="flex items-center justify-between px-6 py-4 gap-4" style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`expense-row-${e.id}`}>
            <div className="min-w-0">
              <div className="truncate">{e.category}</div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {fmtDate(e.expense_date)}{e.notes ? ` · ${e.notes}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <div className="font-serif-display">{fmtMoney(e.amount, e.currency || "INR")}</div>
              <button onClick={() => setEditing(e)} data-testid={`edit-expense-${e.id}`} className="btn-ghost text-xs">Edit</button>
            </div>
          </div>
        ))}
      </div>
      {editing && (
        <ExpenseForm tourId={tourId} expense={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

function ExpenseForm({ tourId, expense, onClose, onSaved }) {
  const isNew = !expense.id;
  const knownCategory = EXPENSE_CATEGORIES.includes(expense.category);
  const [category, setCategory] = useState(isNew ? "Flights" : (knownCategory ? expense.category : "Other"));
  const [customCategory, setCustomCategory] = useState(!isNew && !knownCategory ? expense.category : "");
  const [amount, setAmount] = useState(expense.amount ?? "");
  const [currency, setCurrency] = useState(expense.currency || "INR");
  const [expenseDate, setExpenseDate] = useState(expense.expense_date || "");
  const [notes, setNotes] = useState(expense.notes || "");
  const [receiptPath, setReceiptPath] = useState(expense.receipt_path || null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const uploadReceipt = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/uploads/photo", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setReceiptPath(data.path);
      toast.success("Receipt uploaded");
    } catch (e2) {
      toast.error("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    const finalCategory = category === "Other" ? (customCategory.trim() || "Other") : category;
    setSaving(true);
    try {
      const body = {
        category: finalCategory,
        amount: Number(amount) || 0,
        currency,
        expense_date: expenseDate,
        notes: notes || null,
        receipt_path: receiptPath || null,
      };
      if (isNew) await api.post(`/tours/${tourId}/expenses`, body);
      else await api.patch(`/tours/${tourId}/expenses/${expense.id}`, body);
      toast.success(isNew ? "Expense added" : "Expense updated");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove this expense?")) return;
    setDeleting(true);
    try {
      await api.delete(`/tours/${tourId}/expenses/${expense.id}`);
      toast.success("Expense removed");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="expense-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">{isNew ? "Add expense" : "Edit expense"}</h3>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)} data-testid="expense-category-select"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2">
            {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c} style={{ color: "#000" }}>{c}</option>)}
          </select>
        </label>
        {category === "Other" && (
          <label className="block mb-3">
            <span className="uppercase-label block mb-1">Specify category</span>
            <input value={customCategory} onChange={(e) => setCustomCategory(e.target.value)} data-testid="expense-custom-category-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        )}
        <div className="grid grid-cols-3 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Amount</span>
            <input required type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)}
              data-testid="expense-amount-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Currency</span>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)} data-testid="expense-currency-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2">
              {CURRENCIES.map((c) => <option key={c} value={c} style={{ color: "#000" }}>{c}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Date</span>
            <input required type="date" value={expenseDate} onChange={(e) => setExpenseDate(e.target.value)}
              data-testid="expense-date-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Notes (optional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="expense-notes-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="mb-6">
          <span className="uppercase-label block mb-1">Receipt (optional)</span>
          {receiptPath && (
            <div className="w-24 h-24 rounded overflow-hidden mb-2" style={{ background: "var(--surface-2)" }}>
              <AuthImage path={receiptPath} className="w-full h-full object-cover" />
            </div>
          )}
          <label className="btn-ghost text-xs inline-flex items-center gap-2 cursor-pointer">
            <Upload size={13} /> {uploading ? "Uploading…" : receiptPath ? "Replace receipt" : "Upload receipt"}
            <input type="file" accept="image/*" className="hidden" onChange={uploadReceipt} data-testid="expense-receipt-input" />
          </label>
        </div>
        <div className="flex justify-between gap-3">
          {!isNew ? (
            <button type="button" onClick={remove} disabled={deleting} data-testid="expense-delete-btn"
              className="btn-ghost flex items-center gap-2" style={{ color: "var(--error)" }}>
              <Trash2 size={14} /> Remove
            </button>
          ) : <span />}
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={saving} data-testid="expense-save-btn" className="btn-pill">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

// --------------- Invoices tab -----------------
function InvoicesTab({ tourId }) {
  const [invoices, setInvoices] = useState(null);
  const [contacts, setContacts] = useState([]);
  const [editing, setEditing] = useState(null);
  const [sending, setSending] = useState(null);

  const load = () => {
    api.get(`/tours/${tourId}/invoices`).then((r) => setInvoices(r.data));
    api.get(`/tours/${tourId}/contacts`).then((r) => setContacts(r.data));
  };
  useEffect(() => { load(); }, [tourId]);

  const togglePaid = async (inv) => {
    try {
      await api.patch(`/tours/${tourId}/invoices/${inv.id}`, { paid: !inv.paid });
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed to update");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this invoice?")) return;
    try {
      await api.delete(`/tours/${tourId}/invoices/${id}`);
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    }
  };

  if (invoices === null) return <div className="uppercase-label">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setEditing({})} data-testid="add-invoice-btn" className="btn-pill flex items-center gap-2 text-sm">
          <Plus size={14} /> New invoice
        </button>
      </div>
      {invoices.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>No invoices yet.</div>
      )}
      <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
        {invoices.map((inv) => (
          <div key={inv.id} className="flex items-center justify-between px-6 py-4 gap-4" style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`invoice-row-${inv.id}`}>
            <div className="min-w-0">
              <div className="truncate">{inv.invoice_number} · {inv.recipient_name}</div>
              <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                {fmtDate(inv.invoice_date)} · {inv.description}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <div className="font-serif-display" style={{ color: inv.paid ? "var(--success)" : "var(--error)" }}>
                {fmtMoney(inv.amount, inv.currency)}
              </div>
              <button
                onClick={() => togglePaid(inv)}
                data-testid={`invoice-paid-toggle-${inv.id}`}
                className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full"
                style={{
                  color: inv.paid ? "var(--success)" : "var(--error)",
                  border: `1px solid ${inv.paid ? "var(--success)" : "var(--error)"}`,
                }}
              >
                {inv.paid ? "Paid" : "Unpaid"}
              </button>
              <button onClick={() => setSending(inv)} data-testid={`invoice-send-${inv.id}`} className="btn-ghost text-xs">Send</button>
              <button onClick={() => setEditing(inv)} data-testid={`edit-invoice-${inv.id}`} className="btn-ghost text-xs">Edit</button>
              <button onClick={() => remove(inv.id)} data-testid={`invoice-delete-${inv.id}`} className="p-1" style={{ color: "var(--error)" }}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
      {editing && (
        <InvoiceForm tourId={tourId} invoice={editing} contacts={contacts} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
      {sending && (
        <SendInvoiceModal tourId={tourId} invoice={sending} onClose={() => setSending(null)} onSent={load} />
      )}
    </div>
  );
}

function InvoiceForm({ tourId, invoice, contacts, onClose, onSaved }) {
  const isNew = !invoice.id;
  const [contactId, setContactId] = useState(invoice.contact_id || "");
  const [recipientName, setRecipientName] = useState(invoice.recipient_name || "");
  const [recipientEmail, setRecipientEmail] = useState(invoice.recipient_email || "");
  const [description, setDescription] = useState(invoice.description || "");
  const [invoiceDate, setInvoiceDate] = useState(invoice.invoice_date || new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState(invoice.amount ?? "");
  const [currency, setCurrency] = useState(invoice.currency || "INR");
  const [saving, setSaving] = useState(false);

  const pickContact = (id) => {
    setContactId(id);
    const c = contacts.find((x) => x.id === id);
    if (c) {
      setRecipientName(c.name);
      setRecipientEmail(c.email || "");
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        contact_id: contactId || null,
        recipient_name: recipientName,
        recipient_email: recipientEmail || null,
        description,
        invoice_date: invoiceDate,
        amount: Number(amount) || 0,
        currency,
      };
      if (isNew) await api.post(`/tours/${tourId}/invoices`, body);
      else await api.patch(`/tours/${tourId}/invoices/${invoice.id}`, body);
      toast.success(isNew ? "Invoice created" : "Invoice updated");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="invoice-form" className="surface w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">{isNew ? "New invoice" : "Edit invoice"}</h3>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>

        {contacts.length > 0 && (
          <label className="block mb-3">
            <span className="uppercase-label block mb-1">Fill from contact (optional)</span>
            <select value={contactId} onChange={(e) => pickContact(e.target.value)} data-testid="invoice-contact-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2">
              <option value="" style={{ color: "#000" }}>— Select a contact —</option>
              {contacts.map((c) => <option key={c.id} value={c.id} style={{ color: "#000" }}>{c.name}</option>)}
            </select>
          </label>
        )}

        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Recipient name</span>
          <input required value={recipientName} onChange={(e) => setRecipientName(e.target.value)} data-testid="invoice-name-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Recipient email</span>
          <input type="email" value={recipientEmail} onChange={(e) => setRecipientEmail(e.target.value)} data-testid="invoice-email-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Description</span>
          <textarea required rows={2} value={description} onChange={(e) => setDescription(e.target.value)} data-testid="invoice-description-input"
            placeholder="e.g. Performance at Theatre X, Paris"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="grid grid-cols-3 gap-3 mb-6">
          <label className="block">
            <span className="uppercase-label block mb-1">Amount</span>
            <input required type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)}
              data-testid="invoice-amount-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Currency</span>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)} data-testid="invoice-currency-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2">
              {CURRENCIES.map((c) => <option key={c} value={c} style={{ color: "#000" }}>{c}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Date</span>
            <input required type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)}
              data-testid="invoice-date-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
          <button type="submit" disabled={saving} data-testid="invoice-save-btn" className="btn-pill">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}

function SendInvoiceModal({ tourId, invoice, onClose, onSent }) {
  const [emailChecked, setEmailChecked] = useState(!!invoice.recipient_email);
  const [whatsappChecked, setWhatsappChecked] = useState(true);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  const send = async () => {
    const channels = [];
    if (emailChecked) channels.push("email");
    if (whatsappChecked) channels.push("whatsapp");
    if (channels.length === 0) {
      toast.error("Pick at least one channel");
      return;
    }
    setSending(true);
    try {
      const { data } = await api.post(`/tours/${tourId}/invoices/${invoice.id}/send`, { channels });
      setResult(data);
      if (data.email === "sent") toast.success("Emailed");
      onSent();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div data-testid="send-invoice-modal" className="surface w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">Send invoice</h3>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
          To <span style={{ color: "var(--text)" }}>{invoice.recipient_name}</span> — {fmtMoney(invoice.amount, invoice.currency)}
        </div>
        <label className="flex items-center gap-2 mb-3">
          <input type="checkbox" checked={emailChecked} onChange={(e) => setEmailChecked(e.target.checked)}
            disabled={!invoice.recipient_email} data-testid="send-email-checkbox" />
          Email {!invoice.recipient_email && <span style={{ color: "var(--text-muted)" }}>(no address on file)</span>}
        </label>
        <label className="flex items-center gap-2 mb-6">
          <input type="checkbox" checked={whatsappChecked} onChange={(e) => setWhatsappChecked(e.target.checked)}
            data-testid="send-whatsapp-checkbox" />
          WhatsApp
        </label>

        {result?.whatsapp && (
          <a href={result.whatsapp} target="_blank" rel="noreferrer" data-testid="whatsapp-link"
            className="btn-pill w-full flex items-center justify-center mb-3">
            Open WhatsApp message
          </a>
        )}
        {result && !result.whatsapp && whatsappChecked && (
          <div className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
            No phone number on file for this contact — WhatsApp link unavailable.
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-ghost">Close</button>
          <button type="button" onClick={send} disabled={sending} data-testid="send-invoice-btn" className="btn-pill">
            {sending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

// --------------- Check-ins tab -----------------
function CheckinsTab({ tourId }) {
  const [checkins, setCheckins] = useState(null);
  const [note, setNote] = useState("");
  const [capturing, setCapturing] = useState(false);

  const load = () => api.get(`/tours/${tourId}/checkins`).then((r) => setCheckins(r.data));
  useEffect(() => { load(); }, [tourId]);

  const checkIn = () => {
    if (!navigator.geolocation) {
      toast.error("Location isn't available in this browser");
      return;
    }
    setCapturing(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await api.post(`/tours/${tourId}/checkins`, {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            note: note || null,
          });
          toast.success("Checked in");
          setNote("");
          load();
        } catch (e2) {
          toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Check-in failed");
        } finally {
          setCapturing(false);
        }
      },
      (err) => {
        toast.error(err.message || "Couldn't get your location");
        setCapturing(false);
      },
      { enableHighAccuracy: true, timeout: 15000 }
    );
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this check-in?")) return;
    try {
      await api.delete(`/tours/${tourId}/checkins/${id}`);
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    }
  };

  if (checkins === null) return <div className="uppercase-label">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="surface p-5">
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Note (optional)</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} data-testid="checkin-note-input"
            placeholder="e.g. Arrived at venue"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <button onClick={checkIn} disabled={capturing} data-testid="checkin-btn" className="btn-pill flex items-center gap-2 text-sm">
          <Navigation size={14} /> {capturing ? "Getting location…" : "Check in here"}
        </button>
      </div>
      {checkins.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>No check-ins logged yet.</div>
      )}
      <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
        {checkins.map((c) => (
          <div key={c.id} className="flex items-center justify-between px-6 py-4 gap-4" style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`checkin-row-${c.id}`}>
            <div className="min-w-0">
              <div className="truncate">{c.note || "Check-in"}</div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {new Date(c.created_at).toLocaleString("en-IN")} · {c.latitude.toFixed(5)}, {c.longitude.toFixed(5)}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <a
                href={`https://www.google.com/maps?q=${c.latitude},${c.longitude}`}
                target="_blank" rel="noreferrer"
                className="btn-ghost text-xs flex items-center gap-1"
                data-testid={`checkin-map-${c.id}`}
              >
                <MapPin size={12} /> Map
              </a>
              <button onClick={() => remove(c.id)} data-testid={`checkin-delete-${c.id}`} className="p-1" style={{ color: "var(--error)" }}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------- Contacts tab -----------------
function ContactsTab({ tourId }) {
  const [contacts, setContacts] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = () => api.get(`/tours/${tourId}/contacts`).then((r) => setContacts(r.data));
  useEffect(() => { load(); }, [tourId]);

  if (contacts === null) return <div className="uppercase-label">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setEditing({})} data-testid="add-contact-btn" className="btn-pill flex items-center gap-2 text-sm">
          <Plus size={14} /> Add contact
        </button>
      </div>
      {contacts.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>No contacts saved yet.</div>
      )}
      <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
        {contacts.map((c) => (
          <div key={c.id} className="flex items-center justify-between px-6 py-4 gap-4" style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`contact-row-${c.id}`}>
            <div className="min-w-0">
              <div className="truncate">{c.name}{c.role ? ` — ${c.role}` : ""}</div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {[c.phone, c.email].filter(Boolean).join(" · ")}
              </div>
              {c.notes && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{c.notes}</div>}
            </div>
            <button onClick={() => setEditing(c)} data-testid={`edit-contact-${c.id}`} className="btn-ghost text-xs shrink-0">Edit</button>
          </div>
        ))}
      </div>
      {editing && (
        <ContactForm tourId={tourId} contact={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

function ContactForm({ tourId, contact, onClose, onSaved }) {
  const isNew = !contact.id;
  const [name, setName] = useState(contact.name || "");
  const [role, setRole] = useState(contact.role || "");
  const [phone, setPhone] = useState(contact.phone || "");
  const [email, setEmail] = useState(contact.email || "");
  const [notes, setNotes] = useState(contact.notes || "");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { name, role: role || null, phone: phone || null, email: email || null, notes: notes || null };
      if (isNew) await api.post(`/tours/${tourId}/contacts`, body);
      else await api.patch(`/tours/${tourId}/contacts/${contact.id}`, body);
      toast.success(isNew ? "Contact added" : "Contact updated");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove this contact?")) return;
    setDeleting(true);
    try {
      await api.delete(`/tours/${tourId}/contacts/${contact.id}`);
      toast.success("Contact removed");
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="contact-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">{isNew ? "Add contact" : "Edit contact"}</h3>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Name</span>
          <input required value={name} onChange={(e) => setName(e.target.value)} data-testid="contact-name-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Role (optional)</span>
          <input value={role} onChange={(e) => setRole(e.target.value)} data-testid="contact-role-input"
            placeholder="e.g. Venue manager"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Phone</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="contact-phone-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="contact-email-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <label className="block mb-6">
          <span className="uppercase-label block mb-1">Notes (optional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="contact-notes-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="flex justify-between gap-3">
          {!isNew ? (
            <button type="button" onClick={remove} disabled={deleting} data-testid="contact-delete-btn"
              className="btn-ghost flex items-center gap-2" style={{ color: "var(--error)" }}>
              <Trash2 size={14} /> Remove
            </button>
          ) : <span />}
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={saving} data-testid="contact-save-btn" className="btn-pill">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

// --------------- To-dos tab -----------------
function TodosTab({ tourId }) {
  const [todos, setTodos] = useState(null);
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () => api.get(`/tours/${tourId}/todos`).then((r) => setTodos(r.data));
  useEffect(() => { load(); }, [tourId]);

  const add = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setAdding(true);
    try {
      await api.post(`/tours/${tourId}/todos`, { text: text.trim() });
      setText("");
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed to add");
    } finally {
      setAdding(false);
    }
  };

  const toggle = async (todo) => {
    try {
      await api.patch(`/tours/${tourId}/todos/${todo.id}`, { done: !todo.done });
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed to update");
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/tours/${tourId}/todos/${id}`);
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    }
  };

  if (todos === null) return <div className="uppercase-label">Loading…</div>;

  return (
    <div className="space-y-4">
      <form onSubmit={add} className="surface p-4 flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} data-testid="todo-input"
          placeholder="Add a planning task…"
          className="flex-1 bg-transparent border border-white/10 rounded px-3 py-2" />
        <button type="submit" disabled={adding} data-testid="todo-add-btn" className="btn-pill flex items-center gap-2 text-sm shrink-0">
          <Plus size={14} /> Add
        </button>
      </form>
      {todos.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>Nothing on the list yet.</div>
      )}
      <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
        {todos.map((t) => (
          <div key={t.id} className="flex items-center justify-between px-6 py-3 gap-4" style={{ borderTop: "1px solid var(--border)" }}
            data-testid={`todo-row-${t.id}`}>
            <button onClick={() => toggle(t)} data-testid={`todo-toggle-${t.id}`} className="flex items-center gap-3 flex-1 min-w-0 text-left">
              {t.done ? <CheckSquare size={16} style={{ color: "var(--success)" }} /> : <Square size={16} style={{ color: "var(--text-muted)" }} />}
              <span className="truncate" style={{ textDecoration: t.done ? "line-through" : "none", color: t.done ? "var(--text-muted)" : "var(--text)" }}>
                {t.text}
              </span>
            </button>
            <button onClick={() => remove(t.id)} data-testid={`todo-delete-${t.id}`} className="p-1 shrink-0" style={{ color: "var(--error)" }}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------- Page -----------------
export default function TourDetailPage() {
  const { id } = useParams();
  const [tour, setTour] = useState(null);
  const [tab, setTab] = useState("schedule");

  useEffect(() => {
    api.get(`/tours/${id}`).then((r) => setTour(r.data)).catch(() => setTour(false));
  }, [id]);

  const copyShareLink = () => {
    const link = `${window.location.origin}/tour/${tour.share_token}`;
    navigator.clipboard.writeText(link);
    toast.success("Share link copied");
  };

  if (tour === null) return <div className="uppercase-label">Loading…</div>;
  if (tour === false) return <div className="uppercase-label">Tour not found.</div>;

  return (
    <div data-testid="tour-detail-page" className="space-y-6">
      <Link to="/tours" className="btn-ghost text-xs inline-flex items-center gap-1">
        <ArrowLeft size={13} /> All tours
      </Link>

      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">
            {fmtDate(tour.start_date)} – {fmtDate(tour.end_date)}{tour.location ? ` · ${tour.location}` : ""}
          </div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">{tour.name}</h1>
        </div>
        <button onClick={copyShareLink} data-testid="copy-share-link-btn" className="btn-ghost text-xs flex items-center gap-2">
          <Link2 size={13} /> Copy public schedule link
        </button>
      </header>

      <div className="flex gap-1 overflow-x-auto" style={{ borderBottom: "1px solid var(--border)" }}>
        {TABS.map((t) => (
          <TabButton key={t.key} active={tab === t.key} onClick={() => setTab(t.key)} testid={`tab-${t.key}`}>
            {t.label}
          </TabButton>
        ))}
      </div>

      {tab === "schedule" && <ScheduleTab tourId={id} />}
      {tab === "expenses" && <ExpensesTab tourId={id} />}
      {tab === "invoices" && <InvoicesTab tourId={id} />}
      {tab === "checkins" && <CheckinsTab tourId={id} />}
      {tab === "contacts" && <ContactsTab tourId={id} />}
      {tab === "todos" && <TodosTab tourId={id} />}
    </div>
  );
}
