import React, { useEffect, useState } from "react";
import { studentApi, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Trash2, Pencil, X } from "lucide-react";

export default function StudentNotesPage() {
  const [notes, setNotes] = useState(null);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editingText, setEditingText] = useState("");

  const load = () => {
    studentApi.get("/student/notes").then((r) => setNotes(r.data));
  };

  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setSaving(true);
    try {
      await studentApi.post("/student/notes", { text });
      setText("");
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't save that note");
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (n) => {
    setEditingId(n.id);
    setEditingText(n.text);
  };

  const saveEdit = async (id) => {
    try {
      await studentApi.patch(`/student/notes/${id}`, { text: editingText });
      setEditingId(null);
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't save that note");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this note?")) return;
    await studentApi.delete(`/student/notes/${id}`);
    load();
  };

  if (!notes) return <div data-testid="portal-notes-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="portal-notes-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Private to you</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Notes</h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
          Your teacher can't see these — use this space however helps you practice.
        </p>
      </header>

      <form onSubmit={add} className="surface p-4 flex gap-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Jot something down…"
          rows={2}
          data-testid="portal-notes-input"
          className="flex-1 bg-transparent border border-white/10 rounded px-3 py-2"
        />
        <button type="submit" disabled={saving} className="btn-pill self-end" data-testid="portal-notes-add-btn">
          Add
        </button>
      </form>

      <div className="surface">
        {notes.length === 0 && (
          <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>No notes yet.</div>
        )}
        {notes.map((n) => (
          <div key={n.id} className="px-6 py-4 text-sm flex items-start justify-between gap-3"
            style={{ borderTop: "1px solid var(--border)" }} data-testid={`portal-note-${n.id}`}>
            {editingId === n.id ? (
              <>
                <textarea value={editingText} onChange={(e) => setEditingText(e.target.value)} rows={2}
                  className="flex-1 bg-transparent border border-white/10 rounded px-3 py-2" />
                <div className="flex flex-col gap-1">
                  <button type="button" onClick={() => saveEdit(n.id)} className="btn-ghost p-2" data-testid={`portal-note-save-${n.id}`}>Save</button>
                  <button type="button" onClick={() => setEditingId(null)} className="btn-ghost p-2"><X size={14} /></button>
                </div>
              </>
            ) : (
              <>
                <div className="whitespace-pre-wrap">{n.text}</div>
                <div className="flex gap-2 shrink-0">
                  <button type="button" onClick={() => startEdit(n)} className="btn-ghost p-2" data-testid={`portal-note-edit-${n.id}`}>
                    <Pencil size={14} />
                  </button>
                  <button type="button" onClick={() => remove(n.id)} className="btn-ghost p-2" style={{ color: "var(--error)" }}
                    data-testid={`portal-note-delete-${n.id}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
