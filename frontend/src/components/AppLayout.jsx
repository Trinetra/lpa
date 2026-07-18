import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutDashboard,
  Users,
  BookOpenCheck,
  Wallet,
  FileText,
  LogOut,
} from "lucide-react";

export default function AppLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  const handleLogout = async () => {
    await logout();
    nav("/login", { replace: true });
  };

  const links = [
    { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, tid: "nav-dashboard" },
    { to: "/students", label: "Students", icon: Users, tid: "nav-students" },
    { to: "/classes", label: "Classes", icon: BookOpenCheck, tid: "nav-classes" },
    { to: "/payments", label: "Payments", icon: Wallet, tid: "nav-payments" },
    { to: "/invoices", label: "Invoices", icon: FileText, tid: "nav-invoices" },
  ];

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>
      {/* Sidebar */}
      <aside
        data-testid="app-sidebar"
        className="hidden md:flex md:flex-col w-64 shrink-0 px-5 py-8 gap-2"
        style={{ background: "#1a1816", borderRight: "1px solid var(--border)" }}
      >
        <div className="mb-10">
          <div className="font-serif-display text-2xl" style={{ color: "var(--primary)" }}>
            Kalpana
          </div>
          <div className="uppercase-label mt-1">Studio Ledger</div>
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
        <div className="mt-auto pt-6">
          <div className="uppercase-label mb-2">Signed in</div>
          <div className="text-sm truncate" style={{ color: "var(--text)" }}>
            {user?.name || user?.email}
          </div>
          <button
            data-testid="logout-btn"
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
        style={{ background: "#1a1816", borderBottom: "1px solid var(--border)" }}>
        <div className="font-serif-display text-xl" style={{ color: "var(--primary)" }}>Kalpana</div>
        <button data-testid="mobile-logout-btn" onClick={handleLogout} className="btn-ghost text-xs" type="button">
          Log out
        </button>
      </div>

      <main className="flex-1 px-6 md:px-10 py-16 md:py-10 max-w-[1400px] mx-auto w-full">
        {/* Mobile bottom nav */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 z-30 flex justify-around px-2 py-2"
          style={{ background: "#1a1816", borderTop: "1px solid var(--border)" }}>
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
