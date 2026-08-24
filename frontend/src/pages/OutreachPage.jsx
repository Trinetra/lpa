import React, { useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import {
  Plus, Trash2, Send, ArrowLeft, Loader2, Copy, Pencil,
  Bold, Italic, Underline, AlignLeft, AlignCenter, AlignRight, Link2, Image as ImageIcon,
} from "lucide-react";
import { toast } from "sonner";

// Puts the rendered email on the clipboard as rich HTML (not just text) so
// pasting into a Gmail compose window reproduces the formatted email —
// mirrors the template's own original "select all, copy, paste into Gmail"
// workflow, just without the manual find-and-replace step first.
async function copyHtmlToClipboard(html) {
  if (navigator.clipboard?.write && window.ClipboardItem) {
    const item = new ClipboardItem({
      "text/html": new Blob([html], { type: "text/html" }),
      "text/plain": new Blob([html.replace(/<[^>]+>/g, " ")], { type: "text/plain" }),
    });
    await navigator.clipboard.write([item]);
    return;
  }
  // Fallback for browsers without the rich Clipboard API — a document.
  // execCommand("copy") on a selected contenteditable node still copies
  // as HTML in every major browser, just via an older, deprecated path.
  const holder = document.createElement("div");
  holder.setAttribute("contenteditable", "true");
  holder.style.position = "fixed";
  holder.style.opacity = "0";
  holder.innerHTML = html;
  document.body.appendChild(holder);
  const range = document.createRange();
  range.selectNodeContents(holder);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  document.execCommand("copy");
  sel.removeAllRanges();
  document.body.removeChild(holder);
}

const RICH_TEXT_COLORS = ["#3a3a3a", "#7a1f2b", "#8a6d3b", "#2b6b3a", "#1a4b8a"];
// execCommand("fontSize") only accepts the legacy 1-7 <font size> scale, not
// a CSS px value — this maps to that scale, then a DOM pass afterward
// rewrites the resulting <font size="n"> back into a real inline
// font-size in px, which is what the server sanitizer actually looks for.
const RICH_TEXT_SIZES = [
  { label: "Small", legacy: "2", px: "13px" },
  { label: "Normal", legacy: "3", px: "16px" },
  { label: "Large", legacy: "5", px: "20px" },
];

// A contenteditable rich-text region with a small fixed toolbar. The
// browser's own execCommand output (mixed <b>/<font>/<div>/style tags,
// inconsistent across browsers) is never trusted as-is — the server
// re-sanitizes into a fixed allowlisted vocabulary before it's ever stored
// or merged into an outreach email (see _sanitize_rich_html in server.py).
// This editor only needs to produce *something* reasonable for her to look
// at; correctness of the final email HTML is enforced server-side.
function RichTextEditor({ value, onChange }) {
  const ref = useRef(null);
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== value) {
      ref.current.innerHTML = value || "";
    }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  const emitChange = () => onChange(ref.current?.innerHTML || "");

  const exec = (command, arg) => {
    ref.current?.focus();
    document.execCommand(command, false, arg);
    emitChange();
  };

  const setFontSize = (legacy, px) => {
    ref.current?.focus();
    document.execCommand("fontSize", false, legacy);
    // Rewrite every <font size="legacy"> the command just produced into a
    // span with a real px font-size — <font size> never survives the
    // server sanitizer's allowlist, so leaving it as-is would silently
    // drop her size choice.
    ref.current?.querySelectorAll(`font[size="${legacy}"]`).forEach((el) => {
      const span = document.createElement("span");
      span.style.fontSize = px;
      span.innerHTML = el.innerHTML;
      el.replaceWith(span);
    });
    emitChange();
  };

  const insertLink = () => {
    const url = window.prompt("Link URL (https://…)");
    if (!url) return;
    exec("createLink", url);
  };

  const insertImage = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/uploads/photo", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const url = data.path.startsWith("http") ? data.path : `${window.location.origin}${data.path}`;
      exec("insertImage", url);
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't upload image");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-1 flex-wrap mb-1 p-1 rounded" style={{ border: "1px solid var(--border)" }}>
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => exec("bold")}
          className="btn-ghost p-1.5" title="Bold"><Bold size={13} /></button>
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => exec("italic")}
          className="btn-ghost p-1.5" title="Italic"><Italic size={13} /></button>
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => exec("underline")}
          className="btn-ghost p-1.5" title="Underline"><Underline size={13} /></button>
        <span style={{ width: 1, background: "var(--border)", alignSelf: "stretch" }} />
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => exec("justifyLeft")}
          className="btn-ghost p-1.5" title="Align left"><AlignLeft size={13} /></button>
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => exec("justifyCenter")}
          className="btn-ghost p-1.5" title="Align center"><AlignCenter size={13} /></button>
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => exec("justifyRight")}
          className="btn-ghost p-1.5" title="Align right"><AlignRight size={13} /></button>
        <span style={{ width: 1, background: "var(--border)", alignSelf: "stretch" }} />
        <select onMouseDown={(e) => e.preventDefault()}
          onChange={(e) => {
            const s = RICH_TEXT_SIZES.find((x) => x.px === e.target.value);
            if (s) setFontSize(s.legacy, s.px);
            e.target.value = "";
          }}
          defaultValue="" className="btn-ghost text-xs" style={{ padding: "4px 6px" }} title="Text size">
          <option value="" disabled>Size</option>
          {RICH_TEXT_SIZES.map((s) => <option key={s.px} value={s.px}>{s.label}</option>)}
        </select>
        <select onMouseDown={(e) => e.preventDefault()}
          onChange={(e) => { exec("foreColor", e.target.value); e.target.value = ""; }}
          defaultValue="" className="btn-ghost text-xs" style={{ padding: "4px 6px" }} title="Text color">
          <option value="" disabled>Color</option>
          {RICH_TEXT_COLORS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span style={{ width: 1, background: "var(--border)", alignSelf: "stretch" }} />
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={insertLink}
          className="btn-ghost p-1.5" title="Insert link"><Link2 size={13} /></button>
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => fileRef.current?.click()}
          disabled={uploading} className="btn-ghost p-1.5" title="Insert image">
          {uploading ? <Loader2 size={13} className="animate-spin" /> : <ImageIcon size={13} />}
        </button>
        <input ref={fileRef} type="file" accept="image/*" onChange={insertImage} className="hidden" />
      </div>
      <div
        ref={ref}
        contentEditable
        onInput={emitChange}
        onBlur={emitChange}
        data-testid="outreach-richtext-editor"
        className="w-full bg-transparent border border-white/10 rounded px-3 py-2 text-sm"
        style={{ minHeight: 140, outline: "none" }}
      />
    </div>
  );
}

