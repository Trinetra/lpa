import React, { createContext, useContext, useEffect, useState } from "react";
import { api, API } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // null = checking, false = not authed, object = authed
  const [user, setUser] = useState(null);

  useEffect(() => {
    let cancelled = false;
    // Use fetch (not axios) so a 401 is a normal Response, not a thrown
    // AxiosError — avoids polluting the console / preview error overlay
    // on the very first anonymous page-load.
    fetch(`${API}/auth/me`, { credentials: "include" })
      .then(async (r) => {
        if (cancelled) return;
        if (r.ok) setUser(await r.json());
        else setUser(false);
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
    setUser({ id: data.id, email: data.email, name: data.name });
    return data;
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      // ignore
    }
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
