import React, { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useStudentAuth } from "@/context/StudentAuthContext";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Loader2 } from "lucide-react";

const HERO_IMG = "/hero-photos/hero1.jpg";

export default function StudentLoginPage() {
  const { student, login } = useStudentAuth();
  const [params] = useSearchParams();
  const [email, setEmail] = useState(() => params.get("email") || "");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);

  if (student && student !== false && student !== null)
    return <Navigate to="/portal/schedule" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      await login(email, password);
    } catch (e2) {
      setErr(formatApiErrorDetail(e2?.response?.data?.detail) || e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen grid md:grid-cols-2" style={{ background: "var(--bg)" }}>
      <div className="md:hidden fixed inset-0 z-0">
        <img src={HERO_IMG} alt="" aria-hidden="true" className="absolute inset-0 w-full h-full object-cover"
          style={{ filter: "brightness(0.6) saturate(1.05)" }} />
        <div className="absolute inset-0"
          style={{ background: "linear-gradient(180deg, rgba(26,24,22,0.55) 0%, rgba(26,24,22,0.85) 100%)" }} />
      </div>

      <div className="hidden md:block relative overflow-hidden z-10">
        <img src={HERO_IMG} alt="Dancer" className="absolute inset-0 w-full h-full object-cover"
          style={{ filter: "brightness(0.6) saturate(1.05)" }} />
        <div className="absolute inset-0"
          style={{ background: "linear-gradient(120deg, rgba(26,24,22,0.55) 0%, rgba(26,24,22,0.75) 100%)" }} />
        <div className="relative z-10 h-full flex flex-col justify-between p-12">
          <div />
          <div>
            <h1 className="font-serif-display text-xl sm:text-2xl italic leading-snug"
              style={{ color: "#e8c48a", letterSpacing: "0.02em", fontWeight: 500 }}>
              Student portal
            </h1>
          </div>
        </div>
      </div>

      <div className="relative z-10 flex flex-col items-center justify-center px-6 py-16">
        <form onSubmit={submit} data-testid="portal-login-form" className="w-full max-w-sm surface p-8">
          <div className="uppercase-label mb-2">Student sign in</div>
          <h2 className="font-serif-display text-3xl mb-8">Welcome back!</h2>

          <label className="block mb-4">
            <span className="uppercase-label block mb-2">Email</span>
            <input
              data-testid="portal-login-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)] transition-colors"
              autoComplete="email"
            />
          </label>
          <label className="block mb-2">
            <span className="uppercase-label block mb-2">Password</span>
            <input
              data-testid="portal-login-password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)] transition-colors"
              autoComplete="current-password"
            />
          </label>
          <div className="flex justify-end mb-6">
            <button
              type="button"
              data-testid="portal-forgot-password-link"
              onClick={() => setForgotOpen(true)}
              className="text-xs hover:underline"
              style={{ color: "var(--text-muted)" }}
            >
              Forgot password?
            </button>
          </div>

          {err && (
            <div data-testid="portal-login-error" className="mb-4 text-sm" style={{ color: "var(--error)" }}>
              {err}
            </div>
          )}

          <button type="submit" data-testid="portal-login-submit-btn" disabled={loading}
            className="btn-pill w-full flex items-center justify-center gap-2">
            {loading && <Loader2 className="animate-spin" size={16} />}
            Sign in
          </button>
          <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }}>
            New here? Ask your teacher to send you an invite link.
          </p>
        </form>
      </div>
      {forgotOpen && <ForgotPasswordModal onClose={() => setForgotOpen(false)} defaultEmail={email} />}
    </div>
  );
}

function ForgotPasswordModal({ onClose, defaultEmail }) {
  const [email, setEmail] = useState(defaultEmail || "");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setSending(true);
    setErr("");
    try {
      await api.post("/auth/forgot-password", { email });
      setSent(true);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Something went wrong");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }}>
      <form onSubmit={submit} data-testid="portal-forgot-form" className="surface w-full max-w-sm p-6">
        <div className="uppercase-label mb-2">Reset password</div>
        <h3 className="font-serif-display text-2xl mb-4">Forgot your password?</h3>
        {sent ? (
          <>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
              If an account exists for <span style={{ color: "var(--text)" }}>{email}</span>, we've sent a reset link.
            </p>
            <button type="button" onClick={onClose} className="btn-pill w-full" data-testid="portal-forgot-done-btn">Got it</button>
          </>
        ) : (
          <>
            <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
              Enter the email you sign in with. We'll send you a link to choose a new password.
            </p>
            <label className="block mb-4">
              <span className="uppercase-label block mb-1">Email</span>
              <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                data-testid="portal-forgot-email-input"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
            </label>
            {err && <div className="mb-3 text-sm" style={{ color: "var(--error)" }}>{err}</div>}
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="btn-ghost flex-1" data-testid="portal-forgot-cancel-btn">Cancel</button>
              <button type="submit" disabled={sending} className="btn-pill flex-1" data-testid="portal-forgot-send-btn">
                {sending ? "Sending..." : "Send reset link"}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
