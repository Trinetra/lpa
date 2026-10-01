import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Reply, Trash2 } from "lucide-react";

// Messages sent through the contact form on www.pravaahacfm.com. Each one is
// also emailed to her; this is the copy that survives if that email doesn't.
export default function MessagesPage() {
  const [messages, setMessages] = useState(null);

  const load = () => {
    api.get("/contact-messages").then((r) => setMessages(r.data));
  };

  useEffect(() => {
    load();
    // Opening the page counts as reading them — the "new" marks below are
    // from the list fetched before this runs, so they still show this visit.
    api.post("/contact-messages/mark-read").catch(() => {});
  }, []);

  const remove = async (id) => {
    if (!window.confirm("Delete this message?")) return;
    try {
      await api.delete(`/contact-messages/${id}`);
      toast.success("Deleted");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't delete that message");
    }
  };

  return (
    <div data-testid="messages-page" className="space-y-6">
      <header>
        <div className="uppercase-label mb-2">www.pravaahacfm.com</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Website messages</h1>
      </header>

      {!messages ? (
        <div className="uppercase-label">Loading…</div>
      ) : (
        <div className="surface">
          {messages.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
              No messages yet. Anything sent through the contact form on your website will appear here.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={m.id} className="px-6 py-4 text-sm" data-testid={`message-${m.id}`}
              style={{ borderTop: i === 0 ? "none" : "1px solid var(--border)" }}>
              <div className="flex justify-between items-start gap-4">
                <div className="min-w-0">
                  <div className="font-serif-display text-lg flex items-center gap-2">
                    {m.name}
                    {!m.read && <span className="uppercase-label" style={{ color: "var(--primary)" }}>New</span>}
                  </div>
                  <div className="truncate" style={{ color: "var(--text-muted)" }}>
                    {m.email} · {new Date(m.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <a href={`mailto:${m.email}?subject=${encodeURIComponent("Re: your message")}`} className="btn-ghost p-2"
                    title="Reply by email" data-testid={`reply-message-${m.id}`}>
                    <Reply size={16} />
                  </a>
                  <button type="button" onClick={() => remove(m.id)} className="btn-ghost p-2" style={{ color: "var(--error)" }}
                    title="Delete" data-testid={`delete-message-${m.id}`}>
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
              <div className="mt-3 whitespace-pre-wrap break-words">{m.message}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
