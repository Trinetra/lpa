import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail, API } from "@/lib/api";
import { FileText, Download, Link as LinkIcon, Copy } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

export default function InvoicesPage() {
  const [students, setStudents] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [form, setForm] = useState({
    student_id: "",
    start_date: "",
    end_date: "",
  });
  const [saving, setSaving] = useState(false);

  const load = () => {
    Promise.all([api.get("/students"), api.get("/invoices")]).then(([sRes, iRes]) => {
      setStudents(sRes.data);
      setInvoices(iRes.data);
    });
  };
  useEffect(load, []);

  const nameOf = (id) => students.find((s) => s.id === id)?.name || "—";

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

  const shareLink = (inv) =>
    `${window.location.origin}/invoice/${inv.share_token}`;

  const pdfLink = (inv) =>
    `${API}/invoices/${inv.invoice_id}/pdf?token=${inv.share_token}`;

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Link copied");
  };

  return (
    <div data-testid="invoices-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Billing</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Invoices</h1>
        <p className="mt-3 text-sm max-w-xl" style={{ color: "var(--text-muted)" }}>
          Generate a shareable invoice for any student and date range. Send the link
          or the PDF directly to your student.
        </p>
      </header>

      <form onSubmit={generate} data-testid="invoice-form" className="surface p-6">
        <div className="uppercase-label mb-4">Generate invoice</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="md:col-span-2">
            <span className="uppercase-label block mb-1">Student *</span>
            <select
              required
              value={form.student_id}
              onChange={(e) => setForm({ ...form, student_id: e.target.value })}
              data-testid="invoice-student-select"
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
            <span className="uppercase-label block mb-1">From</span>
            <input
              type="date"
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              data-testid="invoice-start-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
          <label>
            <span className="uppercase-label block mb-1">To</span>
            <input
              type="date"
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              data-testid="invoice-end-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
        </div>
        <div className="flex justify-end mt-4">
          <button
            type="submit"
            disabled={saving}
            data-testid="invoice-generate-btn"
            className="btn-pill flex items-center gap-2"
          >
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
            <div
              key={inv.invoice_id}
              data-testid={`invoice-row-${inv.invoice_id}`}
              className="flex flex-wrap items-center justify-between px-6 py-4 gap-4"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <div className="min-w-0">
                <div className="font-serif-display text-lg truncate">
                  {inv.student_name}
                </div>
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
                <div className="flex gap-2">
                  <a
                    href={pdfLink(inv)}
                    target="_blank"
                    rel="noreferrer"
                    data-testid={`invoice-pdf-${inv.invoice_id}`}
                    className="btn-ghost flex items-center gap-1 text-xs"
                  >
                    <Download size={13} /> PDF
                  </a>
                  <button
                    type="button"
                    onClick={() => copy(shareLink(inv))}
                    data-testid={`invoice-copy-${inv.invoice_id}`}
                    className="btn-ghost flex items-center gap-1 text-xs"
                  >
                    <LinkIcon size={13} /> Share link <Copy size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
