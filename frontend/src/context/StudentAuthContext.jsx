import React, { createContext, useContext, useEffect, useState } from "react";
import { studentApi, API, setStoredStudentToken, getStoredStudentToken } from "@/lib/api";

const StudentAuthContext = createContext(null);

export function StudentAuthProvider({ children }) {
  // null = checking, false = not authed, object = authed
  const [student, setStudent] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const token = getStoredStudentToken();
    const opts = token
      ? { credentials: "include", headers: { Authorization: `Bearer ${token}` } }
      : { credentials: "include" };
    fetch(`${API}/student/me`, opts)
      .then(async (r) => {
        if (cancelled) return;
        if (r.ok) setStudent(await r.json());
        else {
          setStoredStudentToken(null);
          setStudent(false);
        }
      })
      .catch(() => {
        if (!cancelled) setStudent(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (email, password) => {
    const { data } = await studentApi.post("/student/auth/login", { email, password });
    if (data.token) setStoredStudentToken(data.token);
    // A successful password login guarantees a password_hash already exists.
    setStudent({ id: data.id, name: data.name, has_password: true });
    return data;
  };

  const acceptInvite = async (token) => {
    const { data } = await studentApi.post("/student/auth/accept-invite", { token });
    if (data.token) setStoredStudentToken(data.token);
    setStudent({ id: data.id, name: data.name, has_password: !data.must_set_password });
    return data;
  };

  const setPassword = async (password) => {
    const { data } = await studentApi.post("/student/auth/set-password", { password });
    setStudent((s) => (s ? { ...s, has_password: true } : s));
    return data;
  };

  const logout = async () => {
    try {
      await studentApi.post("/student/auth/logout");
    } catch (e) {
      // ignore
    }
    setStoredStudentToken(null);
    setStudent(false);
  };

  return (
    <StudentAuthContext.Provider value={{ student, setStudent, login, acceptInvite, setPassword, logout }}>
      {children}
    </StudentAuthContext.Provider>
  );
}

export function useStudentAuth() {
  return useContext(StudentAuthContext);
}
