import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStudentAuth } from "@/context/StudentAuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import InstallAppPrompt from "@/components/student/InstallAppPrompt";
import { Loader2, CheckCircle2 } from "lucide-react";

export default function StudentSetPasswordPage() {
  const { student, setPassword } = useStudentAuth();
  const nav = useNavigate();
  const [pw1, setPw1] = useState("");
  const [pw2, setPw2] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (pw1.length < 6) return setErr("Password must be at least 6 characters.");
    if (pw1 !== pw2) return setErr("Passwords do not match.");
    setLoading(true);
    try {
      await setPassword(pw1);
      setDone(true);
    } catch (e2) {
      setErr(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't set your password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-16" style={{ background: "var(--bg)" }}>
      <div className="surface p-8 w-full max-w-sm" data-testid="portal-set-password-page">
        {done ? (
          <>
            <div className="text-center mb-6">
              <CheckCircle2 size={40} className="mx-auto mb-3" style={{ color: "var(--success)" }} />
              <div className="font-serif-display text-xl mb-1">Password set{student?.name ? `, ${student.name}!` : "!"}</div>
              <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                You're all set. Next time, sign in with your email and this password.
              </div>
            </div>
            <InstallAppPrompt />
            <button
              type="button"
              onClick={() => nav("/portal/schedule", { replace: true })}
              className="btn-pill w-full mt-4"
              data-testid="portal-set-password-continue"
            >
              Continue to portal
            </button>
          </>
        ) : (
          <form onSubmit={submit}>
            <div className="uppercase-label mb-2">Welcome</div>
            <h2 className="font-serif-display text-3xl mb-2">Set your password</h2>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
              This is a one-time step — after this you'll sign in with your email and password.
            </p>

            <label className="block mb-4">
              <span className="uppercase-label block mb-1">New password</span>
              <input
                required
                type="password"
                value={pw1}
                onChange={(e) => setPw1(e.target.value)}
                data-testid="portal-set-password-pw1"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
                autoComplete="new-password"
              />
            </label>
            <label className="block mb-4">
              <span className="uppercase-label block mb-1">Confirm password</span>
              <input
                required
                type="password"
                value={pw2}
                onChange={(e) => setPw2(e.target.value)}
                data-testid="portal-set-password-pw2"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
                autoComplete="new-password"
              />
            </label>
            {err && <div className="mb-3 text-sm" data-testid="portal-set-password-error" style={{ color: "var(--error)" }}>{err}</div>}
            <button
              type="submit"
              disabled={loading}
              data-testid="portal-set-password-submit"
              className="btn-pill w-full flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="animate-spin" size={16} />}
              Set password
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
