import React, { useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, Trash2, Pencil, X, Video, ChevronDown } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const today = () => new Date().toISOString().slice(0, 10);

const fmtMeetingWhen = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
};

// Lets her pick a real past Zoom session instead of typing date/hours by
// hand — selecting one pre-fills the log-class form's date and duration.
function ZoomPicker({ onPick }) {
  const [open, setOpen] = useState(false);
  const [meetings, setMeetings] = useState(null); // null = not loaded, [] = loaded empty
  const [configured, setConfigured] = useState(true);
  const wrapRef = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const load = () => {
    if (meetings !== null) return; // cache for the session — no need to refetch every open
    api.get("/zoom/past-meetings").then((r) => setMeetings(r.data)).catch((e) => {
      if (e?.response?.status === 404) setConfigured(false);
      else toast.error("Couldn't load Zoom meetings");
      setMeetings([]);
    });
  };

  const toggle = () => {
    setOpen((o) => !o);
    if (!open) load();
  };

  if (!configured) return null; // Zoom not connected — don't clutter the form with a dead button

  return (
    <div ref={wrapRef} className="relative">
      <button type="button" onClick={toggle} data-testid="zoom-picker-btn"
        className="btn-ghost text-xs flex items-center gap-1.5">
        <Video size={13} /> Pick from Zoom <ChevronDown size={12} />
      </button>
      {open && (
        <div className="absolute z-10 mt-1 w-72 surface p-1 max-h-64 overflow-y-auto" style={{ borderColor: "var(--border)" }}>
          {meetings === null && (
            <div className="p-3 text-xs text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
          )}
          {meetings !== null && meetings.length === 0 && (
            <div className="p-3 text-xs text-center" style={{ color: "var(--text-muted)" }}>No recent Zoom sessions.</div>
          )}
          {meetings?.map((m) => (
            <button key={m.uuid} type="button" data-testid={`zoom-meeting-${m.uuid}`}
              onClick={() => { onPick(m); setOpen(false); }}
              className="w-full text-left px-3 py-2 rounded hover:bg-white/5">
              <div className="text-sm truncate">{m.topic || "Zoom Meeting"}</div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {fmtMeetingWhen(m.start_time)} · {m.duration_minutes} min
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Free-add, studio-wide topic tags: type a new one to create it (added to
// the shared autocomplete list on save), or pick from what's already there.
function TopicPicker({ topics, onChange, allTopics, testidPrefix }) {
  const [input, setInput] = useState("");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const addTopic = (name) => {
    const trimmed = name.trim();
    if (!trimmed || topics.includes(trimmed)) return;
    onChange([...topics, trimmed]);
    setInput("");
    setOpen(false);
  };

  const removeTopic = (name) => onChange(topics.filter((t) => t !== name));

  const suggestions = allTopics.filter(
    (t) => !topics.includes(t) && t.toLowerCase().includes(input.toLowerCase())
  ).slice(0, 6);
  const isNew = input.trim() && !allTopics.some((t) => t.toLowerCase() === input.trim().toLowerCase());

  return (
    <div ref={wrapRef} className="relative">
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {topics.map((t) => (
          <span key={t} data-testid={`${testidPrefix}-chip-${t}`}
            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full"
            style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)", border: "1px solid rgba(212,132,100,0.4)" }}>
            {t}
            <button type="button" onClick={() => removeTopic(t)} data-testid={`${testidPrefix}-remove-${t}`}>
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <input
        value={input}
        onChange={(e) => { setInput(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); addTopic(input); }
        }}
        placeholder="Add a topic taught (e.g. Alarippu)…"
        data-testid={`${testidPrefix}-input`}
        className="w-full bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
      />
      {open && (suggestions.length > 0 || isNew) && (
        <div className="absolute z-10 mt-1 w-full surface p-1 max-h-48 overflow-y-auto" style={{ borderColor: "var(--border)" }}>
          {suggestions.map((t) => (
            <button key={t} type="button" onClick={() => addTopic(t)}
              data-testid={`${testidPrefix}-suggestion-${t}`}
              className="w-full text-left text-sm px-3 py-1.5 rounded hover:bg-white/5">
              {t}
            </button>
          ))}
          {isNew && (
            <button type="button" onClick={() => addTopic(input)}
              data-testid={`${testidPrefix}-create-new`}
              className="w-full text-left text-sm px-3 py-1.5 rounded hover:bg-white/5"
              style={{ color: "var(--primary)" }}>
              + Add "{input.trim()}" as new topic
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function EditClassModal({ item, students, allTopics, onClose, onSaved }) {
  const [form, setForm] = useState({
    student_id: item.student_id,
    hours: item.hours,
    class_date: item.class_date,
    notes: item.notes || "",
    rate_override: item.rate ?? "",
    topics: item.topics || [],
  });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch(`/classes/${item.id}`, {
        student_id: form.student_id,
        hours: Number(form.hours),
        class_date: form.class_date,
        notes: form.notes || null,
        rate_override: form.rate_override === "" ? null : Number(form.rate_override),
        topics: form.topics,
      });
      toast.success("Class updated");
      onSaved();
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Update failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="edit-class-form" className="surface w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">Edit class</h3>
          <button type="button" onClick={onClose} data-testid="edit-class-close" className="p-1"><X size={18} /></button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Student</span>
            <select required value={form.student_id} onChange={(e) => setForm({ ...form, student_id: e.target.value })}
              data-testid="edit-class-student"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}>
              {students.map((s) => (
                <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>{s.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="uppercase-label block mb-1">Hours</span>
            <input required type="number" step="0.25" min="0" value={form.hours}
              onChange={(e) => setForm({ ...form, hours: e.target.value })}
              data-testid="edit-class-hours"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Date</span>
            <input required type="date" value={form.class_date}
              onChange={(e) => setForm({ ...form, class_date: e.target.value })}
              data-testid="edit-class-date"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Rate override</span>
            <input type="number" min="0" value={form.rate_override}
              onChange={(e) => setForm({ ...form, rate_override: e.target.value })}
              data-testid="edit-class-rate"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Topics taught</span>
            <TopicPicker topics={form.topics} onChange={(topics) => setForm({ ...form, topics })}
              allTopics={allTopics} testidPrefix="edit-class-topic" />
          </label>
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Notes</span>
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
              data-testid="edit-class-notes"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <button type="button" onClick={onClose} className="btn-ghost" data-testid="edit-class-cancel">Cancel</button>
          <button type="submit" disabled={saving} className="btn-pill" data-testid="edit-class-save">
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function ClassesPage() {
  const [students, setStudents] = useState([]);
  const [classes, setClasses] = useState([]);
  const [allTopics, setAllTopics] = useState([]);
  const [filterId, setFilterId] = useState("");
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({
    student_id: "",
    hours: 1,
    class_date: today(),
    notes: "",
    rate_override: "",
    topics: [],
  });
  const [saving, setSaving] = useState(false);

  const load = () => {
    const params = filterId ? { params: { student_id: filterId } } : {};
    Promise.all([api.get("/students"), api.get("/classes", params), api.get("/class-topics")]).then(([sRes, cRes, tRes]) => {
      setStudents(sRes.data);
      setClasses(cRes.data);
      setAllTopics(tRes.data);
    });
  };

  useEffect(load, [filterId]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.student_id) {
      toast.error("Please select a student");
      return;
    }
    setSaving(true);
    try {
      await api.post("/classes", {
        student_id: form.student_id,
        hours: Number(form.hours),
        class_date: form.class_date,
        notes: form.notes || null,
        topics: form.topics,
        rate_override:
          form.rate_override === "" ? null : Number(form.rate_override),
      });
      toast.success("Class logged");
      setForm({ ...form, hours: 1, notes: "", rate_override: "", topics: [] });
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this class entry?")) return;
    await api.delete(`/classes/${id}`);
    toast.success("Deleted");
    load();
  };

  const nameOf = (id) => students.find((s) => s.id === id)?.name || "—";

  return (
    <div data-testid="classes-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Class ledger</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Log & review classes</h1>
      </header>

      {/* Log form */}
      <form onSubmit={submit} data-testid="log-class-form" className="surface p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="uppercase-label">Log a class</div>
          <ZoomPicker onPick={(m) => {
            const start = new Date(m.start_time);
            const hours = Math.max(0.25, Math.round((m.duration_minutes / 60) * 4) / 4);
            setForm({
              ...form,
              class_date: start.toISOString().slice(0, 10),
              hours,
            });
            toast.success(`Filled in from "${m.topic || "Zoom Meeting"}" — pick the student and save`);
          }} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <label className="md:col-span-2">
            <span className="uppercase-label block mb-1">Student</span>
            <select required value={form.student_id}
              onChange={(e) => setForm({ ...form, student_id: e.target.value })}
              data-testid="log-student-select"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
              style={{ background: "var(--surface)" }}>
              <option value="" style={{ background: "var(--surface)" }}>Select student…</option>
              {students.map((s) => (
                <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>
                  {s.name} — ₹{s.hourly_rate}/hr
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="uppercase-label block mb-1">Hours</span>
            <input required type="number" step="0.25" min="0" value={form.hours}
              onChange={(e) => setForm({ ...form, hours: e.target.value })}
              data-testid="log-hours-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Date</span>
            <input required type="date" value={form.class_date}
              onChange={(e) => setForm({ ...form, class_date: e.target.value })}
              data-testid="log-date-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Rate override</span>
            <input type="number" min="0" placeholder="optional" value={form.rate_override}
              onChange={(e) => setForm({ ...form, rate_override: e.target.value })}
              data-testid="log-rate-override-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="md:col-span-5">
            <span className="uppercase-label block mb-1">Topics taught</span>
            <TopicPicker topics={form.topics} onChange={(topics) => setForm({ ...form, topics })}
              allTopics={allTopics} testidPrefix="log-topic" />
          </label>
          <label className="md:col-span-4">
            <span className="uppercase-label block mb-1">Notes</span>
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
              data-testid="log-notes-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <div className="md:col-span-1 flex items-end">
            <button type="submit" disabled={saving} data-testid="log-submit-btn"
              className="btn-pill w-full flex items-center justify-center gap-2">
              <Plus size={14} /> {saving ? "Saving…" : "Log class"}
            </button>
          </div>
        </div>
      </form>

      {/* Filter */}
      <div className="flex items-center gap-3">
        <span className="uppercase-label">Filter</span>
        <select value={filterId} onChange={(e) => setFilterId(e.target.value)}
          data-testid="classes-filter-select"
          className="bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
          style={{ background: "var(--surface)" }}>
          <option value="" style={{ background: "var(--surface)" }}>All students</option>
          {students.map((s) => (
            <option key={s.id} value={s.id} style={{ background: "var(--surface)" }}>{s.name}</option>
          ))}
        </select>
      </div>

      {/* List */}
      <div className="surface overflow-hidden">
        <div className="hidden sm:grid sm:grid-cols-12 px-6 py-3 uppercase-label" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="col-span-3">Date</div>
          <div className="col-span-3">Student</div>
          <div className="col-span-1 text-right">Hours</div>
          <div className="col-span-2 text-right">Rate</div>
          <div className="col-span-2 text-right">Amount</div>
          <div className="col-span-1 text-right">•</div>
        </div>
        {classes.length === 0 && (
          <div className="p-8 text-center" style={{ color: "var(--text-muted)" }}>
            No classes yet.
          </div>
        )}
        {classes.map((c) => (
          <div key={c.id} data-testid={`class-row-${c.id}`}
            className="px-4 sm:px-6 py-3 text-sm"
            style={{ borderTop: "1px solid var(--border)" }}>
            {/* Mobile: two-line card. Desktop: 12-col grid */}
            <div className="flex flex-col sm:grid sm:grid-cols-12 sm:items-center gap-2 sm:gap-0">
              <div className="sm:col-span-3 flex justify-between sm:block">
                <span>{c.class_date}</span>
                <span className="sm:hidden font-serif-display" style={{ color: "var(--primary)" }}>{fmt(c.amount)}</span>
              </div>
              <div className="sm:col-span-3 truncate" style={{ color: "var(--text-muted)" }}>{nameOf(c.student_id)}</div>
              <div className="sm:col-span-1 sm:text-right flex sm:block items-center justify-between">
                <span className="sm:hidden uppercase-label">Hours</span>
                <span>{c.hours}</span>
              </div>
              <div className="sm:col-span-2 sm:text-right flex sm:block items-center justify-between">
                <span className="sm:hidden uppercase-label">Rate</span>
                <span>{fmt(c.rate)}</span>
              </div>
              <div className="hidden sm:block sm:col-span-2 sm:text-right font-serif-display" style={{ color: "var(--primary)" }}>
                {fmt(c.amount)}
              </div>
              <div className="sm:col-span-1 flex items-center justify-end gap-3 pt-2 sm:pt-0 mt-1 sm:mt-0" style={{ borderTop: "1px dashed var(--border)" }}>
                <button
                  onClick={() => setEditing(c)}
                  data-testid={`edit-class-${c.id}`}
                  className="px-3 py-1.5 sm:p-1 rounded hover:bg-white/5 inline-flex items-center gap-1 text-xs"
                  type="button"
                  title="Edit"
                >
                  <Pencil size={14} strokeWidth={1.5} /> <span className="sm:hidden">Edit</span>
                </button>
                <button
                  onClick={() => remove(c.id)}
                  data-testid={`delete-class-${c.id}`}
                  className="px-3 py-1.5 sm:p-1 rounded hover:bg-white/5 inline-flex items-center gap-1 text-xs"
                  style={{ color: "var(--error)" }}
                  type="button"
                  title="Delete"
                >
                  <Trash2 size={14} /> <span className="sm:hidden">Delete</span>
                </button>
              </div>
            </div>
            {c.topics && c.topics.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {c.topics.map((t) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full"
                    style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)" }}>
                    {t}
                  </span>
                ))}
              </div>
            )}
            {c.notes && (
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{c.notes}</div>
            )}
          </div>
        ))}
      </div>

      {editing && (
        <EditClassModal
          item={editing}
          students={students}
          allTopics={allTopics}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
