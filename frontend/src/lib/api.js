import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;
const TOKEN_KEY = "kalpana_access_token";

export function setStoredToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

// Attach Bearer token from localStorage on every request (belt & suspenders
// alongside httpOnly cookies — needed when cookies are blocked in
// iframe / third-party contexts).
api.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers = config.headers || {};
    if (!config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// A separate axios instance + token for the student portal, so a teacher
// previewing /portal in the same browser tab can't clobber (or be clobbered
// by) their own session — the backend also uses distinct cookie names for
// the two, but this keeps the bearer-token belt-and-suspenders layer apart too.
const STUDENT_TOKEN_KEY = "kalpana_student_access_token";

export function setStoredStudentToken(token) {
  if (token) localStorage.setItem(STUDENT_TOKEN_KEY, token);
  else localStorage.removeItem(STUDENT_TOKEN_KEY);
}

export function getStoredStudentToken() {
  try {
    return localStorage.getItem(STUDENT_TOKEN_KEY);
  } catch {
    return null;
  }
}

export const studentApi = axios.create({
  baseURL: API,
  withCredentials: true,
});

studentApi.interceptors.request.use((config) => {
  const token = getStoredStudentToken();
  if (token) {
    config.headers = config.headers || {};
    if (!config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}
