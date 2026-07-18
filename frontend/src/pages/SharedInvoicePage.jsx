import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/lib/api";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

export default function SharedInvoicePage() {
  const { token } = useParams();
  const [inv, setInv] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    axios
      .get(`${API}/invoices/share/${token}`)
      .then((r) => setInv(r.data))
      .catch(() => setErr("Invoice not found."));
  }, [token]);

  if (err)
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="surface p-8 text-center">
          <div className="uppercase-label mb-2">Not found</div>
          <div className="font-serif-display text-2xl">{err}</div>
        </div>
      </div>
    );
  if (!inv) return <div className="min-h-screen flex items-center justify-center uppercase-label">Loading…</div>;

  const pdfUrl = `${API}/invoices/${inv.invoice_id}/pdf?token=${inv.share_token}`;

  return (
    <div className="min-h-screen py-14 px-6" style={{ background: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto">
        <header className="flex items-end justify-between mb-10">
          <div>
            <div className="uppercase-label mb-1">Invoice from</div>
            <div className="font-serif-display text-3xl" style={{ color: "var(--primary)" }}>
              {inv.teacher_name}
            </div>
          </div>
          <a href={pdfUrl} target="_blank" rel="noreferrer" className="btn-pill" data-testid="shared-download-pdf">
            Download PDF
          </a>
        </header>

        <div className="surface p-8 mb-6">
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div>
              <div className="uppercase-label mb-1">Billed to</div>
              <div className="font-serif-display text-xl">{inv.student?.name}</div>
              <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                {inv.student?.email} {inv.student?.phone && ` · ${inv.student.phone}`}
              </div>
            </div>
            <div className="text-right">
              <div className="uppercase-label mb-1">Period</div>
              <div>{inv.start_date || "All time"} — {inv.end_date || "today"}</div>
            </div>
          </div>

          <div className="divider-dashed my-4" />

          <div className="uppercase-label mb-2">Classes</div>
          <table className="w-full text-sm mb-6">
            <thead>
              <tr style={{ color: "var(--text-muted)" }}>
                <th className="text-left py-2">Date</th>
                <th className="text-right">Hrs</th>
                <th className="text-right">Rate</th>
                <th className="text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {inv.classes.map((c) => (
                <tr key={c.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td className="py-2">{c.class_date}</td>
                  <td className="text-right">{c.hours}</td>
                  <td className="text-right">{fmt(c.rate)}</td>
                  <td className="text-right">{fmt(c.amount)}</td>
                </tr>
              ))}
              {inv.classes.length === 0 && (
                <tr><td colSpan="4" className="py-4 text-center" style={{ color: "var(--text-muted)" }}>No classes in this period.</td></tr>
              )}
            </tbody>
          </table>

          {inv.payments.length > 0 && (
            <>
              <div className="uppercase-label mb-2">Payments received</div>
              <table className="w-full text-sm mb-6">
                <thead>
                  <tr style={{ color: "var(--text-muted)" }}>
                    <th className="text-left py-2">Date</th>
                    <th className="text-left">Method</th>
                    <th className="text-right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {inv.payments.map((p) => (
                    <tr key={p.id} style={{ borderTop: "1px solid var(--border)" }}>
                      <td className="py-2">{p.paid_on}</td>
                      <td>{p.method || "-"}</td>
                      <td className="text-right">{fmt(p.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div className="divider-dashed my-4" />

          <div className="flex justify-end">
            <div className="w-full max-w-xs text-sm space-y-1">
              <div className="flex justify-between"><span>Total billed</span><span>{fmt(inv.summary?.total_billed)}</span></div>
              <div className="flex justify-between"><span>Total paid</span><span>{fmt(inv.summary?.total_paid)}</span></div>
              <div className="flex justify-between font-serif-display text-lg pt-2"
                style={{ borderTop: "1px solid var(--border)", color: inv.summary?.balance_due > 0 ? "var(--error)" : "var(--success)" }}>
                <span>Balance due</span><span>{fmt(inv.summary?.balance_due)}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="text-center text-xs" style={{ color: "var(--text-muted)" }}>
          <Link to="/" className="underline">Powered by Kalpana Studio Ledger</Link>
        </div>
      </div>
    </div>
  );
}
