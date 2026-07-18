import React, { useState } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Loader2, CheckCircle2 } from "lucide-react";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const token = params.get("token") || "";

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
      await api.post("/auth/reset-password", { token, new_password: pw1 });
      setDone(true);
      setTimeout(() => nav("/login", { replace: true }), 2500);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Reset failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg)" }}>
      <div className="surface p-8 w-full max-w-sm" data-testid="reset-password-page">
        <div className="uppercase-label mb-2">Reset password</div>
        <h1 className="font-serif-display text-3xl mb-6">Set a new password</h1>

        {!token && (
          <div style={{ color: "var(--error)" }} className="text-sm mb-4">
            This reset link is missing its token. Please request a new one.
          </div>
        )}

        {done ? (
          <div className="text-center py-6">
            <CheckCircle2 size={40} className="mx-auto mb-3" style={{ color: "var(--success)" }} />
            <div className="font-serif-display text-xl mb-2">Password updated</div>
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>Redirecting to sign in…</div>
          </div>
        ) : (
          <form onSubmit={submit}>
            <label className="block mb-4">
              <span className="uppercase-label block mb-1">New password</span>
              <input
                required
                type="password"
                value={pw1}
                onChange={(e) => setPw1(e.target.value)}
                data-testid="reset-pw1-input"
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
                data-testid="reset-pw2-input"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
                autoComplete="new-password"
              />
            </label>
            {err && <div className="mb-3 text-sm" data-testid="reset-error" style={{ color: "var(--error)" }}>{err}</div>}
            <button
              type="submit"
              disabled={loading || !token}
              data-testid="reset-submit-btn"
              className="btn-pill w-full flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="animate-spin" size={16} />}
              Update password
            </button>
            <div className="mt-6 text-center text-xs" style={{ color: "var(--text-muted)" }}>
              <Link to="/login" className="hover:underline">Back to sign in</Link>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