function TemplateForm({ existing, onClose, onSaved }) {
  const [name, setName] = useState(existing?.name || "");
  const [subject, setSubject] = useState(existing?.subject || "");
  const [html, setHtml] = useState(existing?.html || "");
  const [saving, setSaving] = useState(false);
  const isEdit = !!existing;

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = isEdit
        ? await api.patch(`/outreach-templates/${existing.id}`, { name, subject, html })
        : await api.post("/outreach-templates", { name, subject, html });
      toast.success(isEdit ? "Template updated" : "Template saved");
      onSaved(data);
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't save template");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="outreach-new-template-form" className="surface p-6 space-y-4">
      <h2 className="font-serif-display text-2xl">{isEdit ? `Edit "${existing.name}"` : "New template"}</h2>
      <label className="block">
        <span className="uppercase-label block mb-1">Name</span>
        <input required value={name} onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Bharatanatyam Outreach"
          data-testid="outreach-template-name-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>
      <label className="block">
        <span className="uppercase-label block mb-1">Subject line</span>
        <input required value={subject} onChange={(e) => setSubject(e.target.value)}
          placeholder="e.g. Bharatanatyam performance & workshop enquiry"
          data-testid="outreach-template-subject-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      </label>
      <label className="block">
        <span className="uppercase-label block mb-1">HTML</span>
        <textarea required rows={10} value={html} onChange={(e) => setHtml(e.target.value)}
          placeholder="Paste the full HTML source of the email"
          data-testid="outreach-template-html-input"
          className="w-full bg-transparent border border-white/10 rounded px-3 py-2 font-mono text-xs" />
        <span className="text-xs mt-1 block" style={{ color: "var(--text-muted)" }}>
          Any {"{{Field Name}}"} tokens in the HTML become fill-in fields automatically.
        </span>
      </label>
      <div className="flex justify-end gap-3">
        <button type="button" onClick={onClose} className="btn-ghost" data-testid="outreach-new-template-cancel">Cancel</button>
        <button type="submit" disabled={saving} className="btn-pill" data-testid="outreach-new-template-save">
          {saving ? "Saving…" : "Save template"}
        </button>
      </div>
    </form>
  );
}

