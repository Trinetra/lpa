import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Picks one of her productions (edited on the Website page). Value is the
// production id, "" for none.
export default function ProductionSelect({ value, onChange, className, disabled, testid }) {
  const [productions, setProductions] = useState([]);
  useEffect(() => {
    api.get("/productions").then((r) => setProductions(r.data)).catch(() => {});
  }, []);
  return (
    <select value={value || ""} onChange={(e) => onChange(e.target.value)} className={className} disabled={disabled} data-testid={testid}>
      <option value="">— Not set —</option>
      {productions.map((p) => (
        <option key={p.id} value={p.id}>{p.title}{p.year ? ` (${p.year})` : ""}</option>
      ))}
    </select>
  );
}
