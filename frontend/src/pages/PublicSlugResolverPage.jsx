import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/lib/api";
import SharedTourPage from "@/pages/SharedTourPage";
import SharedEventPage from "@/pages/SharedEventPage";

// A custom public link (e.g. pravaahacfm.com/tour2026 or /workshop2026) can
// resolve to either a tour or an event — both share one slug namespace
// (RESERVED_SLUGS, uniqueness) but there's no way to tell which from the URL
// alone, so this tries tour first, then falls back to event, before giving
// up as "not found".
export default function PublicSlugResolverPage() {
  const { slug } = useParams();
  const [kind, setKind] = useState(null); // "tour" | "event" | "notfound" | null (checking)

  useEffect(() => {
    let cancelled = false;
    setKind(null);
    axios.get(`${API}/tours/slug/${slug}`)
      .then(() => { if (!cancelled) setKind("tour"); })
      .catch(() => {
        axios.get(`${API}/events/slug/${slug}`)
          .then(() => { if (!cancelled) setKind("event"); })
          .catch(() => { if (!cancelled) setKind("notfound"); });
      });
    return () => { cancelled = true; };
  }, [slug]);

  if (kind === null) return <div className="min-h-screen flex items-center justify-center uppercase-label">Loading…</div>;
  if (kind === "tour") return <SharedTourPage bySlug />;
  if (kind === "event") return <SharedEventPage bySlug />;
  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="surface p-8 text-center">
        <div className="uppercase-label mb-2">Not found</div>
        <div className="font-serif-display text-2xl">Page not found.</div>
      </div>
    </div>
  );
}
