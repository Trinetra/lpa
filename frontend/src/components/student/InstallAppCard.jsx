import React, { useEffect, useState } from "react";
import { Download, Share, MoreVertical, CheckCircle2 } from "lucide-react";

function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)")?.matches ||
    window.navigator.standalone === true
  );
}

function isIOS() {
  return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
}

// Unlike a one-shot dismissible banner, this always renders (until the app
// is actually installed) so students can find it again in Settings even if
// they missed or dismissed it earlier. Chrome only fires beforeinstallprompt
// after its own engagement heuristic passes — not necessarily on first
// visit — so the manual 3-dot-menu instructions are shown as the reliable
// fallback whenever that event hasn't arrived yet.
export default function InstallAppCard() {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    const onBeforeInstall = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    const onInstalled = () => setInstalled(true);
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const ios = isIOS();

  const install = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    setDeferredPrompt(null);
  };

  if (isStandalone() || installed) {
    return (
      <div data-testid="install-app-card" className="surface p-6">
        <div className="flex items-center gap-2 mb-1">
          <CheckCircle2 size={14} strokeWidth={1.5} style={{ color: "var(--success)" }} />
          <div className="uppercase-label">App</div>
        </div>
        <h2 className="font-serif-display text-2xl mb-2">Installed</h2>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          You're using the installed app on this device.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="install-app-card" className="surface p-6">
      <div className="flex items-center gap-2 mb-1">
        <Download size={14} strokeWidth={1.5} style={{ color: "var(--primary)" }} />
        <div className="uppercase-label">App</div>
      </div>
      <h2 className="font-serif-display text-2xl mb-2">Add to home screen</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
        Install the portal on this device for one-tap access, like any other app.
      </p>
      {deferredPrompt ? (
        <button type="button" onClick={install} className="btn-pill" data-testid="install-app-btn">
          Install app
        </button>
      ) : ios ? (
        <div className="text-sm flex items-center gap-1 flex-wrap" style={{ color: "var(--text-muted)" }}>
          Tap the Share icon <Share size={13} className="inline" /> in Safari, then "Add to Home Screen".
        </div>
      ) : (
        <div className="text-sm flex items-center gap-1 flex-wrap" style={{ color: "var(--text-muted)" }}>
          Tap the menu icon <MoreVertical size={13} className="inline" /> in Chrome, then "Install app" or "Add to Home screen".
        </div>
      )}
    </div>
  );
}
