// Minimal service worker for Web Push — shows a notification for whatever
// {title, body, url} payload the backend sent, and routes a click to that
// url (used by both the teacher app and the student portal, same origin).
self.addEventListener("push", (event) => {
  let data = { title: "Notification", body: "", url: "/" };
  try {
    data = { ...data, ...event.data.json() };
  } catch {
    // ignore malformed payloads
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icon-192.png",
      data: { url: data.url },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        if ("navigate" in client) {
          try {
            client.navigate(url);
          } catch {
            // ignore — fall through to focus() below regardless
          }
        }
        return "focus" in client ? client.focus() : undefined;
      }
      return clients.openWindow(url);
    })
  );
});
