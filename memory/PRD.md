# Lakshmi — Studio Ledger (Dance Teacher Billing)

## Original Problem Statement
Client is a dance teacher with ~10 online students. She has no way to bill students, track who paid and who hasn't. Needs a small web/mobile app to:
- Maintain a roster (name, phone, email, photo, description, level, joined date)
- Set per-student hourly rate (INR)
- Log completed classes (student + hours + date + notes)
- Track payments and outstanding balances
- Optionally sync with calendar (deferred)

## User Choices (Confirmed)
- **Auth**: JWT-based custom login
- **Currency**: INR (₹)
- **Payments**: Manual entry + shareable PDF invoices (Stripe/Razorpay deferred to later phase)
- **Photos**: Yes, via Emergent Object Storage
- **Calendar**: No — simple class logging only

## Personas
1. **Dance teacher (admin)** — single user, manages roster, logs classes, records payments, sends invoices.
2. **Student (recipient)** — receives shareable invoice link/PDF (public, read-only).

## Architecture
- **Backend**: FastAPI + MongoDB (motor). JWT (bcrypt-hashed passwords, httpOnly cookies + Bearer fallback). ReportLab for PDF generation. Emergent Object Storage for photos.
- **Frontend**: React 19 + React Router 7 + Tailwind + Shadcn/UI + Sonner (toasts).
- **Design**: "Earthy Editorial" — Playfair Display + Outfit fonts, warm charcoal/terracotta palette (per `/app/design_guidelines.json`).

## Data Model
- `users` (email, password_hash, name, role)
- `students` (owner_id, name, email, phone, level, joined_on, description, hourly_rate, photo_path)
- `classes` (owner_id, student_id, hours, class_date, rate, amount, notes)
- `payments` (owner_id, student_id, amount, paid_on, method, notes)
- `invoices` (invoice_id, share_token, owner_id, student_snapshot, classes, payments, summary, period)
- `files` (storage_path, user_id, content_type, is_deleted)

## Implemented (2026-02)
- JWT login + `me` + refresh + logout (cookies SameSite=None/Secure + Bearer fallback for iframe)
- **Password lifecycle**: `/auth/change-password` (authenticated), `/auth/forgot-password` → emails a signed reset link via Resend, `/auth/reset-password` consumes single-use token (1-hour TTL, auto-expiring via Mongo TTL index)
- **Studio Profile**: `/api/profile` GET/PATCH — studio_name, teacher_name, contact_phone, contact_upi, contact_email, logo_path. Empty strings clear fields. Settings page in UI with logo upload + change-password card.
- Student CRUD with photo upload/serve
- Class logging + edit + delete (mobile-responsive row)
- Payment CRUD (mobile-responsive row)
- Per-student summary + dashboard totals + outstanding by student + recent classes
- Invoice generation with **studio profile snapshot** — historical invoices retain their branding even if profile later changes
- Invoice PDF (ReportLab) with logo + studio name + "Pay to" UPI line
- Shared invoice page + public logo endpoint (`/invoices/share/{token}/logo`)
- Email invoice (Resend) + WhatsApp deep-link
- Delete invoices
- Charts: monthly earnings, hours, per-student billing/hours share (Recharts)
- Kalpana → **Lakshmi** rename across UI, PDF, email templates
- Auto-migrate admin doc on startup (rename email + password + name to match `.env`)
- Admin credentials: **lpathreya@gmail.com / prashanth**

### Test Results
- 33/34 backend E2E checks pass (1 test-script bug — expected `.user` wrapper).
- PATCH class verified: 3h × ₹600 override = ₹1,800.
- Email send verified: 200 OK with email_id from proxy.
- Charts UI verified via screenshots (multi-month data seeded).

## Backlog / Next Actions
- **P2** Online payment collection (Stripe/Razorpay) — record + mark invoice paid.
- **P2** Calendar view (deferred by user).
- **P3** Multi-teacher / studio mode.
- **P3** SMS reminders via Twilio, bulk WhatsApp broadcast.
- **P3** Recurring class templates (auto-log same class weekly).

## Credentials
See `/app/memory/test_credentials.md`.
