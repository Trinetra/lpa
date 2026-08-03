import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useStudentAuth } from "@/context/StudentAuthContext";
import { useTheme } from "@/context/ThemeContext";
import { studentApi } from "@/lib/api";
import InstallAppPrompt from "@/components/student/InstallAppPrompt";
import {
  CalendarClock,
  Wallet,
  BookOpenCheck,
  NotebookPen,
  Receipt,
  Sun,
  Moon,
  LogOut,
} from "lucide-react";

export default function StudentPortalLayout() {
  const { logout } = useStudentAuth();
  const { theme, toggle } = useTheme();
  const nav = useNavigate();
  const [me, setMe] = useState(null);

  useEffect(() => {
    studentApi.get("/student/me").then((r) => setMe(r.data)).catch(() => {});
  }, []);

  const handleLogout = async () => {
    await logout();
    nav("/portal/login", { replace: true });
  };

  const links = [
    { to: "/portal/schedule", label: "Schedule", icon: CalendarClock, tid: "portal-nav-schedule" },
    { to: "/portal/dues", label: "Dues", icon: Wallet, tid: "portal-nav-dues" },
    { to: "/portal/progress", label: "Progress", icon: BookOpenCheck, tid: "portal-nav-progress" },
    { to: "/portal/notes", label: "Notes", icon: NotebookPen, tid: "portal-nav-notes" },
    { to: "/portal/payment-proof", label: "Payment proof", icon: Receipt, tid: "portal-nav-payment-proof" },
  ];

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>
      {/* Sidebar */}
      <aside
        data-testid="portal-sidebar"
        className="hidden md:flex md:flex-col w-64 shrink-0 px-5 py-8 gap-2"
        style={{ background: "var(--bg)", borderRight: "1px solid var(--border)" }}
      >
        <div className="mb-10">
          <div className="uppercase-label mb-1">Student portal</div>
          <div className="font-serif-display text-2xl truncate" style={{ color: "var(--primary)" }}>
            {me?.studio_name || me?.teacher_name || "Your studio"}
          </div>
          {me?.name && <div className="uppercase-label mt-2 truncate">{me.name}</div>}
        </div>
        <nav className="flex flex-col gap-1">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              data-testid={l.tid}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              <l.icon size={18} strokeWidth={1.5} />
              <span>{l.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto pt-6 space-y-3">
          <InstallAppPrompt />
          <button
            data-testid="portal-theme-toggle-btn"
            onClick={toggle}
            className="nav-link w-full"
            type="button"
          >
            {theme === "dark" ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
            <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </button>
          <button
            data-testid="portal-logout-btn"
            onClick={handleLogout}
            className="nav-link w-full mt-3"
            type="button"
          >
            <LogOut size={16} strokeWidth={1.5} />
            <span>Log out</span>
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-30 flex items-center justify-between px-4 py-3"
        style={{ background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
        <div className="font-serif-display text-xl truncate" style={{ color: "var(--primary)" }}>
          {me?.studio_name || me?.teacher_name || "Student portal"}
        </div>
        <button data-testid="portal-mobile-logout-btn" onClick={handleLogout} className="btn-ghost text-xs" type="button">
          Log out
        </button>
      </div>

      <main className="flex-1 px-6 md:px-10 py-16 md:py-10 pb-24 md:pb-10 max-w-[1000px] mx-auto w-full">
        {/* Mobile bottom nav */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 z-30 flex justify-around px-2 py-2"
          style={{ background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              data-testid={`m-${l.tid}`}
              className={({ isActive }) => `flex flex-col items-center gap-1 px-2 py-1 text-[10px] ${isActive ? "text-[color:var(--primary)]" : "text-[color:var(--text-muted)]"}`}
            >
              <l.icon size={18} strokeWidth={1.5} />
              <span>{l.label}</span>
            </NavLink>
          ))}
        </div>
        <Outlet />
      </main>
    </div>
  );
}
