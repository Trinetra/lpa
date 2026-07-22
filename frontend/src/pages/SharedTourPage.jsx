import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/lib/api";
import { MapPin } from "lucide-react";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

export default function SharedTourPage() {
  const { token } = useParams();
  const [tour, setTour] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    axios
      .get(`${API}/tours/share/${token}`)
      .then((r) => setTour(r.data))
      .catch(() => setErr("Tour not found."));
  }, [token]);

  if (err)
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="surface p-8 text-center">
          <div className="uppercase-label mb-2">Not found</div>
          <div className="font-serif-display text-2xl">{err}</div>
        </div>
      </div>
    );
  if (!tour) return <div className="min-h-screen flex items-center justify-center uppercase-label">Loading…</div>;

  return (
    <div className="min-h-screen py-14 px-6" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto">
        <header className="mb-10">
          <div className="uppercase-label mb-2">Tour schedule</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl mb-3" data-testid="shared-tour-name">{tour.name}</h1>
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>
            {fmtDate(tour.start_date)} – {fmtDate(tour.end_date)}
            {tour.location && ` · ${tour.location}`}
          </div>
        </header>

        {tour.stops.length === 0 ? (
          <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>
            No dates announced yet — check back soon.
          </div>
        ) : (
          <div className="surface divide-y" style={{ borderColor: "var(--border)" }}>
            {tour.stops.map((s) => (
              <div key={s.id} className="px-6 py-5" style={{ borderTop: "1px solid var(--border)" }} data-testid={`shared-stop-${s.id}`}>
                <div className="font-serif-display text-xl mb-1">{s.city}</div>
                {s.venue && <div className="text-sm mb-1" style={{ color: "var(--text)" }}>{s.venue}</div>}
                <div className="text-sm flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
                  <MapPin size={12} />
                  {fmtDate(s.stop_date)}{s.stop_time ? ` · ${s.stop_time}` : ""}
                </div>
                {s.notes && <div className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>{s.notes}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
