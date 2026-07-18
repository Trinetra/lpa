import React, { createContext, useContext, useEffect, useState } from "react";
import { api, API, setStoredToken, getStoredToken } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // null = checking, false = not authed, object = authed
  const [user, setUser] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const token = getStoredToken();
    const headers = { credentials: "include" };
    const opts = token
      ? { credentials: "include", headers: { Authorization: `Bearer ${token}` } }
      : headers;
    fetch(`${API}/auth/me`, opts)
      .then(async (r) => {
        if (cancelled) return;
        if (r.ok) setUser(await r.json());
        else {
          setStoredToken(null);
          setUser(false);
        }
      })
      .catch(() => {
        if (!cancelled) setUser(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    if (data.token) setStoredToken(data.token);
    setUser({ id: data.id, email: data.email, name: data.name });
    return data;
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      // ignore
    }
    setStoredToken(null);
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
