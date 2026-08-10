import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, BellOff } from "lucide-react";
import { pushSupported, getExistingSubscription, subscribe, unsubscribe } from "@/lib/push";

/** Shared by the teacher Settings page and the student portal sidebar —
 * just needs the right axios instance + endpoint paths for whichever
 * audience is subscribing. `variant="nav"` renders as a sidebar nav-link
 * (student portal); the default renders as a standalone button (Settings). */
export default function PushNotificationToggle({
  apiClient, subscribeUrl, unsubscribeUrl, testidPrefix = "push", variant = "button",
}) {
  const [subscribed, setSubscribed] = useState(null); // null = checking
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!pushSupported()) {
      setSubscribed(false);
      return;
    }
    getExistingSubscription()
      .then((sub) => setSubscribed(!!sub))
      .catch(() => setSubscribed(false));
  }, []);

  if (!pushSupported()) return null;

  const toggle = async () => {
    setBusy(true);
    try {
      if (subscribed) {
        await unsubscribe(apiClient, unsubscribeUrl);
        setSubscribed(false);
      } else {
        if (Notification.permission === "denied") {
          toast.error("Notifications are blocked for this site in your browser settings");
          return;
        }
        await subscribe(apiClient, subscribeUrl);
        setSubscribed(true);
        toast.success("Push notifications enabled");
      }
    } catch (e) {
      console.error("Push subscription failed:", e);
      if (e?.name === "NotAllowedError" || Notification.permission === "denied") {
        toast.error("Notifications are blocked for this site in your browser settings");
      } else if (e?.name === "NotSupportedError") {
        toast.error("Push notifications aren't supported in this browser");
      } else {
        toast.error(e?.message ? `Couldn't update notification settings: ${e.message}` : "Couldn't update notification settings");
      }
    } finally {
      setBusy(false);
    }
  };

  const className = variant === "nav" ? "nav-link w-full" : "btn-ghost flex items-center gap-2";

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy || subscribed === null}
      data-testid={`${testidPrefix}-toggle-btn`}
      className={className}
    >
      {subscribed ? <Bell size={16} strokeWidth={1.5} /> : <BellOff size={16} strokeWidth={1.5} />}
      <span>{subscribed ? "Notifications on" : "Enable notifications"}</span>
    </button>
  );
}
