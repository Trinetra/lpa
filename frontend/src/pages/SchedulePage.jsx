import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { DndContext, useDraggable, useDroppable, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { Plus, X, Trash2 } from "lucide-react";
import { toast } from "sonner";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const START_HOUR = 6;
const END_HOUR = 22;
const HOUR_HEIGHT = 56; // px per hour, drives the whole grid's vertical scale
const SLOT_MINUTES = 15; // snap granularity for drag/resize

const toMinutes = (t) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};
const toTimeStr = (mins) => {
  mins = Math.max(0, Math.min(24 * 60, mins));
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};
const fmt12h = (t) => {
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12}${period}` : `${h12}:${String(m).padStart(2, "0")}${period}`;
};
const snap = (mins) => Math.round(mins / SLOT_MINUTES) * SLOT_MINUTES;
const minutesFromTop = (px) => snap((px / HOUR_HEIGHT) * 60) + START_HOUR * 60;
const topFromMinutes = (mins) => ((mins - START_HOUR * 60) / 60) * HOUR_HEIGHT;

function DayColumn({ dayIndex, children }) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${dayIndex}` });
  return (
    <div
      ref={setNodeRef}
      data-testid={`schedule-day-${dayIndex}`}
      className="relative border-l"
      style={{
        borderColor: "var(--border)",
        height: (END_HOUR - START_HOUR) * HOUR_HEIGHT,
        background: isOver ? "rgba(212,132,100,0.06)" : "transparent",
      }}
    >
      {Array.from({ length: END_HOUR - START_HOUR }).map((_, i) => (
        <div
          key={i}
          className="absolute left-0 right-0 border-t"
          style={{ top: i * HOUR_HEIGHT, borderColor: "var(--border)" }}
        />
      ))}
      {children}
    </div>
  );
}

function BlockCard({ block, studentMap, onOpen, onResizeStart }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: block.id,
    data: { block },
  });

  const startM = toMinutes(block.start_time);
  const endM = toMinutes(block.end_time);
  const top = topFromMinutes(startM);
  const height = Math.max(20, topFromMinutes(endM) - top);

  const names = block.student_ids
    .map((sid) => studentMap[sid]?.name)
    .filter(Boolean)
    .join(", ") || "No students";

  const style = {
    top,
    height,
    transform: transform ? `translate(${transform.x}px, ${transform.y}px)` : undefined,
    zIndex: isDragging ? 30 : 1,
    background: "var(--primary)",
    opacity: isDragging ? 0.85 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={(e) => {
        // Avoid opening the editor right after a drag/resize gesture.
        if (isDragging) return;
        onOpen(block);
      }}
      data-testid={`schedule-block-${block.id}`}
      className="absolute left-1 right-1 rounded-md px-2 py-1 text-xs cursor-grab active:cursor-grabbing overflow-hidden select-none"
      style={style}
    >
      <div className="font-medium truncate" style={{ color: "#2c2926" }}>
        {fmt12h(block.start_time)}–{fmt12h(block.end_time)}
      </div>
      <div className="truncate" style={{ color: "rgba(44,41,38,0.85)" }}>
        {names}
      </div>
      <div
        onMouseDown={(e) => {
          e.stopPropagation();
          onResizeStart(block, e);
        }}
        onPointerDown={(e) => e.stopPropagation()}
        className="absolute bottom-0 left-0 right-0 h-2 cursor-ns-resize"
        data-testid={`schedule-block-resize-${block.id}`}
      />
    </div>
  );
}

