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

  const requestLink = async (email) => {
    const { data } = await studentApi.post("/student/auth/request-link", { email });
    return data;
  };

  const verify = async (token) => {
    const { data } = await studentApi.post("/student/auth/verify", { token });
    if (data.token) setStoredStudentToken(data.token);
    setStudent({ id: data.id, name: data.name });
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
    <StudentAuthContext.Provider value={{ student, setStudent, requestLink, verify, logout }}>
      {children}
    </StudentAuthContext.Provider>
  );
}

export function useStudentAuth() {
  return useContext(StudentAuthContext);
}
