import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Search, Send, X, Loader2 } from "lucide-react";
import { toast } from "sonner";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");

function InviteModal({ selectedIds, onClose, onSent }) {
  const [events, setEvents] = useState(null);
  const [eventId, setEventId] = useState("");
  const [sending, setSending] = useState(false);
  const [alreadyInvited, setAlreadyInvited] = useState(null);
  const [force, setForce] = useState(false);

  useEffect(() => {
    api.get("/events").then((r) => setEvents(r.data.filter((e) => e.status === "published"))).catch(() => setEvents([]));
  }, []);

  useEffect(() => {
    setForce(false);
    if (!eventId) { setAlreadyInvited(null); return; }
    api.get("/crm/contacts/already-invited", { params: { event_id: eventId } })
      .then((r) => setAlreadyInvited(new Set(r.data.contact_ids)))
      .catch(() => setAlreadyInvited(new Set()));
  }, [eventId]);

  const overlapCount = alreadyInvited ? selectedIds.filter((id) => alreadyInvited.has(id)).length : 0;

  const send = async () => {
    if (!eventId) return toast.error("Pick an event first");
    setSending(true);
    try {
      const { data } = await api.post("/crm/contacts/bulk-invite", { contact_ids: selectedIds, event_id: eventId, force });
      const parts = [`Invited ${data.sent.length}`];
      if (data.skipped?.length) parts.push(`${data.skipped.length} skipped (already invited)`);
      if (data.failed?.length) parts.push(`${data.failed.length} failed`);
      toast.success(parts.join(", "));
      onSent();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Failed to send invites");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div data-testid="crm-invite-modal" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">Invite {selectedIds.length} contact{selectedIds.length === 1 ? "" : "s"}</h3>
          <button type="button" onClick={onClose} data-testid="crm-invite-close" className="p-1"><X size={18} /></button>
        </div>
        {events === null ? (
          <div className="uppercase-label">Loading events…</div>
        ) : events.length === 0 ? (
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>
            No published events yet — publish one first from the Events tab.
          </div>
        ) : (
          <>
            <label className="block mb-4">
              <span className="uppercase-label block mb-1">Event</span>
              <select value={eventId} onChange={(e) => setEventId(e.target.value)}
                data-testid="crm-invite-event-select"
                className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
                style={{ background: "var(--surface)" }}>
                <option value="" style={{ background: "var(--surface)" }}>Select an event…</option>
                {events.map((ev) => (
                  <option key={ev.id} value={ev.id} style={{ background: "var(--surface)" }}>
                    {ev.name} — {fmtDate(ev.start_date)}
                  </option>
                ))}
              </select>
            </label>

            {overlapCount > 0 && (
              <div className="text-xs mb-4 p-3 rounded" data-testid="crm-invite-overlap-warning"
                style={{ background: "rgba(214,120,90,0.12)", color: "var(--warning)" }}>
                {overlapCount} of {selectedIds.length} selected already got an invite for this event.
                <label className="flex items-center gap-2 mt-2">
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} data-testid="crm-invite-force-checkbox" />
                  Resend to them anyway
                </label>
              </div>
            )}

            <div className="flex justify-end gap-3">
              <button type="button" onClick={onClose} className="btn-ghost" data-testid="crm-invite-cancel">Cancel</button>
              <button type="button" onClick={send} disabled={sending} className="btn-pill flex items-center gap-2" data-testid="crm-invite-send">
                {sending && <Loader2 size={14} className="animate-spin" />} <Send size={14} /> Send invites
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function CrmPage() {
  const [contacts, setContacts] = useState(null);
  const [pastEvents, setPastEvents] = useState([]);
  const [allCountries, setAllCountries] = useState([]);
  const [q, setQ] = useState("");
  const [country, setCountry] = useState("");
  const [minAge, setMinAge] = useState("");
  const [maxAge, setMaxAge] = useState("");
  const [eventFilter, setEventFilter] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [showInvite, setShowInvite] = useState(false);
  const [campaignsRefresh, setCampaignsRefresh] = useState(0);

  useEffect(() => {
    api.get("/events").then((r) => setPastEvents(r.data)).catch(() => setPastEvents([]));
    // Unfiltered, fetched once — used only to populate the country dropdown
    // so it doesn't shrink to whatever's currently filtered in the table.
    api.get("/crm/contacts").then((r) => {
      setAllCountries([...new Set(r.data.map((c) => c.country).filter(Boolean))].sort());
    }).catch(() => {});
  }, []);

  const load = () => {
    const params = {};
    if (q.trim()) params.q = q.trim();
    if (country.trim()) params.country = country.trim();
    if (minAge !== "") params.min_age = Number(minAge);
    if (maxAge !== "") params.max_age = Number(maxAge);
    if (eventFilter) params.event_id = eventFilter;
    api.get("/crm/contacts", { params }).then((r) => setContacts(r.data)).catch(() => setContacts([]));
  };

  useEffect(() => { load(); }, [q, country, minAge, maxAge, eventFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (!contacts) return;
    setSelected((s) => (s.size === contacts.length ? new Set() : new Set(contacts.map((c) => c.id))));
  };

  if (contacts === null) return <div data-testid="crm-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="crm-page" className="space-y-6">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Everyone who's registered</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Contacts</h1>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          disabled={selected.size === 0}
          data-testid="crm-invite-btn"
          className="btn-pill flex items-center gap-2 disabled:opacity-40"
        >
          <Send size={16} /> Invite selected ({selected.size})
        </button>
      </header>

      <div className="surface p-4 flex flex-wrap gap-3 items-end">
        <label className="flex-1 min-w-[180px]">
          <span className="uppercase-label block mb-1">Search</span>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--text-muted)" }} />
            <input value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Name, email, experience…"
              data-testid="crm-search-input"
              className="w-full bg-transparent border border-white/10 rounded pl-9 pr-3 py-2" />
          </div>
        </label>
        <label>
          <span className="uppercase-label block mb-1">Country</span>
          <select value={country} onChange={(e) => setCountry(e.target.value)}
            data-testid="crm-country-select"
            className="bg-transparent border border-white/10 rounded px-3 py-2"
            style={{ background: "var(--surface)" }}>
            <option value="" style={{ background: "var(--surface)" }}>All</option>
            {allCountries.map((c) => (
              <option key={c} value={c} style={{ background: "var(--surface)" }}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="uppercase-label block mb-1">Min age</span>
          <input type="number" min="0" value={minAge} onChange={(e) => setMinAge(e.target.value)}
            data-testid="crm-min-age-input"
            className="w-20 bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Max age</span>
          <input type="number" min="0" value={maxAge} onChange={(e) => setMaxAge(e.target.value)}
            data-testid="crm-max-age-input"
            className="w-20 bg-transparent border border-white/10 rounded px-3 py-2" />
        </label>
        <label>
          <span className="uppercase-label block mb-1">Past event</span>
          <select value={eventFilter} onChange={(e) => setEventFilter(e.target.value)}
            data-testid="crm-event-filter-select"
            className="bg-transparent border border-white/10 rounded px-3 py-2"
            style={{ background: "var(--surface)" }}>
            <option value="" style={{ background: "var(--surface)" }}>Any</option>
            {pastEvents.map((ev) => (
              <option key={ev.id} value={ev.id} style={{ background: "var(--surface)" }}>{ev.name}</option>
            ))}
          </select>
        </label>
      </div>

      {contacts.length === 0 ? (
        <div className="surface p-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
          No contacts match these filters.
        </div>
      ) : (
        <div className="surface overflow-hidden">
          <div className="hidden sm:grid sm:grid-cols-12 px-6 py-3 uppercase-label items-center" style={{ borderBottom: "1px solid var(--border)" }}>
            <div className="col-span-1">
              <input type="checkbox" checked={selected.size === contacts.length} onChange={toggleAll} data-testid="crm-select-all" />
            </div>
            <div className="col-span-3">Name</div>
            <div className="col-span-3">Contact</div>
            <div className="col-span-1 text-right">Age</div>
            <div className="col-span-1">Country</div>
            <div className="col-span-2">Past events</div>
            <div className="col-span-1">Last invite</div>
          </div>
          {contacts.map((c) => (
            <div key={c.id} data-testid={`crm-contact-row-${c.id}`}
              className="px-4 sm:px-6 py-3 text-sm flex flex-col sm:grid sm:grid-cols-12 sm:items-center gap-2 sm:gap-0"
              style={{ borderTop: "1px solid var(--border)" }}>
              <div className="sm:col-span-1">
                <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} data-testid={`crm-select-${c.id}`} />
              </div>
              <div className="sm:col-span-3">
                <div className="font-serif-display text-base">{c.name}</div>
                {c.latest_experience && (
                  <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{c.latest_experience}</div>
                )}
              </div>
              <div className="sm:col-span-3 text-xs" style={{ color: "var(--text-muted)" }}>
                <div>{c.email}</div>
                <div>{c.mobile}</div>
              </div>
              <div className="sm:col-span-1 sm:text-right">{c.age ?? "—"}</div>
              <div className="sm:col-span-1">{c.country || "—"}</div>
              <div className="sm:col-span-2 flex flex-wrap gap-1">
                {c.events_participated.length === 0 ? (
                  <span style={{ color: "var(--text-muted)" }}>—</span>
                ) : (
                  c.events_participated.map((ep, i) => (
                    <span key={i} className="text-[10px] px-2 py-0.5 rounded-full"
                      style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)" }}>
                      {ep.event_name || "Event"}
                    </span>
                  ))
                )}
              </div>
              <div className="sm:col-span-1">
                <InviteStatus invite={c.latest_invite} />
              </div>
            </div>
          ))}
        </div>
      )}

      <CampaignsPanel refreshKey={campaignsRefresh} />

      {showInvite && (
        <InviteModal
          selectedIds={[...selected]}
          onClose={() => setShowInvite(false)}
          onSent={() => { setShowInvite(false); setSelected(new Set()); load(); setCampaignsRefresh((n) => n + 1); }}
        />
      )}
    </div>
  );
}

function InviteStatus({ invite }) {
  if (!invite) return <span className="text-xs" style={{ color: "var(--text-muted)" }}>—</span>;
  const label = invite.clicked_at ? "Clicked" : invite.opened_at ? "Opened" : "Sent";
  const color = invite.clicked_at ? "var(--success)" : invite.opened_at ? "var(--primary)" : "var(--text-muted)";
  return (
    <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full"
      style={{ color, border: `1px solid ${color}` }}>
      {label}
    </span>
  );
}

function CampaignsPanel({ refreshKey }) {
  const [campaigns, setCampaigns] = useState(null);

  useEffect(() => {
    api.get("/crm/campaigns").then((r) => setCampaigns(r.data)).catch(() => setCampaigns([]));
  }, [refreshKey]);

  if (campaigns === null || campaigns.length === 0) return null;

  return (
    <section>
      <div className="uppercase-label mb-3">Past invite campaigns</div>
      <div className="surface overflow-hidden">
        <div className="hidden sm:grid sm:grid-cols-12 px-6 py-3 uppercase-label" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="col-span-4">Event</div>
          <div className="col-span-2">Sent on</div>
          <div className="col-span-2 text-right">Sent</div>
          <div className="col-span-2 text-right">Opened</div>
          <div className="col-span-2 text-right">Clicked</div>
        </div>
        {campaigns.map((c) => (
          <div key={c.campaign_id} data-testid={`crm-campaign-row-${c.campaign_id}`}
            className="px-4 sm:px-6 py-3 text-sm flex flex-col sm:grid sm:grid-cols-12 sm:items-center gap-1 sm:gap-0"
            style={{ borderTop: "1px solid var(--border)" }}>
            <div className="sm:col-span-4 font-serif-display">{c.event_name || "Event"}</div>
            <div className="sm:col-span-2 text-xs" style={{ color: "var(--text-muted)" }}>{fmtDate(c.sent_at?.slice(0, 10))}</div>
            <div className="sm:col-span-2 sm:text-right">{c.sent}</div>
            <div className="sm:col-span-2 sm:text-right">{c.opened} <span className="text-xs" style={{ color: "var(--text-muted)" }}>({c.sent ? Math.round((c.opened / c.sent) * 100) : 0}%)</span></div>
            <div className="sm:col-span-2 sm:text-right">{c.clicked} <span className="text-xs" style={{ color: "var(--text-muted)" }}>({c.sent ? Math.round((c.clicked / c.sent) * 100) : 0}%)</span></div>
          </div>
        ))}
      </div>
    </section>
  );
}
