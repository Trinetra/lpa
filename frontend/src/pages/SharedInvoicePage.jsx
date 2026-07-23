import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/lib/api";

const MAROON = "#7A1F2B";
const GOLD = "#C98A3A";
const LABEL = "#8A6D3B";
const RULE = "#E4D9C8";
const CREAM = "#FBF5EC";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "");
const fmtHours = (h) => {
  const n = Number(h);
  const whole = Math.trunc(n);
  const frac = n - whole;
  if (Math.abs(frac - 0.5) < 1e-6) return whole ? <>{whole} <sup>1/2</sup></> : <sup>1/2</sup>;
  return String(n);
};

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
  const studio = inv.studio || {};
  const brandName = studio.studio_name || inv.teacher_name;
  const logoUrl = studio.logo_path ? `${API}/invoices/share/${token}/logo` : null;

  const totalBilled = inv.summary?.total_billed || 0;
  const totalPaid = inv.summary?.total_paid || 0;
  const balanceDue = inv.summary?.balance_due || 0;
  const hasCredit = balanceDue < 0;
  const qrUrl = (studio.contact_upi && balanceDue > 0) ? `${API}/invoices/share/${token}/qr` : null;

  return (
    <div className="min-h-screen py-14 px-6" style={{ background: "#FFFDF9" }}>
      <div className="max-w-2xl mx-auto">
        {/* Letterhead — centered, mirrors the PDF */}
        <header className="text-center mb-8">
          <div className="uppercase-label mb-3" style={{ color: MAROON, letterSpacing: "1px" }}>Invoice</div>
          {logoUrl && (
            <img src={logoUrl} alt="" data-testid="shared-logo"
              className="w-24 h-24 object-contain rounded mx-auto mb-3" />
          )}
          <div className="font-serif-display text-2xl" style={{ color: MAROON }} data-testid="shared-brand">
            {brandName}
          </div>
          <div className="mt-5 mx-auto" style={{ borderBottom: `1px solid ${GOLD}`, maxWidth: "100%" }} />
        </header>

        <div className="flex justify-end mb-4">
          <a href={pdfUrl} target="_blank" rel="noreferrer" className="btn-pill" data-testid="shared-download-pdf">
            Download PDF
          </a>
        </div>

        <div className="surface p-0 mb-6 overflow-hidden">
          {/* Meta info card */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 p-6" style={{ background: CREAM }}>
            <div>
              <div className="uppercase-label" style={{ color: LABEL, fontSize: "0.65rem" }}>Billed to</div>
              <div className="font-medium">{inv.student?.name}</div>
            </div>
            <div className="sm:text-right">
              <div className="uppercase-label" style={{ color: LABEL, fontSize: "0.65rem" }}>Period</div>
              <div className="font-medium">{fmtDate(inv.start_date) || "All time"} – {fmtDate(inv.end_date) || "Today"}</div>
            </div>
            <div className="sm:col-span-2 text-sm" style={{ color: LABEL }}>
              {inv.student?.email} {inv.student?.phone && ` · ${inv.student.phone}`}
            </div>
          </div>

          <div className="p-6">
            <div className="uppercase-label mb-2" style={{ color: "var(--text)" }}>Classes</div>
            <table className="w-full text-sm mb-6">
              <thead>
                <tr style={{ background: MAROON, color: "white" }}>
                  <th className="text-left py-2 px-3">Date</th>
                  <th className="text-left px-3">Hours</th>
                  <th className="text-left px-3">Amount</th>
                  <th className="text-left px-3">Notes</th>
                </tr>
              </thead>
              <tbody>
                {inv.classes.map((c, i) => (
                  <tr key={c.id} style={{ background: i % 2 === 1 ? CREAM : "transparent" }}>
                    <td className="py-2 px-3 text-left">{fmtDate(c.class_date)}</td>
                    <td className="text-left px-3">{fmtHours(c.hours)}</td>
                    <td className="text-left px-3">{fmt(c.amount)}</td>
                    <td className="text-left px-3" style={{ color: LABEL }}>{c.notes || ""}</td>
                  </tr>
                ))}
                {inv.classes.length === 0 && (
                  <tr><td colSpan="4" className="py-4 text-center" style={{ color: LABEL }}>No classes in this period.</td></tr>
                )}
              </tbody>
            </table>

            {inv.payments.length > 0 && (
              <>
                <div className="uppercase-label mb-2" style={{ color: "var(--text)" }}>Payments received</div>
                <table className="w-full text-sm mb-6">
                  <thead>
                    <tr style={{ background: MAROON, color: "white" }}>
                      <th className="text-left py-2 px-3">Date</th>
                      <th className="text-left px-3">Method</th>
                      <th className="text-left px-3">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inv.payments.map((p, i) => (
                      <tr key={p.id} style={{ background: i % 2 === 1 ? CREAM : "transparent" }}>
                        <td className="py-2 px-3 text-left">{fmtDate(p.paid_on)}</td>
                        <td className="text-left px-3">{p.method || "—"}</td>
                        <td className="text-left px-3">{fmt(p.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            <div className="flex justify-between items-end flex-wrap gap-6">
              {qrUrl ? (
                <div className="text-center" data-testid="shared-upi-qr">
                  <img src={qrUrl} alt="Scan to pay via UPI" className="w-28 h-28" />
                  <div className="text-xs mt-1 italic" style={{ color: LABEL }}>Scan to pay via UPI</div>
                </div>
              ) : <div />}
              <div className="w-full sm:w-auto sm:min-w-[280px] text-sm">
                <div className="flex justify-between gap-6 py-1"><span style={{ color: LABEL }}>Total billed</span><span>{fmt(totalBilled)}</span></div>
                <div className="flex justify-between gap-6 py-1"><span style={{ color: LABEL }}>Total paid</span><span>{fmt(totalPaid)}</span></div>
                {hasCredit && (
                  <div className="flex justify-between gap-6 py-1"><span style={{ color: LABEL }}>Credit balance</span><span>{fmt(Math.abs(balanceDue))}</span></div>
                )}
                <div className="flex justify-between gap-6 font-serif-display text-lg mt-2 px-3 py-2 rounded"
                  style={{ background: MAROON, color: "white" }}>
                  <span>Final Amount Due</span><span>{fmt(hasCredit ? 0 : balanceDue)}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Centered footer — mirrors the PDF's sign-off block */}
        <div className="text-center pt-6 mb-3" style={{ borderTop: `1px solid ${RULE}`, maxWidth: "280px", margin: "0 auto" }}>
          <div className="font-serif-display text-lg" style={{ color: MAROON }}>{inv.teacher_name}</div>
          {(studio.social_youtube || studio.social_instagram || studio.social_facebook) && (
            <div className="text-xs mt-2 space-x-3" data-testid="shared-socials">
              {studio.social_youtube && <a href={studio.social_youtube} target="_blank" rel="noreferrer" className="underline" style={{ color: LABEL }}>YouTube</a>}
              {studio.social_instagram && <a href={studio.social_instagram} target="_blank" rel="noreferrer" className="underline" style={{ color: LABEL }}>Instagram</a>}
              {studio.social_facebook && <a href={studio.social_facebook} target="_blank" rel="noreferrer" className="underline" style={{ color: LABEL }}>Facebook</a>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
