import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import { Plus, Trash2, Pencil, Upload, X } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;

function StudentForm({ initial, onClose, onSaved }) {
  const [name, setName] = useState(initial?.name || "");
  const [email, setEmail] = useState(initial?.email || "");
  const [phone, setPhone] = useState(initial?.phone || "");
  const [level, setLevel] = useState(initial?.level || "");
  const [joinedOn, setJoinedOn] = useState(initial?.joined_on || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [rate, setRate] = useState(initial?.hourly_rate ?? 0);
  const [photoPath, setPhotoPath] = useState(initial?.photo_path || null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/uploads/photo", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPhotoPath(data.path);
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        name,
        email: email || null,
        phone: phone || null,
        level: level || null,
        joined_on: joinedOn || null,
        description: description || null,
        hourly_rate: Number(rate) || 0,
        photo_path: photoPath || null,
      };
      if (initial?.id) {
        await api.patch(`/students/${initial.id}`, body);
        toast.success("Student updated");
      } else {
        await api.post("/students", body);
        toast.success("Student added");
      }
      onSaved();
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form
        onSubmit={submit}
        data-testid="student-form"
        className="surface w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">
            {initial?.id ? "Edit student" : "New student"}
          </h3>
          <button type="button" onClick={onClose} data-testid="student-form-close" className="p-1">
            <X size={18} />
          </button>
        </div>

        <div className="flex items-center gap-4 mb-6">
          <div className="w-20 h-20 rounded-full overflow-hidden shrink-0" style={{ background: "var(--surface-2)" }}>
            <AuthImage
              path={photoPath}
              className="w-full h-full object-cover"
              fallback={
                <div className="w-full h-full flex items-center justify-center font-serif-display text-2xl" style={{ color: "var(--primary)" }}>
                  {(name || "?").charAt(0)}
                </div>
              }
            />
          </div>
          <div>
            <input ref={fileRef} data-testid="photo-input" type="file" accept="image/*" onChange={handleUpload} className="hidden" />
            <button type="button" data-testid="upload-photo-btn" onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="btn-ghost flex items-center gap-2 text-xs">
              <Upload size={14} /> {uploading ? "Uploading..." : photoPath ? "Change photo" : "Upload photo"}
            </button>
            {photoPath && (
              <button type="button" onClick={() => setPhotoPath(null)}
                className="ml-2 text-xs" style={{ color: "var(--error)" }} data-testid="remove-photo-btn">
                Remove
              </button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Name *</span>
            <input required value={name} onChange={(e) => setName(e.target.value)} data-testid="student-name-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="student-email-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Phone</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="student-phone-input"
              placeholder="10-digit number, +91 added automatically"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Level</span>
            <input value={level} onChange={(e) => setLevel(e.target.value)} placeholder="e.g. Intermediate"
              data-testid="student-level-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
          <label>
            <span className="uppercase-label block mb-1">Joined on</span>
            <input type="date" value={joinedOn} onChange={(e) => setJoinedOn(e.target.value)}
              data-testid="student-joined-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Hourly rate (₹) *</span>
            <input required type="number" min="0" step="1" value={rate} onChange={(e) => setRate(e.target.value)}
              data-testid="student-rate-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
          <label className="sm:col-span-2">
            <span className="uppercase-label block mb-1">Description / notes</span>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
              data-testid="student-description-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2 focus:outline-none focus:border-[color:var(--primary)]" />
          </label>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button type="button" onClick={onClose} className="btn-ghost" data-testid="student-cancel-btn">Cancel</button>
          <button type="submit" disabled={saving} className="btn-pill" data-testid="student-save-btn">
            {saving ? "Saving..." : "Save student"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function StudentsPage() {
  const [students, setStudents] = useState([]);
  const [dueMap, setDueMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null / student object / "new"
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = () => {
    setLoading(true);
    Promise.all([api.get("/students"), api.get("/dashboard")]).then(([sRes, dRes]) => {
      setStudents(sRes.data);
      const map = {};
      dRes.data.students.forEach((s) => (map[s.student_id] = s));
      setDueMap(map);
    }).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const remove = async () => {
    if (!confirmDelete) return;
    try {
      await api.delete(`/students/${confirmDelete.id}`);
      toast.success("Student removed");
      setConfirmDelete(null);
      load();
    } catch (e) {
      toast.error("Delete failed");
    }
  };

  return (
    <div data-testid="students-page" className="space-y-8">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Roster</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Students</h1>
        </div>
        <button data-testid="add-student-btn" onClick={() => setEditing("new")} className="btn-pill flex items-center gap-2">
          <Plus size={16} /> Add student
        </button>
      </header>

      {loading ? (
        <div className="uppercase-label">Loading…</div>
      ) : students.length === 0 ? (
        <div className="surface p-12 text-center">
          <div className="uppercase-label mb-3">Empty roster</div>
          <p className="font-serif-display text-2xl mb-6">No students yet.</p>
          <button data-testid="empty-add-student-btn" onClick={() => setEditing("new")} className="btn-pill">
            Add your first student
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {students.map((s) => {
            const due = dueMap[s.id] || {};
            return (
              <div key={s.id} data-testid={`student-card-${s.id}`} className="surface p-6 surface-hover">
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 rounded-full overflow-hidden shrink-0" style={{ background: "var(--surface-2)" }}>
                    <AuthImage
                      path={s.photo_path}
                      className="w-full h-full object-cover"
                      fallback={
                        <div className="w-full h-full flex items-center justify-center font-serif-display text-xl" style={{ color: "var(--primary)" }}>
                          {(s.name || "?").charAt(0)}
                        </div>
                      }
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Link
                        to={`/students/${s.id}`}
                        data-testid={`student-name-${s.id}`}
                        className="font-serif-display text-lg truncate hover:text-[color:var(--primary)] transition-colors"
                      >
                        {s.name}
                      </Link>
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                      {s.level || "No level"}
                    </div>
                    <div className="mt-2 text-xs space-y-0.5" style={{ color: "var(--text-muted)" }}>
                      {s.phone && <div>{s.phone}</div>}
                      {s.email && <div className="truncate">{s.email}</div>}
                    </div>
                  </div>
                </div>
                <div className="divider-dashed my-4" />
                <div className="flex items-center justify-between">
                  <div>
                    <div className="uppercase-label">Rate</div>
                    <div className="font-serif-display text-lg">{fmt(s.hourly_rate)}/hr</div>
                  </div>
                  <div className="text-right">
                    <div className="uppercase-label">Due</div>
                    <div
                      className="font-serif-display text-lg"
                      style={{ color: due.balance_due > 0 ? "var(--error)" : "var(--success)" }}
                    >
                      {fmt(due.balance_due || 0)}
                    </div>
                  </div>
                </div>
                <div className="flex justify-end gap-2 mt-4">
                  <button
                    data-testid={`edit-student-${s.id}`}
                    onClick={() => setEditing(s)}
                    className="p-2 rounded hover:bg-white/5 transition-colors"
                    title="Edit"
                    type="button"
                  >
                    <Pencil size={15} strokeWidth={1.5} />
                  </button>
                  <button
                    data-testid={`delete-student-${s.id}`}
                    onClick={() => setConfirmDelete(s)}
                    className="p-2 rounded hover:bg-white/5 transition-colors"
                    title="Delete"
                    type="button"
                    style={{ color: "var(--error)" }}
                  >
                    <Trash2 size={15} strokeWidth={1.5} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {editing !== null && (
        <StudentForm
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}

      {confirmDelete && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
          <div className="surface p-6 max-w-sm w-full">
            <h3 className="font-serif-display text-xl mb-2">Remove student?</h3>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
              This will also delete all class logs and payments for {confirmDelete.name}.
            </p>
            <div className="flex justify-end gap-3">
              <button className="btn-ghost" onClick={() => setConfirmDelete(null)} data-testid="confirm-delete-cancel">
                Cancel
              </button>
              <button
                className="btn-pill"
                style={{ background: "var(--error)", color: "white" }}
                onClick={remove}
                data-testid="confirm-delete-btn"
              >
                Yes, remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
