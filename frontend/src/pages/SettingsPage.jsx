import React, { useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import { KeyRound, Upload, Save, Loader2 } from "lucide-react";
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
      await api.post("/auth/change-password", { current_password: current, new_password: pw1 });
      toast.success("Password updated");
      setCurrent(""); setPw1(""); setPw2("");
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="change-password-form" className="surface p-6">
      <div className="flex items-center gap-2 mb-1">
        <KeyRound size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">Security</div>
      </div>
      <h2 className="font-serif-display text-2xl mb-6">Change password</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="sm:col-span-1">
          <span className="uppercase-label block mb-1">Current password</span>
          <input required type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
            data-testid="cp-current-input"
            autoComplete="current-password"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">New password</span>
          <input required type="password" value={pw1} onChange={(e) => setPw1(e.target.value)}
            data-testid="cp-new-input"
            autoComplete="new-password"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Confirm new</span>
          <input required type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
            data-testid="cp-confirm-input"
            autoComplete="new-password"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>
      <div className="flex justify-end mt-4">
        <button type="submit" disabled={saving} className="btn-pill flex items-center gap-2" data-testid="cp-submit-btn">
          {saving && <Loader2 size={14} className="animate-spin" />} Update password
        </button>
      </div>
    </form>
  );
}

function StudioProfileCard({ profile, onSaved }) {
  const [form, setForm] = useState({
    studio_name: profile?.studio_name || "",
    teacher_name: profile?.teacher_name || profile?.name || "",
    contact_phone: profile?.contact_phone || "",
    contact_upi: profile?.contact_upi || "",
    contact_email: profile?.contact_email || profile?.email || "",
    logo_path: profile?.logo_path || null,
  });
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);

  const upload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/uploads/photo", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setForm((f) => ({ ...f, logo_path: data.path }));
      toast.success("Logo uploaded");
    } catch (e2) {
      toast.error("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        studio_name: form.studio_name || null,
        teacher_name: form.teacher_name || null,
        contact_phone: form.contact_phone || null,
        contact_upi: form.contact_upi || null,
        contact_email: form.contact_email || null,
        logo_path: form.logo_path || null,
      };
      const { data } = await api.patch("/profile", body);
      toast.success("Studio profile saved");
      onSaved(data);
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="studio-profile-form" className="surface p-6">
      <div className="uppercase-label mb-1">Branding</div>
      <h2 className="font-serif-display text-2xl mb-6">Studio profile</h2>

      <div className="flex items-center gap-5 mb-6">
        <div className="w-24 h-24 rounded overflow-hidden shrink-0" style={{ background: "var(--surface-2)" }}>
          <AuthImage
            path={form.logo_path}
            className="w-full h-full object-contain"
            fallback={
              <div className="w-full h-full flex items-center justify-center font-serif-display text-3xl" style={{ color: "var(--primary)" }}>
                {(form.studio_name || form.teacher_name || "L").charAt(0)}
              </div>
            }
          />
        </div>
        <div>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={upload}
            data-testid="logo-input" />
          <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
            data-testid="upload-logo-btn"
            className="btn-ghost flex items-center gap-2 text-xs">
            <Upload size={14} /> {uploading ? "Uploading..." : form.logo_path ? "Change logo" : "Upload logo"}
          </button>
          {form.logo_path && (
            <button type="button" onClick={() => setForm({ ...form, logo_path: null })}
              className="ml-2 text-xs" style={{ color: "var(--error)" }} data-testid="remove-logo-btn">
              Remove
            </button>
          )}
          <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
            Shown on invoices and the shared invoice page.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label>
          <span className="uppercase-label block mb-1">Studio name</span>
          <input value={form.studio_name} onChange={(e) => setForm({ ...form, studio_name: e.target.value })}
            data-testid="studio-name-input"
            placeholder="e.g. Lakshmi School of Dance"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Teacher name</span>
          <input value={form.teacher_name} onChange={(e) => setForm({ ...form, teacher_name: e.target.value })}
            data-testid="teacher-name-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Contact phone</span>
          <input value={form.contact_phone} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
            data-testid="studio-phone-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Contact email</span>
          <input type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
            data-testid="studio-email-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label className="sm:col-span-2">
          <span className="uppercase-label block mb-1">Payment ID (UPI / bank)</span>
          <input value={form.contact_upi} onChange={(e) => setForm({ ...form, contact_upi: e.target.value })}
            data-testid="studio-upi-input"
            placeholder="e.g. lakshmi@upi"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
      </div>

      <div className="flex justify-end mt-6">
        <button type="submit" disabled={saving} className="btn-pill flex items-center gap-2" data-testid="profile-save-btn">
          <Save size={14} /> {saving ? "Saving..." : "Save profile"}
        </button>
      </div>
    </form>
  );
}

export default function SettingsPage() {
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    api.get("/profile").then((r) => setProfile(r.data));
  }, []);

  return (
    <div data-testid="settings-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Settings</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Your studio</h1>
        <p className="mt-3 text-sm max-w-xl" style={{ color: "var(--text-muted)" }}>
          Set up your studio branding and change your password. Your studio name and logo
          appear on every invoice you send.
        </p>
      </header>
      {profile && <StudioProfileCard profile={profile} onSaved={setProfile} />}
      <ChangePasswordCard />
    </div>
  );
}
