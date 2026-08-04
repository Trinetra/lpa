import React, { useState } from "react";
import { studentApi, formatApiErrorDetail } from "@/lib/api";
import InstallAppCard from "@/components/student/InstallAppCard";
import { KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";

function ChangePasswordCard() {
  const [current, setCurrent] = useState("");
  const [pw1, setPw1] = useState("");
  const [pw2, setPw2] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (pw1.length < 6) return toast.error("Password must be at least 6 characters");
    if (pw1 !== pw2) return toast.error("Passwords do not match");
    setSaving(true);
    try {
      await studentApi.post("/student/auth/change-password", { current_password: current, new_password: pw1 });
      toast.success("Password updated");
      setCurrent(""); setPw1(""); setPw2("");
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="portal-change-password-form" className="surface p-6">
      <div className="flex items-center gap-2 mb-1">
        <KeyRound size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">Security</div>
      </div>
      <h2 className="font-serif-display text-2xl mb-6">Change password</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="sm:col-span-1">
          <span className="uppercase-label block mb-1">Current password</span>
          <input required type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
            data-testid="portal-cp-current-input"
            autoComplete="current-password"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">New password</span>
          <input required type="password" value={pw1} onChange={(e) => setPw1(e.target.value)}
            data-testid="portal-cp-new-input"
            autoComplete="new-password"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Confirm new</span>
          <input required type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
            data-testid="portal-cp-confirm-input"
            autoComplete="new-password"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>
      <div className="flex justify-end mt-4">
        <button type="submit" disabled={saving} className="btn-pill flex items-center gap-2" data-testid="portal-cp-submit-btn">
          {saving && <Loader2 size={14} className="animate-spin" />} Update password
        </button>
      </div>
    </form>
  );
}

export default function StudentSettingsPage() {
  return (
    <div data-testid="portal-settings-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Your account</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Settings</h1>
      </header>

      <div className="space-y-6 max-w-xl">
        <InstallAppCard />
        <ChangePasswordCard />
      </div>
    </div>
  );
}
