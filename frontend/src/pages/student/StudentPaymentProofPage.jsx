import React, { useEffect, useRef, useState } from "react";
import { studentApi, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { UploadCloud } from "lucide-react";

const STATUS_COLOR = {
  pending: "var(--text-muted)",
  reviewed: "var(--success)",
};

export default function StudentPaymentProofPage() {
  const [proofs, setProofs] = useState(null);
  const [file, setFile] = useState(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef(null);

  const load = () => {
    studentApi.get("/student/payment-proofs").then((r) => setProofs(r.data));
  };

  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (!file) {
      toast.error("Choose a file first");
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (amount) fd.append("amount_claimed", amount);
      if (note) fd.append("note", note);
      await studentApi.post("/student/payment-proofs", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("Uploaded — your teacher will review it");
      setFile(null);
      setAmount("");
      setNote("");
      if (fileInput.current) fileInput.current.value = "";
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  if (!proofs) return <div data-testid="portal-proofs-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="portal-payment-proof-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Payments</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Upload proof of payment</h1>
      </header>

      <form onSubmit={submit} className="surface p-6 space-y-4">
        <label className="block">
          <span className="uppercase-label block mb-2">File (image or PDF)</span>
          <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            data-testid="portal-proof-file-input"
            className="w-full text-sm" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Amount paid (optional)</span>
            <input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
              data-testid="portal-proof-amount-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Note (optional)</span>
            <input type="text" value={note} onChange={(e) => setNote(e.target.value)}
              data-testid="portal-proof-note-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <button type="submit" disabled={uploading} className="btn-pill flex items-center gap-2"
          data-testid="portal-proof-upload-btn">
          <UploadCloud size={16} /> {uploading ? "Uploading…" : "Upload"}
        </button>
      </form>

      <section>
        <div className="uppercase-label mb-3">Your uploads</div>
        <div className="surface">
          {proofs.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No uploads yet.</div>
          )}
          {proofs.map((p) => (
            <div key={p.id} className="flex justify-between px-6 py-3 text-sm"
              style={{ borderTop: "1px solid var(--border)" }} data-testid={`portal-proof-${p.id}`}>
              <div>
                <div>{p.uploaded_at?.slice(0, 10)}</div>
                {p.amount_claimed != null && (
                  <div style={{ color: "var(--text-muted)" }}>₹{Number(p.amount_claimed).toLocaleString("en-IN")}</div>
                )}
                {p.note && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{p.note}</div>}
              </div>
              <div className="uppercase-label" style={{ color: STATUS_COLOR[p.status] || "var(--text)" }}>
                {p.status}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
