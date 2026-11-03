import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { EyeOff } from "lucide-react";

// Library home: one card per production (edited on the Website page).
export const fmtSize = (n) => {
  if (!n) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i >= 2 ? 1 : 0)} ${units[i]}`;
};

export default function LibraryPage() {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/library").then((r) => setData(r.data)).catch(() => setData({ productions: [], trash_count: 0 }));
  }, []);

  if (data === null) return <div className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="library-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Productions</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Library</h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
          Music, lighting cues, videos, costumes, expenses — everything for each production, filed by performance.
        </p>
      </header>

      {data.productions.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>
          No productions yet. Add them on the <Link to="/website" className="underline">Website page</Link>.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {data.productions.map((p) => (
          <Link key={p.id} to={`/library/${p.id}`} data-testid={`library-production-${p.id}`} className="surface surface-hover p-5 block">
            <div className="uppercase-label mb-1 flex items-center gap-2">
              {p.year}
              {!p.show_on_website && <span className="flex items-center gap-1" title="Hidden from the website"><EyeOff size={11} /> hidden</span>}
            </div>
            <h3 className="font-serif-display text-xl">{p.title}</h3>
            {p.subtitle && <div className="text-sm italic" style={{ color: "var(--text-muted)" }}>{p.subtitle}</div>}
            <div className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
              {p.item_count ? `${p.item_count} item${p.item_count === 1 ? "" : "s"}${p.total_size ? ` · ${fmtSize(p.total_size)}` : ""}` : "Empty"}
            </div>
          </Link>
        ))}
      </div>

      {data.trash_count > 0 && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {data.trash_count} item{data.trash_count === 1 ? "" : "s"} in Trash — open a production and choose Trash to restore. Trash empties itself after 30 days.
        </p>
      )}
    </div>
  );
}