function SendPanel({ template, onBack, onTemplateUpdated, ownerEmail }) {
  const [toEmail, setToEmail] = useState("");
  const [replyTo, setReplyTo] = useState(ownerEmail || "");
  const [fields, setFields] = useState(() => {
    const init = {};
    template.merge_fields.forEach((f) => {
      init[f.name] = template.default_values?.[f.name] || (f.kind === "color" ? "#ffffff" : "");
    });
    return init;
  });
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [copying, setCopying] = useState(false);

  const saveDefault = async (fieldName, value) => {
    try {
      const nextDefaults = { ...(template.default_values || {}), [fieldName]: value };
      const { data } = await api.patch(`/outreach-templates/${template.id}`, { default_values: nextDefaults });
      onTemplateUpdated(data);
      toast.success(`Saved as the default for "${fieldName}"`);
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't save default");
    }
  };

  const loadPreview = async () => {
    setPreviewLoading(true);
    try {
      const { data } = await api.post(`/outreach-templates/${template.id}/preview`, {
        to_email: toEmail || "preview@example.com", reply_to: replyTo || null, field_values: fields,
      });
      setPreview(data);
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't build preview");
    } finally {
      setPreviewLoading(false);
    }
  };

  useEffect(() => { loadPreview(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(loadPreview, 400); // debounce as she types
    return () => clearTimeout(t);
  }, [JSON.stringify(fields)]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = async (e) => {
    e.preventDefault();
    setSending(true);
    try {
      await api.post(`/outreach-templates/${template.id}/send`, {
        to_email: toEmail, reply_to: replyTo || null, field_values: fields,
      });
      toast.success(`Sent to ${toEmail}`);
      setToEmail("");
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't send");
    } finally {
      setSending(false);
    }
  };

  const copy = async () => {
    if (!preview?.html) return;
    setCopying(true);
    try {
      await copyHtmlToClipboard(preview.html);
      toast.success("Copied — paste it into a new Gmail compose window");
    } catch (e2) {
      toast.error("Couldn't copy — your browser may not allow this. Try again from the tab you're actively viewing.");
    } finally {
      setCopying(false);
    }
  };

  return (
    <div data-testid="outreach-send-panel" className="space-y-6">
      <button type="button" onClick={onBack} className="btn-ghost flex items-center gap-2 text-xs" data-testid="outreach-send-back-btn">
        <ArrowLeft size={14} /> All templates
      </button>

      <div className="grid md:grid-cols-2 gap-6">
        <form onSubmit={send} className="surface p-6 space-y-4">
          <h2 className="font-serif-display text-2xl">{template.name}</h2>
          <label className="block">
            <span className="uppercase-label block mb-1">Send to</span>
            <input required type="email" value={toEmail} onChange={(e) => setToEmail(e.target.value)}
              placeholder="recipient@school.edu"
              data-testid="outreach-to-email-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          <label className="block">
            <span className="uppercase-label block mb-1">Replies go to</span>
            <input type="email" value={replyTo} onChange={(e) => setReplyTo(e.target.value)}
              data-testid="outreach-reply-to-input"
              className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
          </label>
          {template.merge_fields.length > 0 && (
            <div className="space-y-3">
              <span className="uppercase-label block">Personalize</span>
              {template.merge_fields.map((f) => (
                <label key={f.name} className="block">
                  <span className="text-xs block mb-1" style={{ color: "var(--text-muted)" }}>{f.name}</span>
                  {f.kind === "paragraph" ? (
                    <>
                      <RichTextEditor
                        value={fields[f.name] || ""}
                        onChange={(html) => setFields((prev) => ({ ...prev, [f.name]: html }))}
                      />
                      <div className="flex items-center justify-end mt-1">
                        <button type="button" onClick={() => saveDefault(f.name, fields[f.name] || "")}
                          className="text-[11px] shrink-0 underline" style={{ color: "var(--text-muted)" }}
                          data-testid={`outreach-save-default-${f.name}`}>
                          Save as this template's default
                        </button>
                      </div>
                    </>
                  ) : f.kind === "color" ? (
                    <div className="flex items-center gap-2">
                      <input type="color" value={fields[f.name] || "#ffffff"}
                        onChange={(e) => setFields((prev) => ({ ...prev, [f.name]: e.target.value }))}
                        data-testid={`outreach-field-input-${f.name}`}
                        className="h-9 w-14 rounded border border-white/10 bg-transparent" />
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>{fields[f.name] || "#ffffff"}</span>
                    </div>
                  ) : (
                    <input value={fields[f.name] || ""}
                      onChange={(e) => setFields((prev) => ({ ...prev, [f.name]: e.target.value }))}
                      data-testid={`outreach-field-input-${f.name}`}
                      className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
                  )}
                </label>
              ))}
            </div>
          )}
          <div className="flex gap-3">
            <button type="button" onClick={copy} disabled={copying || previewLoading}
              className="btn-ghost flex-1 flex items-center justify-center gap-2" data-testid="outreach-copy-btn">
              {copying ? <Loader2 size={14} className="animate-spin" /> : <Copy size={14} />} Copy for Gmail
            </button>
            <button type="submit" disabled={sending} className="btn-pill flex-1 flex items-center justify-center gap-2" data-testid="outreach-send-btn">
              {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Send email
            </button>
          </div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            <strong>Copy for Gmail</strong> puts the formatted email on your clipboard — open a new Gmail compose window and paste, then send from your own inbox.
            <strong> Send email</strong> sends it now, with replies routed to the address above.
          </p>
          <p className="text-xs" style={{ color: "var(--error)" }} data-testid="outreach-copy-warning">
            Always paste from here into a brand-new compose window — never copy the text back out of a previously sent email. Gmail rewrites formatting when it sends a message, so copying from a Sent copy carries that damage (centered text, wrong font) into every email after it.
          </p>
        </form>

        <div className="surface p-2 overflow-hidden">
          <div className="uppercase-label px-4 pt-3 pb-2">Preview</div>
          {previewLoading && !preview ? (
            <div className="p-6 text-sm uppercase-label">Loading…</div>
          ) : (
            <iframe
              title="Email preview"
              data-testid="outreach-preview-frame"
              srcDoc={preview?.html || ""}
              sandbox="allow-same-origin"
              style={{ width: "100%", height: "640px", border: "none", background: "#ffffff", borderRadius: "6px" }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default function OutreachPage() {
  const [templates, setTemplates] = useState(null);
  const [creating, setCreating] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState(null);
  const [active, setActive] = useState(null);
  const [ownerEmail, setOwnerEmail] = useState("");

  const load = () => {
    api.get("/outreach-templates").then((r) => setTemplates(r.data)).catch(() => setTemplates([]));
  };

  useEffect(() => {
    load();
    api.get("/profile").then((r) => setOwnerEmail(r.data.contact_email || r.data.email || "")).catch(() => {});
  }, []);

  const remove = async (id) => {
    if (!window.confirm("Delete this template?")) return;
    try {
      await api.delete(`/outreach-templates/${id}`);
      toast.success("Deleted");
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't delete");
    }
  };

  const duplicate = async (t) => {
    try {
      const existingNames = new Set(templates.map((x) => x.name));
      let name = `${t.name} (copy)`;
      let n = 2;
      while (existingNames.has(name)) {
        name = `${t.name} (copy ${n})`;
        n += 1;
      }
      await api.post("/outreach-templates", {
        name, subject: t.subject, html: t.html, default_values: t.default_values || {},
      });
      toast.success("Duplicated — edit the copy's HTML to make your changes");
      load();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't duplicate");
    }
  };

  if (active) {
    return (
      <div data-testid="outreach-page" className="space-y-6">
        <SendPanel template={active} onBack={() => setActive(null)} onTemplateUpdated={setActive} ownerEmail={ownerEmail} />
      </div>
    );
  }

  return (
    <div data-testid="outreach-page" className="space-y-6">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">Cold outreach</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Outreach</h1>
        </div>
        {!creating && (
          <button onClick={() => setCreating(true)} data-testid="outreach-new-template-btn" className="btn-pill flex items-center gap-2">
            <Plus size={16} /> New template
          </button>
        )}
      </header>

      {creating && <TemplateForm onClose={() => setCreating(false)} onSaved={load} />}
      {editingTemplate && (
        <TemplateForm existing={editingTemplate} onClose={() => setEditingTemplate(null)} onSaved={load} />
      )}

      {templates === null ? (
        <div data-testid="outreach-loading" className="uppercase-label">Loading…</div>
      ) : templates.length === 0 && !creating ? (
        <div className="surface p-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
          No templates yet — save one to start sending outreach emails from here.
        </div>
      ) : (
        <div className="surface">
          {templates.map((t) => (
            <div key={t.id} data-testid={`outreach-template-row-${t.id}`}
              className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 px-6 py-4"
              style={{ borderTop: "1px solid var(--border)" }}>
              <button type="button" onClick={() => setActive(t)} className="text-left" data-testid={`outreach-template-open-${t.id}`}>
                <div className="font-serif-display text-xl">{t.name}</div>
                <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{t.subject}</div>
              </button>
              <div className="flex items-center gap-3 flex-wrap sm:shrink-0">
                <button type="button" onClick={() => setActive(t)} className="btn-ghost text-xs" data-testid={`outreach-template-send-${t.id}`}>
                  Open
                </button>
                <button type="button" onClick={() => duplicate(t)} className="btn-ghost text-xs flex items-center gap-1"
                  data-testid={`outreach-template-duplicate-${t.id}`}>
                  <Copy size={12} /> Duplicate
                </button>
                <button type="button" onClick={() => setEditingTemplate(t)} className="btn-ghost text-xs flex items-center gap-1"
                  data-testid={`outreach-template-edit-${t.id}`}>
                  <Pencil size={12} /> Edit
                </button>
                <button type="button" onClick={() => remove(t.id)} className="btn-ghost text-xs" style={{ color: "var(--error)" }}
                  data-testid={`outreach-template-delete-${t.id}`}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
