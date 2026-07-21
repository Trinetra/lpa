import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Loader2 } from "lucide-react";

const HERO_PHOTOS = [
  "hero1.jpg",
  "hero2.jpg",
  "hero3.jpg",
  "hero4.jpg",
  "hero5.jpg",
  "hero6.jpg",
  "hero7.jpg",
  "hero8.jpg",
  "hero9.jpg",
];

const HERO_IMG =
  "/hero-photos/" + HERO_PHOTOS[Math.floor(Math.random() * HERO_PHOTOS.length)];

export default function LoginPage() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);

  if (user && user !== false && user !== null)
    return <Navigate to="/dashboard" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      await login(email, password);
      nav("/dashboard", { replace: true });
    } catch (e2) {
      setErr(formatApiErrorDetail(e2?.response?.data?.detail) || e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen grid md:grid-cols-2" style={{ background: "var(--bg)" }}>
      {/* Full-bleed background photo — mobile only. Desktop uses the split
          panel below instead, so this is hidden at md: and up. */}
      <div className="md:hidden fixed inset-0 z-0">
        <img
          src={HERO_IMG}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 w-full h-full object-cover"
          style={{ filter: "brightness(0.6) saturate(1.05)" }}
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, rgba(26,24,22,0.55) 0%, rgba(26,24,22,0.85) 100%)",
          }}
        />
      </div>

      {/* Left visual — desktop only */}
      <div className="hidden md:block relative overflow-hidden z-10">
        <img
          src={HERO_IMG}
          alt="Dancer"
          className="absolute inset-0 w-full h-full object-cover"
          style={{ filter: "brightness(0.6) saturate(1.05)" }}
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(120deg, rgba(26,24,22,0.55) 0%, rgba(26,24,22,0.75) 100%)",
          }}
        />
        <div className="relative z-10 h-full flex flex-col justify-between p-12">
          <div className="font-serif-display text-3xl" style={{ color: "#f5e6d3" }}>
            Lakshmi
          </div>
          <div>
            <div className="uppercase-label mb-3" style={{ color: "#f5e6d3" }}>
              For dance teachers, made simple
            </div>
            <h1
              className="font-serif-display text-4xl sm:text-5xl lg:text-6xl leading-[1.05]"
              style={{ color: "#f5e6d3" }}
            >
              Track classes.
              <br />
              Bill students.
              <br />
              <span style={{ color: "var(--primary)" }}>Get paid.</span>
            </h1>
            <p className="mt-6 max-w-md text-sm" style={{ color: "rgba(245,230,211,0.7)" }}>
              A quiet ledger for your studio—one place for rosters, rates, hours
              taught, and outstanding dues.
            </p>
          </div>
        </div>
      </div>

      {/* Form */}
      <div className="relative z-10 flex flex-col items-center justify-center px-6 py-16">
        <div className="md:hidden text-center mb-8 font-serif-display text-3xl" style={{ color: "#f5e6d3" }}>
          Lakshmi
        </div>
        <form
          onSubmit={submit}
          data-testid="login-form"
          className="w-full max-w-sm surface p-8"
        >
          <div className="uppercase-label mb-2">Sign in</div>
          <h2 className="font-serif-display text-3xl mb-8">Welcome back.</h2>

          <label className="block mb-4">
            <span className="uppercase-label block mb-2">Email</span>
            <input
              data-testid="login-email"
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
              data-testid="login-password"
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
              data-testid="forgot-password-link"
              onClick={() => setForgotOpen(true)}
              className="text-xs hover:underline"
              style={{ color: "var(--text-muted)" }}
            >
              Forgot password?
            </button>
          </div>

          {err && (
            <div data-testid="login-error" className="mb-4 text-sm" style={{ color: "var(--error)" }}>
              {err}
            </div>
          )}

          <button
            type="submit"
            data-testid="login-submit-btn"
            disabled={loading}
            className="btn-pill w-full flex items-center justify-center gap-2"
          >
            {loading && <Loader2 className="animate-spin" size={16} />}
            Enter Studio
          </button>
        </form>
      </div>
      {forgotOpen && <ForgotPasswordModal onClose={() => setForgotOpen(false)} defaultEmail={email} />}
    </div>
  );
}

function ForgotPasswordModal({ onClose, defaultEmail }) {
  const [email, setEmail] = React.useState(defaultEmail || "");
  const [sending, setSending] = React.useState(false);
  const [sent, setSent] = React.useState(false);
  const [err, setErr] = React.useState("");

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
      <form onSubmit={submit} data-testid="forgot-form" className="surface w-full max-w-sm p-6">
        <div className="uppercase-label mb-2">Reset password</div>
        <h3 className="font-serif-display text-2xl mb-4">Forgot your password?</h3>
        {sent ? (
          <>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
              If an account exists for <span style={{ color: "var(--text)" }}>{email}</span>, we've sent a reset link.
              Check your inbox (and spam folder) for a message from {process.env.REACT_APP_APP_NAME || "the studio ledger"}.
            </p>
            <button type="button" onClick={onClose} className="btn-pill w-full" data-testid="forgot-done-btn">Got it</button>
          </>
        ) : (
          <>
            <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
              Enter the email you use to sign in. We'll send you a link to choose a new password.
            </p>
            <label className="block mb-4">
              <span className="uppercase-label block mb-1">Email</span>
              <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                data-testid="forgot-email-input"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
            </label>
            {err && <div className="mb-3 text-sm" style={{ color: "var(--error)" }}>{err}</div>}
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="btn-ghost flex-1" data-testid="forgot-cancel-btn">Cancel</button>
              <button type="submit" disabled={sending} className="btn-pill flex-1" data-testid="forgot-send-btn">
                {sending ? "Sending..." : "Send reset link"}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
