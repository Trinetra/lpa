# Kalpana — Studio Ledger (Dance Teacher Billing)

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
- JWT login + `me` + refresh + logout (cookies + Bearer)
- Student CRUD with photo upload/serve (blob via `AuthImage`)
- Class logging with per-class rate override, auto-amount
- Payment CRUD
- Per-student summary (billed/paid/due/hours/classes)
- Dashboard (totals + outstanding by student + recent classes)
- Invoice generation → PDF (ReportLab, styled) + public share link + shared invoice view
- Cascade delete of classes/payments when student removed
- Admin auto-seeded on startup

### Test Results
- 33/34 backend E2E checks pass (1 test-script bug — expected `.user` wrapper).
- Frontend renders correctly, login → dashboard flow verified via screenshots.

## Backlog / Next Actions
- **P1** Edit class log (currently delete-only); toggle "paid class" flag on individual classes.
- **P1** Bulk actions (mark all classes in date range as invoiced).
- **P2** Calendar view (deferred by user).
- **P2** Online payment collection (Stripe/Razorpay).
- **P2** WhatsApp/Email invoice send button (Resend/Twilio).
- **P3** Multi-teacher support / studio mode.
- **P3** Charts: monthly earnings, hours per student.

## Credentials
See `/app/memory/test_credentials.md`.
