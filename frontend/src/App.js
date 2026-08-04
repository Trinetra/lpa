import React, { useEffect } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { StudentAuthProvider, useStudentAuth } from "@/context/StudentAuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import AppLayout from "@/components/AppLayout";
import StudentPortalLayout from "@/components/StudentPortalLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import StudentsPage from "@/pages/StudentsPage";
import StudentDetailPage from "@/pages/StudentDetailPage";
import SchedulePage from "@/pages/SchedulePage";
import ClassesPage from "@/pages/ClassesPage";
import PaymentsPage from "@/pages/PaymentsPage";
import InvoicesPage from "@/pages/InvoicesPage";
import ChartsPage from "@/pages/ChartsPage";
import SettingsPage from "@/pages/SettingsPage";
import ResetPasswordPage from "@/pages/ResetPasswordPage";
import SharedInvoicePage from "@/pages/SharedInvoicePage";
import ToursPage from "@/pages/ToursPage";
import TourDetailPage from "@/pages/TourDetailPage";
import SharedTourPage from "@/pages/SharedTourPage";
import PortalActivityPage from "@/pages/PortalActivityPage";
import StudentLoginPage from "@/pages/student/StudentLoginPage";
import StudentAcceptInvitePage from "@/pages/student/StudentAcceptInvitePage";
import StudentSetPasswordPage from "@/pages/student/StudentSetPasswordPage";
import StudentSchedulePage from "@/pages/student/StudentSchedulePage";
import StudentDuesPage from "@/pages/student/StudentDuesPage";
import StudentProgressPage from "@/pages/student/StudentProgressPage";
import StudentNotesPage from "@/pages/student/StudentNotesPage";
import StudentPaymentProofPage from "@/pages/student/StudentPaymentProofPage";
import StudentSettingsPage from "@/pages/student/StudentSettingsPage";

function ProtectedRoute({ children }) {
  const { user } = useAuth();
  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center uppercase-label" style={{ background: "var(--bg)" }}>
        Checking session…
      </div>
    );
  }
  if (user === false) return <Navigate to="/login" replace />;
  return children;
}

function StudentProtectedRoute({ children, requirePassword = false }) {
  const { student } = useStudentAuth();
  if (student === null) {
    return (
      <div className="min-h-screen flex items-center justify-center uppercase-label" style={{ background: "var(--bg)" }}>
        Checking session…
      </div>
    );
  }
  if (student === false) return <Navigate to="/portal/login" replace />;
  // Freshly-accepted invites land here without a password yet — bounce them
  // to the forced set-password step before they can see anything else.
  if (requirePassword && student.has_password === false) {
    return <Navigate to="/portal/set-password" replace />;
  }
  return children;
}

// Swaps the site-wide web manifest for a student-specific one (different
// start_url/name) while anywhere under /portal, so "Add to Home Screen"
// installs a shortcut that opens straight into the portal instead of the
// teacher dashboard — reverted on unmount so the teacher app's own manifest
// comes back for every other route.
//
// Also swaps apple-mobile-web-app-title: iOS reads that tag (and
// apple-touch-icon) straight from the DOM at "Add to Home Screen" time
// rather than fetching the manifest, so this needs its own swap — but
// unlike the manifest fetch, there's no race here, since a student only
// taps Share -> Add to Home Screen well after this effect has already run.
function useStudentManifest() {
  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    const originalHref = link?.getAttribute("href");
    if (link) link.setAttribute("href", "/manifest-student.json");

    const titleMeta = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    const originalTitle = titleMeta?.getAttribute("content");
    if (titleMeta) titleMeta.setAttribute("content", "Student Portal");

    return () => {
      if (link && originalHref) link.setAttribute("href", originalHref);
      if (titleMeta && originalTitle) titleMeta.setAttribute("content", originalTitle);
    };
  }, []);
}

// Mounted as its own provider scope so the student's session token/context
// never mixes with the teacher's, even if both are open in one browser.
function StudentPortalRoutes() {
  useStudentManifest();
  return (
    <StudentAuthProvider>
      <Routes>
        <Route path="login" element={<StudentLoginPage />} />
        <Route path="accept-invite" element={<StudentAcceptInvitePage />} />
        <Route
          path="set-password"
          element={
            <StudentProtectedRoute>
              <StudentSetPasswordPage />
            </StudentProtectedRoute>
          }
        />
        <Route
          element={
            <StudentProtectedRoute requirePassword>
              <StudentPortalLayout />
            </StudentProtectedRoute>
          }
        >
          <Route index element={<Navigate to="schedule" replace />} />
          <Route path="schedule" element={<StudentSchedulePage />} />
          <Route path="dues" element={<StudentDuesPage />} />
          <Route path="progress" element={<StudentProgressPage />} />
          <Route path="notes" element={<StudentNotesPage />} />
          <Route path="payment-proof" element={<StudentPaymentProofPage />} />
          <Route path="settings" element={<StudentSettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="login" replace />} />
      </Routes>
    </StudentAuthProvider>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/invoice/:token" element={<SharedInvoicePage />} />
      <Route path="/tour/:token" element={<SharedTourPage />} />
      <Route path="/portal/*" element={<StudentPortalRoutes />} />
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/students" element={<StudentsPage />} />
        <Route path="/students/:id" element={<StudentDetailPage />} />
        <Route path="/schedule" element={<SchedulePage />} />
        <Route path="/classes" element={<ClassesPage />} />
        <Route path="/payments" element={<PaymentsPage />} />
        <Route path="/invoices" element={<InvoicesPage />} />
        <Route path="/tours" element={<ToursPage />} />
        <Route path="/tours/:id" element={<TourDetailPage />} />
        <Route path="/charts" element={<ChartsPage />} />
        <Route path="/requests" element={<PortalActivityPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      {/* Custom tour public links (e.g. pravaahacfm.com/tour2026) — tried only
          after every real app route above fails to match, since this is a
          single dynamic segment that would otherwise shadow nothing but
          could in principle collide if a tour slug ever matched a route
          name (blocked server-side via RESERVED_SLUGS). */}
      <Route path="/:slug" element={<SharedTourPage bySlug />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <div className="App">
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <AppRoutes />
            <Toaster
              position="top-right"
              toastOptions={{
                style: {
                  background: "var(--toast-bg)",
                  color: "var(--toast-fg)",
                  border: "1px solid var(--toast-border)",
                },
              }}
            />
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </div>
  );
}
