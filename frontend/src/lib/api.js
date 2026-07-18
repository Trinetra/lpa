import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

// Attach a metadata flag to endpoints where a 401 is EXPECTED (i.e. the
// initial "am I logged in?" check). This keeps genuine auth failures visible
// while silencing the noisy expected 401 on first page load.
const SILENT_401_ENDPOINTS = ["/auth/me"];

api.interceptors.response.use(
  (r) => r,
  (error) => {
    const status = error?.response?.status;
    const url = error?.config?.url || "";
    if (status === 401 && SILENT_401_ENDPOINTS.some((p) => url.endsWith(p))) {
      // Expected — user is not logged in yet. Reject silently.
      // eslint-disable-next-line no-param-reassign
      error.__silent = true;
    }
    return Promise.reject(error);
  }
);

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
