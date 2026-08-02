import React, { useState } from "react";
import { Navigate } from "react-router-dom";
import { useStudentAuth } from "@/context/StudentAuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { Loader2, Mail } from "lucide-react";

const HERO_IMG = "/hero-photos/hero1.jpg";

export default function StudentLoginPage() {
  const { student, requestLink } = useStudentAuth();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [sent, setSent] = useState(false);

  if (student && student !== false && student !== null)
    return <Navigate to="/portal/schedule" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      await requestLink(email);
      setSent(true);
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

          {sent ? (
            <div data-testid="portal-login-sent" className="text-sm space-y-4" style={{ color: "var(--text-muted)" }}>
              <div className="flex items-center gap-2" style={{ color: "var(--text)" }}>
                <Mail size={18} /> Check your email
              </div>
              <p>
                If <span style={{ color: "var(--text)" }}>{email}</span> is on file, we've sent a sign-in link.
                It expires in 15 minutes.
              </p>
              <button type="button" className="btn-ghost w-full" data-testid="portal-login-try-again"
                onClick={() => setSent(false)}>
                Use a different email
              </button>
            </div>
          ) : (
            <>
              <label className="block mb-6">
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

              {err && (
                <div data-testid="portal-login-error" className="mb-4 text-sm" style={{ color: "var(--error)" }}>
                  {err}
                </div>
              )}

              <button type="submit" data-testid="portal-login-submit-btn" disabled={loading}
                className="btn-pill w-full flex items-center justify-center gap-2">
                {loading && <Loader2 className="animate-spin" size={16} />}
                Send me a sign-in link
              </button>
              <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }}>
                No password needed — we'll email you a one-time link.
              </p>
            </>
          )}
        </form>
      </div>
    </div>
  );
}
