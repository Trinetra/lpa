import React, { useRef, useState } from "react";
import { studentApi, formatApiErrorDetail } from "@/lib/api";
import { useStudentAuth } from "@/context/StudentAuthContext";
import InstallAppCard from "@/components/student/InstallAppCard";
import StudentAuthImage from "@/components/student/StudentAuthImage";
import PushNotificationToggle from "@/components/PushNotificationToggle";
import { KeyRound, Loader2, Upload, User, BellRing } from "lucide-react";
import { toast } from "sonner";

function ProfilePhotoCard() {
  const { student, setStudent } = useStudentAuth();
  const [photoPath, setPhotoPath] = useState(student?.photo_path || null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const { data } = await studentApi.post("/student/me/photo", body, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPhotoPath(data.path);
      setStudent((s) => (s ? { ...s, photo_path: data.path } : s));
      toast.success("Photo updated");
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div data-testid="portal-photo-card" className="surface p-6">
      <div className="flex items-center gap-2 mb-6">
        <User size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">Profile</div>
      </div>
      <div className="flex items-center gap-4">
        <div className="w-16 h-16 rounded-full overflow-hidden shrink-0" style={{ background: "var(--surface-2)" }}>
          <StudentAuthImage
            path={photoPath}
            className="w-full h-full object-cover"
            testid="portal-photo-preview"
            fallback={
              <div className="w-full h-full flex items-center justify-center font-serif-display text-xl" style={{ color: "var(--primary)" }}>
                {(student?.name || "?").charAt(0)}
              </div>
            }
          />
        </div>
        <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
          className="btn-ghost flex items-center gap-2 text-xs" data-testid="portal-photo-upload-btn">
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} Change photo
        </button>
        <input ref={fileRef} type="file" accept="image/*" onChange={handleUpload} className="hidden" data-testid="portal-photo-input" />
      </div>
    </div>
  );
}

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

function NotificationsCard() {
  return (
    <div data-testid="portal-notifications-card" className="surface p-6">
      <div className="flex items-center gap-2 mb-1">
        <BellRing size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">Notifications</div>
      </div>
      <h2 className="font-serif-display text-2xl mb-2">Push notifications</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
        Get notified on this device when your teacher reschedules or cancels a class, and when
        your own change requests are approved or denied.
      </p>
      <PushNotificationToggle
        apiClient={studentApi}
        subscribeUrl="/student/push/subscribe"
        unsubscribeUrl="/student/push/unsubscribe"
        testidPrefix="portal-settings-push"
      />
    </div>
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
        <ProfilePhotoCard />
        <NotificationsCard />
        <InstallAppCard />
        <ChangePasswordCard />
      </div>
    </div>
  );
}
