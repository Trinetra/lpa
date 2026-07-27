import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/lib/api";
import { MapPin, MessageCircle, Mail, Link2 } from "lucide-react";
import { toast } from "sonner";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

export default function SharedTourPage({ bySlug = false }) {
  const { token, slug } = useParams();
  const [tour, setTour] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    const url = bySlug ? `${API}/tours/slug/${slug}` : `${API}/tours/share/${token}`;
    axios
      .get(url)
      .then((r) => setTour(r.data))
      .catch(() => setErr(bySlug ? "Page not found." : "Tour not found."));
  }, [bySlug, token, slug]);

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

  const studio = tour.studio || {};
  const brandName = studio.studio_name || studio.teacher_name;
  const pageUrl = window.location.href;
  const shareMessage = `${tour.name} — tour schedule${brandName ? ` from ${brandName}` : ""}: ${pageUrl}`;
  const waShareLink = `https://wa.me/?text=${encodeURIComponent(shareMessage)}`;
  const mailShareLink = `mailto:?subject=${encodeURIComponent(`${tour.name} — Tour Schedule`)}&body=${encodeURIComponent(shareMessage)}`;
  const copyLink = () => {
    navigator.clipboard.writeText(pageUrl);
    toast.success("Link copied");
  };

  return (
    <div className="min-h-screen py-14 px-6" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto">
        <header className="mb-10">
          <div className="uppercase-label mb-2">Tour schedule</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl mb-3" data-testid="shared-tour-name">{tour.name}</h1>
          <div className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
            {fmtDate(tour.start_date)} – {fmtDate(tour.end_date)}
            {tour.location && ` · ${tour.location}`}
          </div>
          <div className="flex flex-wrap gap-2">
            <a href={waShareLink} target="_blank" rel="noreferrer" data-testid="share-whatsapp-btn"
              className="btn-pill flex items-center gap-2 text-sm"
              style={{ background: "#25D366", color: "#0b1f13" }}>
              <MessageCircle size={14} /> Share on WhatsApp
            </a>
            <a href={mailShareLink} data-testid="share-email-btn"
              className="btn-ghost flex items-center gap-2 text-sm">
              <Mail size={14} /> Share by email
            </a>
            <button type="button" onClick={copyLink} data-testid="share-copy-btn"
              className="btn-ghost flex items-center gap-2 text-sm">
              <Link2 size={14} /> Copy link
            </button>
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
                {s.latitude != null && s.longitude != null && (
                  <a href={`https://www.google.com/maps?q=${s.latitude},${s.longitude}`} target="_blank" rel="noreferrer"
                    data-testid={`shared-stop-map-${s.id}`}
                    className="text-sm mt-1 flex items-center gap-1 hover:text-[color:var(--primary)] transition-colors underline"
                    style={{ color: "var(--text-muted)" }}>
                    {s.formatted_address || "View on map"}
                  </a>
                )}
                {s.notes && <div className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>{s.notes}</div>}
              </div>
            ))}
          </div>
        )}

        {(brandName || studio.social_youtube || studio.social_instagram || studio.social_facebook) && (
          <div className="text-center pt-10 mt-10" style={{ borderTop: "1px solid var(--border)" }}>
            {brandName && <div className="font-serif-display text-lg mb-2">{brandName}</div>}
            {(studio.social_youtube || studio.social_instagram || studio.social_facebook) && (
              <div className="text-xs space-x-3" data-testid="shared-tour-socials">
                {studio.social_youtube && <a href={studio.social_youtube} target="_blank" rel="noreferrer" className="underline" style={{ color: "var(--text-muted)" }}>YouTube</a>}
                {studio.social_instagram && <a href={studio.social_instagram} target="_blank" rel="noreferrer" className="underline" style={{ color: "var(--text-muted)" }}>Instagram</a>}
                {studio.social_facebook && <a href={studio.social_facebook} target="_blank" rel="noreferrer" className="underline" style={{ color: "var(--text-muted)" }}>Facebook</a>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
