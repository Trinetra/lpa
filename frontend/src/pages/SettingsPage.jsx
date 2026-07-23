import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import { KeyRound, Upload, Save, Loader2, CalendarClock, Link2, Unlink, CheckCircle2, HardDriveDownload } from "lucide-react";
import { toast } from "sonner";

function BackupCard() {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);

  const load = () => {
    api.get("/backup/status").then((r) => setStatus(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const runNow = async () => {
    setRunning(true);
    try {
      const { data } = await api.post("/backup/run");
      toast.success(`Backup uploaded: ${data.filename}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Backup failed");
      load();
    } finally {
      setRunning(false);
    }
  };

  if (!status) return null;

  return (
    <div data-testid="backup-card" className="surface p-6">
      <div className="flex items-center gap-2 mb-1">
        <HardDriveDownload size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">Data safety</div>
      </div>
      <h2 className="font-serif-display text-2xl mb-2">Automatic backups</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
        {status.connected
          ? "A daily backup (a restorable database archive plus an Excel workbook with every record, one sheet per type) is uploaded to a \"Backups\" folder in your connected Google Drive."
          : "Connect Google Calendar above to enable automatic backups — the same connection is used for both."}
      </p>

      {status.last_backup_at && (
        <div className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
          Last attempt: {new Date(status.last_backup_at).toLocaleString("en-IN")} —{" "}
          <span style={{ color: status.last_backup_ok ? "var(--success)" : "var(--error)" }}>
            {status.last_backup_ok ? "succeeded" : "failed"}
          </span>
        </div>
      )}

      {status.connected && (
        <button
          type="button"
          onClick={runNow}
          disabled={running}
          data-testid="backup-run-btn"
          className="btn-pill flex items-center gap-2"
        >
          <HardDriveDownload size={16} /> {running ? "Backing up…" : "Back up now"}
        </button>
      )}
    </div>
  );
}

function CalendarConnectCard() {
  const [status, setStatus] = useState(null);
  const [calendarName, setCalendarName] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [savingName, setSavingName] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const load = () => {
    api.get("/calendar/status").then((r) => {
      setStatus(r.data);
      setCalendarName(r.data.calendar_name);
    }).catch(() => {});
  };

  useEffect(() => {
    load();
    if (searchParams.get("calendar") === "connected") {
      toast.success("Google Calendar connected");
      searchParams.delete("calendar");
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveName = async () => {
    setSavingName(true);
    try {
      await api.patch("/calendar/name", { calendar_name: calendarName });
      toast.success("Calendar name saved");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't save name");
    } finally {
      setSavingName(false);
    }
  };

  const connect = async () => {
    setConnecting(true);
    try {
      const { data } = await api.get("/calendar/connect");
      window.location.href = data.url;
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't start Google connection");
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Disconnect Google Calendar? Existing events will stay on your calendar but stop updating.")) return;
    setDisconnecting(true);
    try {
      await api.post("/calendar/disconnect");
      toast.success("Disconnected");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Failed");
    } finally {
      setDisconnecting(false);
    }
  };

  if (!status) return null;

  const nameChanged = calendarName.trim() && calendarName.trim() !== status.calendar_name;

  return (
    <div data-testid="calendar-connect-card" className="surface p-6">
      <div className="flex items-center gap-2 mb-1">
        <CalendarClock size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">Integrations</div>
      </div>
      <div className="flex items-center gap-3 mb-2">
        <h2 className="font-serif-display text-2xl">Google Calendar</h2>
        {status.connected && (
          <span
            data-testid="calendar-connected-badge"
            className="flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ color: "var(--success)", background: "color-mix(in srgb, var(--success) 15%, transparent)" }}
          >
            <CheckCircle2 size={12} /> Connected
          </span>
        )}
      </div>

      {!status.configured && (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Google Calendar sync isn't set up on this server yet.
        </p>
      )}

      {status.configured && (
        <>
          <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
            {status.connected
              ? `Your weekly schedule syncs to your "${status.calendar_name}" calendar, with reminders 30 minutes before each class.`
              : "Connect your Google account to automatically keep a calendar in sync with your weekly schedule."}
          </p>

          {!status.connected && (
            <label className="block mb-4 max-w-sm">
              <span className="uppercase-label block mb-1">Calendar name</span>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={calendarName}
                  onChange={(e) => setCalendarName(e.target.value)}
                  data-testid="calendar-name-input"
                  className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
                />
                {nameChanged && (
                  <button
                    type="button"
                    onClick={saveName}
                    disabled={savingName}
                    data-testid="calendar-name-save-btn"
                    className="btn-ghost shrink-0"
                  >
                    {savingName ? "Saving…" : "Save"}
                  </button>
                )}
              </div>
            </label>
          )}

          {status.connected ? (
            <button
              type="button"
              onClick={disconnect}
              disabled={disconnecting}
              data-testid="calendar-disconnect-btn"
              className="btn-ghost flex items-center gap-2"
              style={{ color: "var(--error)" }}
            >
              <Unlink size={16} /> {disconnecting ? "Disconnecting…" : "Disconnect"}
            </button>
          ) : (
            <button
              type="button"
              onClick={connect}
              disabled={connecting}
              data-testid="calendar-connect-btn"
              className="btn-pill flex items-center gap-2"
            >
              <Link2 size={16} /> {connecting ? "Redirecting…" : "Connect Google Calendar"}
            </button>
          )}
        </>
      )}
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
    zoom_meeting_id: profile?.zoom_meeting_id || "",
    social_youtube: profile?.social_youtube || "",
    social_instagram: profile?.social_instagram || "",
    social_facebook: profile?.social_facebook || "",
    international_payment_details: profile?.international_payment_details || "",
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
        studio_name: form.studio_name,
        teacher_name: form.teacher_name,
        contact_phone: form.contact_phone,
        contact_upi: form.contact_upi,
        contact_email: form.contact_email,
        logo_path: form.logo_path === null ? "" : form.logo_path,
        zoom_meeting_id: form.zoom_meeting_id,
        social_youtube: form.social_youtube,
        social_instagram: form.social_instagram,
        social_facebook: form.social_facebook,
        international_payment_details: form.international_payment_details,
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
        <label className="sm:col-span-2">
          <span className="uppercase-label block mb-1">Zoom meeting ID</span>
          <input value={form.zoom_meeting_id} onChange={(e) => setForm({ ...form, zoom_meeting_id: e.target.value })}
            data-testid="studio-zoom-input"
            placeholder="e.g. 123 456 7890"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Added as a join link on every class synced to Google Calendar. Passcode isn't included — share that separately if your room needs one.
          </div>
        </label>
        <label className="sm:col-span-2">
          <span className="uppercase-label block mb-1">Social links (shown on invoices)</span>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <input value={form.social_youtube} onChange={(e) => setForm({ ...form, social_youtube: e.target.value })}
              data-testid="studio-youtube-input"
              placeholder="YouTube URL"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
            <input value={form.social_instagram} onChange={(e) => setForm({ ...form, social_instagram: e.target.value })}
              data-testid="studio-instagram-input"
              placeholder="Instagram URL"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
            <input value={form.social_facebook} onChange={(e) => setForm({ ...form, social_facebook: e.target.value })}
              data-testid="studio-facebook-input"
              placeholder="Facebook URL"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </div>
        </label>
        <label className="sm:col-span-2">
          <span className="uppercase-label block mb-1">International payment details (for foreign tour invoices)</span>
          <textarea rows={3} value={form.international_payment_details}
            onChange={(e) => setForm({ ...form, international_payment_details: e.target.value })}
            data-testid="studio-intl-payment-input"
            placeholder="Bank name, account number, SWIFT/IBAN, etc."
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Shown instead of your UPI details on non-INR tour invoices, since UPI only works for INR payments.
          </div>
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
      <CalendarConnectCard />
      <BackupCard />
      <ChangePasswordCard />
    </div>
  );
}
