import React from "react";

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto px-6 py-16">
        <div className="uppercase-label mb-2">Pravaaha CFM</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl mb-2">Privacy Policy</h1>
        <p className="text-sm mb-10" style={{ color: "var(--text-muted)" }}>Last updated 26 August 2026</p>

        <div className="space-y-8 text-sm leading-relaxed" style={{ color: "var(--text)" }}>
          <section>
            <h2 className="font-serif-display text-xl mb-2">What this app is</h2>
            <p>
              Pravaaha CFM ("the app") is a private studio-management tool used by Lakshmi Parthasarathy
              Athreya to run her Bharatanatyam teaching practice — scheduling classes, billing students,
              and related studio administration. It is not a public product; access is limited to the
              studio owner, her students (via an invite-only student portal), and anyone she explicitly
              grants access to.
            </p>
          </section>

          <section>
            <h2 className="font-serif-display text-xl mb-2">Information we collect</h2>
            <p className="mb-2">Depending on your relationship with the studio, we may collect:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Contact details you or the studio owner provide: name, email, phone number.</li>
              <li>Class, schedule, and attendance records.</li>
              <li>Billing and payment records (amounts, dates, payment method) — we do not store card or
                bank account numbers; payments are recorded manually or via UPI/bank transfer references.</li>
              <li>Optional content you choose to add: a profile photo, written notes, or a voice recording
                attached to a class.</li>
              <li>Basic technical data needed to operate the app: your login session, and — if you enable
                push notifications — a device token used only to deliver those notifications.</li>
            </ul>
          </section>

          <section>
            <h2 className="font-serif-display text-xl mb-2">How we use this information</h2>
            <p>
              Solely to run the studio: scheduling and reminding you about classes, generating invoices
              and tracking payments, sending studio announcements and event invitations, and — where you've
              opted in — sending push or email notifications about your own classes and dues. We do not
              sell, rent, or use this information for advertising.
            </p>
          </section>

          <section>
            <h2 className="font-serif-display text-xl mb-2">Google Calendar &amp; Drive</h2>
            <p>
              The studio owner may connect a Google account so her weekly class schedule syncs to a
              dedicated Google Calendar, and so an encrypted daily backup of studio data can be stored in
              a folder in her Google Drive. The app requests only the narrow permissions needed for this:
              creating/editing events on a calendar the app itself created, and creating/reading files in
              a Drive folder the app itself created — it cannot see or modify any other calendars, files,
              or folders in that Google account. This connection can be revoked at any time from the app's
              Settings page or directly from the account's Google security settings.
            </p>
          </section>

          <section>
            <h2 className="font-serif-display text-xl mb-2">Other services we use</h2>
            <p className="mb-2">To operate the app, we share the minimum necessary data with:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>Resend</strong> — to send emails (invoices, reminders, announcements, event invitations).</li>
              <li><strong>Zoom</strong> — a class meeting link may be included in calendar events and reminders, where the studio has configured one.</li>
              <li><strong>OpenAI (Whisper)</strong> — only if the studio owner enables it, a class voice recording may be sent for automatic transcription. This is off by default.</li>
              <li>Standard infrastructure providers (hosting, database, file storage) needed to run the app at all.</li>
            </ul>
          </section>

          <section>
            <h2 className="font-serif-display text-xl mb-2">Data retention &amp; deletion</h2>
            <p>
              Records are kept for as long as you're an active student or the studio owner needs them for
              its own record-keeping. You can ask the studio owner to correct or delete your information
              at any time using the contact details below; a student account can also be deactivated,
              which removes it from the active schedule and portal access.
            </p>
          </section>

          <section>
            <h2 className="font-serif-display text-xl mb-2">Contact</h2>
            <p>
              Questions about this policy or your data can be sent to{" "}
              <a href="mailto:lpathreya@gmail.com" style={{ color: "var(--primary)" }}>lpathreya@gmail.com</a>.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
