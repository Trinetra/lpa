import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useStudentAuth } from "@/context/StudentAuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function StudentAcceptInvitePage() {
  const { acceptInvite } = useStudentAuth();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [err, setErr] = useState("");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const token = params.get("token");
    if (!token) {
      setErr("This invite link is missing its token.");
      return;
    }
    acceptInvite(token)
      .then((data) => {
        nav(data.must_set_password ? "/portal/set-password" : "/portal/schedule", { replace: true });
      })
      .catch((e) => setErr(formatApiErrorDetail(e?.response?.data?.detail) || e.message));
  }, [params, acceptInvite, nav]);

  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg)" }}>
      <div className="surface p-8 w-full max-w-sm text-center" data-testid="portal-accept-invite-page">
        {err ? (
          <>
            <div className="uppercase-label mb-2" style={{ color: "var(--error)" }}>Couldn't sign you in</div>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>{err}</p>
            <Link to="/portal/login" className="btn-pill inline-block" data-testid="portal-accept-invite-retry">
              Go to sign in
            </Link>
          </>
        ) : (
          <div className="flex flex-col items-center gap-3 uppercase-label">
            <Loader2 className="animate-spin" size={20} />
            Setting up your account…
          </div>
        )}
      </div>
    </div>
  );
}