function BlockModal({ block, students, onClose, onSaved, onDeleted }) {
  const isNew = !block?.id;
  const [dayOfWeek, setDayOfWeek] = useState(block?.day_of_week ?? 0);
  const [startTime, setStartTime] = useState(block?.start_time || "09:00");
  const [endTime, setEndTime] = useState(block?.end_time || "10:00");
  const [studentIds, setStudentIds] = useState(block?.student_ids || []);
  const [notes, setNotes] = useState(block?.notes || "");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const toggleStudent = (sid) => {
    setStudentIds((prev) =>
      prev.includes(sid) ? prev.filter((x) => x !== sid) : [...prev, sid]
    );
  };

  const submit = async (e) => {
    e.preventDefault();
    if (studentIds.length === 0) {
      toast.error("Pick at least one student");
      return;
    }
    setSaving(true);
    try {
      const body = {
        day_of_week: Number(dayOfWeek),
        start_time: startTime,
        end_time: endTime,
        student_ids: studentIds,
        notes: notes || null,
      };
      if (isNew) {
        await api.post("/schedule", body);
        toast.success("Class added to schedule");
      } else {
        await api.patch(`/schedule/${block.id}`, body);
        toast.success("Schedule block updated");
      }
      onSaved();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove this class from the schedule?")) return;
    setDeleting(true);
    try {
      await api.delete(`/schedule/${block.id}`);
      toast.success("Removed from schedule");
      onDeleted();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <form onSubmit={submit} data-testid="schedule-block-form" className="surface w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-serif-display text-2xl">{isNew ? "Add class" : "Edit class"}</h3>
          <button type="button" onClick={onClose} data-testid="schedule-modal-close" className="p-1">
            <X size={18} />
          </button>
        </div>

        <label className="block mb-3">
          <span className="uppercase-label block mb-1">Day</span>
          <select
            value={dayOfWeek}
            onChange={(e) => setDayOfWeek(e.target.value)}
            data-testid="schedule-day-select"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
          >
            {DAYS.map((d, i) => (
              <option key={i} value={i} style={{ color: "#000" }}>{d}</option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="uppercase-label block mb-1">Start</span>
            <input
              type="time"
              required
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              data-testid="schedule-start-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">End</span>
            <input
              type="time"
              required
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              data-testid="schedule-end-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
            />
          </label>
        </div>

        <div className="block mb-3">
          <span className="uppercase-label block mb-2">Students</span>
          <div className="max-h-40 overflow-y-auto space-y-1 border rounded p-2" style={{ borderColor: "var(--border)" }}>
            {students.length === 0 && (
              <div className="text-sm" style={{ color: "var(--text-muted)" }}>No students yet.</div>
            )}
            {students.map((s) => (
              <label key={s.id} className="flex items-center gap-2 px-1 py-1 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={studentIds.includes(s.id)}
                  onChange={() => toggleStudent(s.id)}
                  data-testid={`schedule-student-checkbox-${s.id}`}
                />
                {s.name}
              </label>
            ))}
          </div>
        </div>

        <label className="block mb-6">
          <span className="uppercase-label block mb-1">Notes (optional)</span>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            data-testid="schedule-notes-input"
            className="w-full bg-transparent border border-white/10 rounded px-3 py-2"
          />
        </label>

        <div className="flex justify-between gap-3">
          {!isNew ? (
            <button
              type="button"
              onClick={remove}
              disabled={deleting}
              data-testid="schedule-delete-btn"
              className="btn-ghost flex items-center gap-2"
              style={{ color: "var(--error)" }}
            >
              <Trash2 size={16} /> Remove
            </button>
          ) : <span />}
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="btn-ghost" data-testid="schedule-cancel-btn">Cancel</button>
            <button type="submit" disabled={saving} className="btn-pill" data-testid="schedule-save-btn">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

export default function SchedulePage() {
  const [blocks, setBlocks] = useState([]);
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // block being edited, or {} for new
  const resizeState = useRef(null);

  const studentMap = useMemo(() => {
    const m = {};
    students.forEach((s) => { m[s.id] = s; });
    return m;
  }, [students]);

  const load = async () => {
    setLoading(true);
    try {
      const [schedRes, studRes] = await Promise.all([
        api.get("/schedule"),
        api.get("/students"),
      ]);
      setBlocks(schedRes.data);
      setStudents(studRes.data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Failed to load schedule");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const patchBlock = async (id, body) => {
    try {
      const { data } = await api.patch(`/schedule/${id}`, body);
      setBlocks((prev) => prev.map((b) => (b.id === id ? data : b)));
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't move that class — check for overlaps");
      load(); // revert to server state
    }
  };

  const handleDragEnd = (event) => {
    const { active, delta, over } = event;
    const block = active.data.current?.block;
    if (!block) return;

    const duration = toMinutes(block.end_time) - toMinutes(block.start_time);
    const deltaMinutes = snap((delta.y / HOUR_HEIGHT) * 60);
    let newStartM = toMinutes(block.start_time) + deltaMinutes;
    newStartM = Math.max(START_HOUR * 60, Math.min(END_HOUR * 60 - duration, newStartM));

    const targetDay = over?.id?.startsWith("day-") ? Number(over.id.split("-")[1]) : block.day_of_week;

    if (newStartM === toMinutes(block.start_time) && targetDay === block.day_of_week) return;

    patchBlock(block.id, {
      day_of_week: targetDay,
      start_time: toTimeStr(newStartM),
      end_time: toTimeStr(newStartM + duration),
    });
  };

  const handleResizeStart = (block, e) => {
    resizeState.current = { block, startY: e.clientY };
    const onMove = (moveEvent) => {
      // Live-preview isn't tracked in state to keep this simple; the final
      // value is committed on mouseup via patchBlock.
      moveEvent.preventDefault();
    };
    const onUp = (upEvent) => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      const { block: b, startY } = resizeState.current;
      const deltaMinutes = snap(((upEvent.clientY - startY) / HOUR_HEIGHT) * 60);
      const startM = toMinutes(b.start_time);
      let newEndM = toMinutes(b.end_time) + deltaMinutes;
      newEndM = Math.max(startM + SLOT_MINUTES, Math.min(END_HOUR * 60, newEndM));
      if (newEndM !== toMinutes(b.end_time)) {
        patchBlock(b.id, { end_time: toTimeStr(newEndM) });
      }
      resizeState.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const openNew = (dayIndex) => {
    setEditing({ day_of_week: dayIndex });
  };

  if (loading) return <div data-testid="schedule-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="schedule-page" className="space-y-6">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Weekly training</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Schedule</h1>
        </div>
        <button
          onClick={() => openNew(0)}
          data-testid="schedule-add-btn"
          className="btn-pill flex items-center gap-2"
        >
          <Plus size={16} /> Add class
        </button>
      </header>

      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        Drag a class to move it, drag its bottom edge to resize. Click a class to edit students or notes.
      </p>

      <div className="surface overflow-x-auto">
        <div className="min-w-[720px]">
          {/* Day headers */}
          <div className="grid" style={{ gridTemplateColumns: "48px repeat(7, 1fr)" }}>
            <div />
            {DAY_SHORT.map((d, i) => (
              <div key={i} className="text-center py-3 uppercase-label" data-testid={`schedule-day-header-${i}`}>
                {d}
              </div>
            ))}
          </div>

          <DndContext sensors={sensors} onDragEnd={handleDragEnd} modifiers={[]}>
            <div className="grid" style={{ gridTemplateColumns: "48px repeat(7, 1fr)" }}>
              {/* Hour labels */}
              <div className="relative" style={{ height: (END_HOUR - START_HOUR) * HOUR_HEIGHT }}>
                {Array.from({ length: END_HOUR - START_HOUR }).map((_, i) => (
                  <div
                    key={i}
                    className="absolute right-2 text-[10px]"
                    style={{ top: i * HOUR_HEIGHT - 6, color: "var(--text-muted)" }}
                  >
                    {fmt12h(`${String(START_HOUR + i).padStart(2, "0")}:00`)}
                  </div>
                ))}
              </div>

              {DAYS.map((_, dayIndex) => (
                <DayColumn key={dayIndex} dayIndex={dayIndex}>
                  {blocks
                    .filter((b) => b.day_of_week === dayIndex)
                    .map((b) => (
                      <BlockCard
                        key={b.id}
                        block={b}
                        studentMap={studentMap}
                        onOpen={setEditing}
                        onResizeStart={handleResizeStart}
                      />
                    ))}
                  <button
                    onClick={() => openNew(dayIndex)}
                    data-testid={`schedule-add-day-${dayIndex}`}
                    className="absolute inset-x-1 bottom-1 text-[10px] uppercase tracking-wide opacity-0 hover:opacity-100 transition-opacity"
                    style={{ color: "var(--text-muted)" }}
                  >
                    + Add
                  </button>
                </DayColumn>
              ))}
            </div>
          </DndContext>
        </div>
      </div>

      {editing && (
        <BlockModal
          block={editing}
          students={students}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
          onDeleted={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}
