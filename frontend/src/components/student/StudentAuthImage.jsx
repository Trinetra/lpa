import React, { useEffect, useState } from "react";
import { studentApi } from "@/lib/api";

/**
 * Same as the teacher-side AuthImage, but authenticated with the student's
 * own bearer token via studentApi instead of the teacher's — GET
 * /uploads/file accepts either since it just checks for a valid signed JWT.
 */
export default function StudentAuthImage({ path, alt, className, fallback, testid }) {
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (!path) return;
    let revoked = false;
    let objectUrl = null;
    setErr(false);
    studentApi
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
  }, [path]);

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
