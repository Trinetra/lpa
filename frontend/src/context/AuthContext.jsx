import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // null = checking, false = not authed, object = authed
  const [user, setUser] = useState(null);

  useEffect(() => {
    let mounted = true;
    api
      .get("/auth/me")
      .then((r) => mounted && setUser(r.data))
      .catch(() => mounted && setUser(false));
    return () => {
      mounted = false;
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
