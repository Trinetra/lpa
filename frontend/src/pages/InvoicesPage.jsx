import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail, API } from "@/lib/api";
import { FileText, Download, Link as LinkIcon, Copy, Mail, MessageCircle, X, Trash2, Send } from "lucide-react";
import { toast } from "sonner";
import BulkSendModal from "@/components/BulkSendModal";
import { useAuth } from "@/context/AuthContext";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

function EmailInvoiceModal({ invoice, studentMap, onClose }) {
  const { user } = useAuth();
  const student = studentMap[invoice.student_id] || {};
  const shareLink = `${window.location.origin}/invoice/${invoice.share_token}`;
  const [to, setTo] = useState(student.email || "");
  const [replyTo, setReplyTo] = useState(user?.email || "");
  const [msg, setMsg] = useState(
    `Hi ${student.name || "there"}, please find your invoice attached (₹${invoice.summary?.balance_due} due).`
  );
  const [sending, setSending] = useState(false);

  const send = async (e) => {
    e.preventDefault();
    setSending(true);
    try {
      await api.post(`/invoices/${invoice.invoice_id}/send`, {
        to_email: to,
        reply_to: replyTo || null,
        message: msg || null,
        public_link: shareLink,
      });
      toast.success(`Invoice emailed to ${to}`);
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={send} data-testid="email-invoice-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">Email invoice</h3>
          <button type="button" onClick={onClose} data-testid="email-modal-close" className="p-1"><X size={18} /></button>
        </div>
        <div className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
          Sending invoice for <span style={{ color: "var(--text)" }}>{student.name}</span>
        </div>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">To (student email)</span>
          <input required type="email" value={to} onChange={(e) => setTo(e.target.value)}
            data-testid="email-to-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Reply-to (your email, optional)</span>
          <input type="email" value={replyTo} onChange={(e) => setReplyTo(e.target.value)}
            data-testid="email-replyto-input"
            placeholder="teacher@example.com"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="block mb-6">
          <span className="uppercase-label block mb-1">Personal note (optional)</span>
          <textarea rows={3} value={msg} onChange={(e) => setMsg(e.target.value)}
            data-testid="email-message-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-ghost" data-testid="email-cancel-btn">Cancel</button>
          <button type="submit" disabled={sending} className="btn-pill flex items-center gap-2"
            data-testid="email-send-btn">
            <Mail size={14} /> {sending ? "Sending…" : "Send email"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function InvoicesPage() {
  const [students, setStudents] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [form, setForm] = useState({ student_id: "", start_date: "", end_date: "" });
  const [saving, setSaving] = useState(false);
  const [emailing, setEmailing] = useState(null);
  const [bulkOpen, setBulkOpen] = useState(false);

  const load = () => {
    Promise.all([api.get("/students"), api.get("/invoices")]).then(([sRes, iRes]) => {
      setStudents(sRes.data);
      setInvoices(iRes.data);
    });
  };
  useEffect(load, []);

  const studentMap = students.reduce((m, s) => ({ ...m, [s.id]: s }), {});

  const generate = async (e) => {
    e.preventDefault();
    if (!form.student_id) {
      toast.error("Please select a student");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post("/invoices/generate", {
        student_id: form.student_id,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
      });
      toast.success(`Invoice generated (${data.class_count} classes)`);
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Generate failed");
    } finally {
      setSaving(false);
    }
  };

  const shareLink = (inv) => `${window.location.origin}/invoice/${inv.share_token}`;
  const pdfLink = (inv) => `${API}/invoices/${inv.invoice_id}/pdf?token=${inv.share_token}`;
  const copy = (text) => { navigator.clipboard.writeText(text); toast.success("Link copied"); };

  const removeInvoice = async (inv) => {
    if (!window.confirm(`Delete this invoice for ${inv.student_name}? This cannot be undone.`)) return;
    try {
      await api.delete(`/invoices/${inv.invoice_id}`);
      toast.success("Invoice deleted");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Delete failed");
    }
  };

  const openWhatsApp = (inv) => {
    const s = studentMap[inv.student_id] || {};
    const link = shareLink(inv);
    const msg =
      `Hi ${s.name || ""}, here's your dance-class invoice ` +
      `(₹${inv.summary?.balance_due || 0} due):\n${link}`;
    let phone = (s.phone || "").replace(/\D/g, "");
    if (phone.length === 10) phone = `91${phone}`; // wa.me needs a country code
    const url = phone
      ? `https://wa.me/${phone}?text=${encodeURIComponent(msg)}`
      : `https://wa.me/?text=${encodeURIComponent(msg)}`;
    window.open(url, "_blank", "noreferrer");
  };

  return (
    <div data-testid="invoices-page" className="space-y-8">
      <header>
        <div className="flex flex-wrap justify-between items-start gap-4">
          <div>
            <div className="uppercase-label mb-2">Billing</div>
            <h1 className="font-serif-display text-4xl sm:text-5xl">Invoices</h1>
          </div>
          <button type="button" onClick={() => setBulkOpen(true)}
            data-testid="bulk-send-open-btn"
            className="btn-pill flex items-center gap-2">
            <Send size={14} /> Send outstanding
          </button>
        </div>
        <p className="mt-3 text-sm max-w-xl" style={{ color: "var(--text-muted)" }}>
          Generate a shareable invoice for any student and date range. Send the link
          or PDF directly to your student via email or WhatsApp — or dispatch a whole
          month's outstanding reminders in one tap.
        </p>
      </header>

      <form onSubmit={generate} data-testid="invoice-form" className="surface p-6">
        <div className="uppercase-label mb-4">Generate invoice</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="md:col-span-2">
            <span className="uppercase-label block mb-1">Student *</span>
            <select required value={form.student_id}
              onChange={(e) => setForm({ ...form, student_id: e.target.value })}
              data-testid="invoice-student-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}>
              <option value="" style={{ background: "var(--surface)" }}>Select student…</option>
              {students.map((s) => (
                <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>{s.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="uppercase-label block mb-1">From</span>
            <input type="date" value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              data-testid="invoice-start-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">To</span>
            <input type="date" value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              data-testid="invoice-end-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <div className="flex justify-end mt-4">
          <button type="submit" disabled={saving} data-testid="invoice-generate-btn"
            className="btn-pill flex items-center gap-2">
            <FileText size={14} />
            {saving ? "Generating…" : "Generate invoice"}
          </button>
        </div>
      </form>

      <section>
        <div className="uppercase-label mb-3">History</div>
        <div className="surface">
          {invoices.length === 0 && (
            <div className="p-8 text-center" style={{ color: "var(--text-muted)" }}>
              No invoices yet.
            </div>
          )}
          {invoices.map((inv) => (
            <div key={inv.invoice_id} data-testid={`invoice-row-${inv.invoice_id}`}
              className="flex flex-wrap items-center justify-between px-6 py-4 gap-4"
              style={{ borderTop: "1px solid var(--border)" }}>
              <div className="min-w-0">
                <div className="font-serif-display text-lg truncate">{inv.student_name}</div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {inv.start_date || "All time"} → {inv.end_date || "today"} · {new Date(inv.created_at).toLocaleString()}
                </div>
              </div>
              <div className="flex items-center gap-4 flex-wrap">
                <div className="text-right">
                  <div className="uppercase-label">Billed</div>
                  <div className="font-serif-display">{fmt(inv.summary?.total_billed)}</div>
                </div>
                <div className="text-right">
                  <div className="uppercase-label">Due</div>
                  <div className="font-serif-display" style={{ color: inv.summary?.balance_due > 0 ? "var(--error)" : "var(--success)" }}>
                    {fmt(inv.summary?.balance_due)}
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <a href={pdfLink(inv)} target="_blank" rel="noreferrer"
                    data-testid={`invoice-pdf-${inv.invoice_id}`}
                    className="btn-ghost flex items-center gap-1 text-xs">
                    <Download size={13} /> PDF
                  </a>
                  <button type="button" onClick={() => copy(shareLink(inv))}
                    data-testid={`invoice-copy-${inv.invoice_id}`}
                    className="btn-ghost flex items-center gap-1 text-xs">
                    <LinkIcon size={13} /> Link <Copy size={12} />
                  </button>
                  <button type="button" onClick={() => setEmailing(inv)}
                    data-testid={`invoice-email-${inv.invoice_id}`}
                    className="btn-ghost flex items-center gap-1 text-xs">
                    <Mail size={13} /> Email
                  </button>
                  <button type="button" onClick={() => openWhatsApp(inv)}
                    data-testid={`invoice-whatsapp-${inv.invoice_id}`}
                    className="btn-pill flex items-center gap-1 text-xs"
                    style={{ background: "#25D366", color: "#0b1f13" }}>
                    <MessageCircle size={13} /> WhatsApp
                  </button>
                  <button type="button" onClick={() => removeInvoice(inv)}
                    data-testid={`invoice-delete-${inv.invoice_id}`}
                    className="p-2 rounded hover:bg-white/5"
                    style={{ color: "var(--error)" }}
                    title="Delete invoice">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {emailing && (
        <EmailInvoiceModal
          invoice={emailing}
          studentMap={studentMap}
          onClose={() => setEmailing(null)}
        />
      )}
      {bulkOpen && (
        <BulkSendModal onClose={() => setBulkOpen(false)} onDone={load} />
      )}
    </div>
  );
}
