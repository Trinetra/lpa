import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { api } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import {
  LayoutDashboard,
  Users,
  BookOpenCheck,
  Wallet,
  FileText,
  BarChart3,
  Settings,
  Sun,
  Moon,
  LogOut,
  CalendarClock,
  Plane,
  MoreHorizontal,
  X,
} from "lucide-react";

export default function AppLayout() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const nav = useNavigate();
  const location = useLocation();
  const [profile, setProfile] = useState(null);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => { setMoreOpen(false); }, [location.pathname]);

  // Record top-level page visits for dashboard shortcuts. Tour tab visits are
  // tracked separately inside TourDetailPage (it knows which tab is active).
  useEffect(() => {
    const destKey = location.pathname.replace(/^\//, "").split("/")[0];
    if (["students", "schedule", "classes", "payments", "invoices", "charts"].includes(destKey)) {
      api.post("/visits", { dest_key: destKey }).catch(() => {});
    }
  }, [location.pathname]);

  useEffect(() => {
    api.get("/profile").then((r) => setProfile(r.data)).catch(() => {});
  }, []);

  const studioName = profile?.studio_name || "Lakshmi Studio Ledger";

  const handleLogout = async () => {
    await logout();
    nav("/login", { replace: true });
  };

  const links = [
    { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, tid: "nav-dashboard" },
    { to: "/students", label: "Students", icon: Users, tid: "nav-students" },
    { to: "/schedule", label: "Schedule", icon: CalendarClock, tid: "nav-schedule" },
    { to: "/classes", label: "Classes", icon: BookOpenCheck, tid: "nav-classes" },
    { to: "/payments", label: "Payments", icon: Wallet, tid: "nav-payments" },
    { to: "/invoices", label: "Invoices", icon: FileText, tid: "nav-invoices" },
    { to: "/tours", label: "Tours", icon: Plane, tid: "nav-tours" },
    { to: "/charts", label: "Charts", icon: BarChart3, tid: "nav-charts" },
    { to: "/settings", label: "Settings", icon: Settings, tid: "nav-settings" },
  ];

  // The bottom bar only has room for a handful of one-tap items on a phone
  // screen — the rest live behind "More" so nothing gets squeezed unreadably
  // small or clipped off-screen.
  const primaryLinks = links.filter((l) =>
    ["/dashboard", "/students", "/classes", "/payments"].includes(l.to)
  );
  const overflowLinks = links.filter((l) => !primaryLinks.includes(l));
  const overflowHasActive = overflowLinks.some((l) => location.pathname.startsWith(l.to));

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>
      {/* Sidebar */}
      <aside
        data-testid="app-sidebar"
        className="hidden md:flex md:flex-col w-64 shrink-0 px-5 py-8 gap-2"
        style={{ background: "var(--bg)", borderRight: "1px solid var(--border)" }}
      >
        <div className="mb-10 flex items-center gap-3">
          {profile?.logo_path && (
            <AuthImage
              path={profile.logo_path}
              alt=""
              className="w-10 h-10 rounded-full object-cover shrink-0"
            />
          )}
          <div className="min-w-0">
            <div className="font-serif-display text-2xl truncate" style={{ color: "var(--primary)" }}>
              {studioName}
            </div>
            {profile?.teacher_name && (
              <div className="uppercase-label mt-1 truncate">{profile.teacher_name}</div>
            )}
          </div>
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
          <button
            data-testid="theme-toggle-btn"
            onClick={toggle}
            className="nav-link w-full"
            type="button"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
            <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </button>
          <div className="uppercase-label mb-2 mt-4">Signed in</div>
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
        style={{ background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2 min-w-0">
          {profile?.logo_path && (
            <AuthImage
              path={profile.logo_path}
              alt=""
              className="w-7 h-7 rounded-full object-cover shrink-0"
            />
          )}
          <div className="font-serif-display text-xl truncate" style={{ color: "var(--primary)" }}>{studioName}</div>
        </div>
        <div className="flex items-center gap-2">
          <button data-testid="m-theme-toggle-btn" onClick={toggle} className="btn-ghost text-xs p-2" type="button"
            title={theme === "dark" ? "Light mode" : "Dark mode"}>
            {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <button data-testid="mobile-logout-btn" onClick={handleLogout} className="btn-ghost text-xs" type="button">
            Log out
          </button>
        </div>
      </div>

      {/* Mobile "More" sheet */}
      {moreOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex items-end" onClick={() => setMoreOpen(false)}>
          <div className="absolute inset-0" style={{ background: "rgba(0,0,0,0.5)" }} />
          <div
            data-testid="mobile-more-sheet"
            onClick={(e) => e.stopPropagation()}
            className="relative w-full rounded-t-2xl px-4 pt-4 pb-8"
            style={{ background: "var(--bg)", borderTop: "1px solid var(--border)" }}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="uppercase-label">More</div>
              <button type="button" onClick={() => setMoreOpen(false)} data-testid="mobile-more-close" className="btn-ghost p-2">
                <X size={16} />
              </button>
            </div>
            <div className="flex flex-col gap-1">
              {overflowLinks.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  data-testid={`m-${l.tid}`}
                  className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                >
                  <l.icon size={18} strokeWidth={1.5} />
                  <span>{l.label}</span>
                </NavLink>
              ))}
              <button
                data-testid="mobile-more-logout-btn"
                onClick={handleLogout}
                className="nav-link w-full mt-2"
                type="button"
              >
                <LogOut size={18} strokeWidth={1.5} />
                <span>Log out</span>
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="flex-1 px-6 md:px-10 py-16 md:py-10 max-w-[1400px] mx-auto w-full">
        {/* Mobile bottom nav */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 z-30 flex justify-around px-2 py-2"
          style={{ background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
          {primaryLinks.map((l) => (
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
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            data-testid="mobile-more-btn"
            className="flex flex-col items-center gap-1 px-2 py-1 text-[10px]"
            style={{ color: overflowHasActive ? "var(--primary)" : "var(--text-muted)" }}
          >
            <MoreHorizontal size={18} strokeWidth={1.5} />
            <span>More</span>
          </button>
        </div>
        <Outlet />
      </main>
    </div>
  );
}
