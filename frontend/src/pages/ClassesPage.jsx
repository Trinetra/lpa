import React, { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, Trash2, Pencil, X } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const today = () => new Date().toISOString().slice(0, 10);

function EditClassModal({ item, students, onClose, onSaved }) {
  const [form, setForm] = useState({
    student_id: item.student_id,
    hours: item.hours,
    class_date: item.class_date,
    notes: item.notes || "",
    rate_override: item.rate ?? "",
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
  const [filterId, setFilterId] = useState("");
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({
    student_id: "",
    hours: 1,
    class_date: today(),
    notes: "",
    rate_override: "",
  });
  const [saving, setSaving] = useState(false);

  const load = () => {
    const params = filterId ? { params: { student_id: filterId } } : {};
    Promise.all([api.get("/students"), api.get("/classes", params)]).then(([sRes, cRes]) => {
      setStudents(sRes.data);
      setClasses(cRes.data);
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
        rate_override:
          form.rate_override === "" ? null : Number(form.rate_override),
      });
      toast.success("Class logged");
      setForm({ ...form, hours: 1, notes: "", rate_override: "" });
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
        <div className="uppercase-label mb-4">Log a class</div>
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
        <div className="grid grid-cols-12 px-6 py-3 uppercase-label" style={{ borderBottom: "1px solid var(--border)" }}>
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
            className="grid grid-cols-12 items-center px-6 py-3 text-sm"
            style={{ borderTop: "1px solid var(--border)" }}>
            <div className="col-span-3">
              {c.class_date}
              {c.notes && (
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>{c.notes}</div>
              )}
            </div>
            <div className="col-span-3 truncate">{nameOf(c.student_id)}</div>
            <div className="col-span-1 text-right">{c.hours}</div>
            <div className="col-span-2 text-right">{fmt(c.rate)}</div>
            <div className="col-span-2 text-right font-serif-display" style={{ color: "var(--primary)" }}>
              {fmt(c.amount)}
            </div>
            <div className="col-span-1 flex items-center justify-end gap-1">
              <button
                onClick={() => setEditing(c)}
                data-testid={`edit-class-${c.id}`}
                className="p-1 rounded hover:bg-white/5"
                type="button"
                title="Edit"
              >
                <Pencil size={14} strokeWidth={1.5} />
              </button>
              <button
                onClick={() => remove(c.id)}
                data-testid={`delete-class-${c.id}`}
                className="p-1 rounded hover:bg-white/5"
                style={{ color: "var(--error)" }}
                type="button"
                title="Delete"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <EditClassModal
          item={editing}
          students={students}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
