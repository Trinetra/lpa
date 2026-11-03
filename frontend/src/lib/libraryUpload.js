import { api } from "@/lib/api";

// Uploads one file to the Library: the backend starts a multipart upload in
// R2 and hands out presigned part URLs; the parts go straight from the browser
// to R2 (never through our server), a few at a time, each retried on failure.
const PARALLEL = 3;
const RETRIES = 4;

function putPart(url, blob, onBytes, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let sent = 0;
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => { onBytes(e.loaded - sent); sent = e.loaded; };
    xhr.onload = () => {
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag);
      else { onBytes(-sent); reject(new Error(`Part upload failed (${xhr.status})`)); }
    };
    xhr.onerror = () => { onBytes(-sent); reject(new Error("Network error")); };
    xhr.onabort = () => { onBytes(-sent); reject(new DOMException("Cancelled", "AbortError")); };
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(blob);
  });
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// A still from ~1s in, as a JPEG blob, or null if the browser can't decode it.
export function videoThumbnail(file) {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    const done = (blob) => { URL.revokeObjectURL(url); resolve(blob); };
    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.onloadedmetadata = () => { video.currentTime = Math.min(1, (video.duration || 2) / 2); };
    video.onseeked = () => {
      const scale = Math.min(1, 800 / Math.max(video.videoWidth, video.videoHeight || 1));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      if (!canvas.width || !canvas.height) return done(null);
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((b) => done(b), "image/jpeg", 0.8);
    };
    video.onerror = () => done(null);
    setTimeout(() => done(null), 15000);
    video.src = url;
  });
}

// meta: { category, performance_ref, version, notes, tags }. onProgress(bytesDone).
export async function uploadLibraryFile(productionId, file, meta, { onProgress, signal } = {}) {
  const start = await api.post(`/library/productions/${productionId}/uploads`, {
    ...meta, filename: file.name, size: file.size, content_type: file.type || null,
  });
  const { item, part_size: partSize, part_count: partCount } = start.data;
  let finished;
  try {
    let done = 0;
    let failed = false;
    const onBytes = (n) => { done += n; onProgress?.(done); };
    const urls = {};
    const etags = [];
    let next = 1;

    const urlFor = async (n) => {
      if (!urls[n]) {
        const numbers = Array.from({ length: Math.min(50, partCount - n + 1) }, (_, i) => n + i);
        Object.assign(urls, (await api.post(`/library/items/${item.id}/parts`, { numbers })).data.urls);
      }
      return urls[n];
    };

    const worker = async () => {
      while (next <= partCount && !failed) {
        const n = next++;
        const blob = file.slice((n - 1) * partSize, Math.min(n * partSize, file.size));
        for (let attempt = 1; ; attempt++) {
          if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
          try {
            etags[n] = await putPart(await urlFor(n), blob, onBytes, signal);
            break;
          } catch (e) {
            if (e.name === "AbortError" || attempt >= RETRIES) { failed = true; throw e; }
            delete urls[n]; // a fresh URL in case the old one expired
            await wait(1000 * 2 ** attempt);
          }
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(PARALLEL, partCount) }, worker));

    const parts = etags.map((etag, n) => (etag ? { part_number: n, etag } : null)).filter(Boolean);
    finished = (await api.post(`/library/items/${item.id}/complete`, { parts })).data;
  } catch (e) {
    api.delete(`/library/items/${item.id}`).catch(() => {}); // cancels the half-done upload
    throw e;
  }

  // Best-effort: the file is safely in, a missing preview is fine.
  if ((file.type || "").startsWith("video/")) {
    try {
      const thumb = await videoThumbnail(file);
      if (thumb) {
        const form = new FormData();
        form.append("file", thumb, "thumb.jpg");
        finished = (await api.post(`/library/items/${item.id}/thumbnail`, form)).data;
      }
    } catch {}
  }
  return finished;
}
