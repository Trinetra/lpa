import React, { useEffect, useState } from "react";
import { Download, Share } from "lucide-react";

function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)")?.matches ||
    window.navigator.standalone === true
  );
}

function isIOS() {
  return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
}

export default function InstallAppPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [installed, setInstalled] = useState(false);
  const [dismissed, setDismissed] = useState(false);

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

  if (isStandalone() || installed || dismissed) return null;

  const canPromptNatively = !!deferredPrompt;
  const ios = isIOS();
  if (!canPromptNatively && !ios) return null;

  const install = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    setDeferredPrompt(null);
  };

  return (
    <div className="surface p-4" data-testid="install-app-prompt" style={{ background: "var(--surface-2)" }}>
      <div className="flex items-start gap-3">
        <div className="shrink-0 p-2 rounded-full" style={{ background: "rgba(212,132,100,0.15)", color: "var(--primary)" }}>
          {ios && !canPromptNatively ? <Share size={16} /> : <Download size={16} />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium">Add to your home screen</div>
          {canPromptNatively ? (
            <>
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Install the portal for one-tap access, like any other app.
              </div>
              <button type="button" onClick={install} className="btn-ghost mt-2 text-xs" data-testid="install-app-btn">
                Install app
              </button>
            </>
          ) : (
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Tap the Share icon <Share size={11} className="inline" /> in Safari, then "Add to Home Screen".
            </div>
          )}
        </div>
        <button type="button" onClick={() => setDismissed(true)} className="text-xs shrink-0" data-testid="install-app-dismiss"
          style={{ color: "var(--text-muted)" }}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
