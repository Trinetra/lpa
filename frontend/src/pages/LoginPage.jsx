import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { Loader2 } from "lucide-react";

const HERO_IMG =
  "https://images.pexels.com/photos/29016047/pexels-photo-29016047.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940";

export default function LoginPage() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("teacher@dance.com");
  const [password, setPassword] = useState("dance123");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

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
    <div className="min-h-screen grid md:grid-cols-2" style={{ background: "var(--bg)" }}>
      {/* Left visual */}
      <div className="hidden md:block relative overflow-hidden">
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
          <div className="font-serif-display text-3xl" style={{ color: "var(--secondary)" }}>
            Lakshmi
          </div>
          <div>
            <div className="uppercase-label mb-3" style={{ color: "var(--secondary)" }}>
              For dance teachers, made simple
            </div>
            <h1
              className="font-serif-display text-4xl sm:text-5xl lg:text-6xl leading-[1.05]"
              style={{ color: "var(--secondary)" }}
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
      <div className="flex items-center justify-center px-6 py-16">
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
          <label className="block mb-6">
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

          <p className="mt-6 text-xs" style={{ color: "var(--text-muted)" }}>
            Default credentials are already filled in for the demo.
          </p>
        </form>
      </div>
    </div>
  );
}
