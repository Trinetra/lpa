import React, { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

/**
 * Renders an <img> for a stored file path by fetching via API (auth cookie
 * or query-param token) and creating a blob URL.
 */
export default function AuthImage({ path, alt, className, fallback, testid }) {
  const { user } = useAuth();
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (!path) return;
    let revoked = false;
    let objectUrl = null;
    setErr(false);
    api
      .get("/uploads/file", { params: { path }, responseType: "blob" })
      .then((res) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(res.data);
        setSrc(objectUrl);
      })
      .catch(() => setErr(true));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, user?.id]);

  if (!path || err) return fallback || null;
  if (!src) {
    return (
      <div
        data-testid={testid ? `${testid}-loading` : undefined}
        className={className}
        style={{ background: "rgba(245,230,211,0.06)" }}
      />
    );
  }
  return <img data-testid={testid} src={src} alt={alt || ""} className={className} />;
}
