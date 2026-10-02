# College ERP Sandbox

A separate, authenticated ERP service for demonstrating EKEEKRTA integration
when a college does not provide access to its real ERP. It has its own database
and can be deployed independently. It does not create seeded or fabricated
records: users, courses and attendance appear only after an administrator enters
or synchronizes real records. Student, faculty, and HOD master records are
entered in this ERP and reviewed before import into EKEEKRTA; course and meeting
attendance records flow back to the ERP.

Public sandbox: `https://ekeekrta-erp-sandbox.vercel.app`

## Setup

```powershell
Copy-Item .env.example .env
..\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 9000
```

Before starting, edit `.env`:

- Set `ERP_API_TOKEN` to a long random secret.
- Set `ERP_INSTITUTION_ID` to a short code such as `HITAM`.
- Keep SQLite for local testing. Use a separate hosted PostgreSQL database for
  a public deployment.

Open `http://localhost:9000` and enter the ERP token. The protected dashboard
shows users, courses and attendance and refreshes every five seconds. Use
**Add User** to create an ERP student, faculty member, or HOD. Students require
the official roll number, college email, department, programme, batch, semester
and section. Staff require an official employee number, email, and department.

## Connect EKEEKRTA

In **EKEEKRTA Admin → ERP Integration**, enter:

- ERP base URL: use `http://127.0.0.1:9000` while both services run locally.
  Production deployments require a public HTTPS address.
- Institution ID in ERP: the same value as `ERP_INSTITUTION_ID`.
- ERP API token: the same value as `ERP_API_TOKEN`.

Save, select **Import ERP user directory**, test the connection, enable the
connection and run **Preview ERP users**. Review every Create, Update, and Skip
decision, then select **Confirm user import**. Courses and meeting attendance can be
sent in the opposite direction using their corresponding selections. The REST contract is documented in
[`docs/erp-integration.md`](../docs/erp-integration.md).

The ERP dashboard also has an **Academic Results** screen for a registered
student's official CGPA, completed credits, remaining credits, and grading
scale. EKEEKRTA reads one matching record through the protected
`GET /api/ekeekrta/results/{institutional_id}` contract only when that student
requests a roadmap refresh. Results are not seeded, and the student identity
must exist in the ERP before a result can be saved.

The **Academic Register** screen follows the legacy HITAM-style subject-by-date
layout. Select a student to see the courses matching that student's department,
programme, batch, semester and section. Each date cell is calculated from real
online meeting attendance synchronized by EKEEKRTA and finalized offline class
attendance entered in the ERP (`P` for present and `A` for absent);
multiple meetings on the same date are shown as multiple period marks. The
register can be printed or exported as CSV. **Course Directory** remains a
separate screen for synchronized course metadata.

## Parent WhatsApp absence alerts

The ERP can send one official WhatsApp template message when a finalized class
marks a student absent. It never sends on a temporary disconnect: EKEEKRTA first
ends the class, finalizes every enrolled learner (including learners who never
joined), and then synchronizes the final record. Duplicate attendance revisions
reuse the same notification log and cannot message the parent twice.

This integration uses Meta's official WhatsApp Cloud API. Before enabling it:

1. Complete the [WhatsApp Cloud API setup](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
   in a Meta business app and add the institution's sending number.
2. Create and obtain approval for a **Utility** message template named
   `class_absence_alert` (or change the configured name). Suggested body:

   ```text
   Attendance alert: {{1}} was marked absent for {{2}} on {{3}}.
   Recorded attendance: {{4}} minutes. - {{5}}
   ```

   The variables are student name, course, class date/time, attended minutes,
   and institution/ERP name. See Meta's
   [template-message documentation](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates/).
3. Add the current Graph API version, Phone Number ID and access token to the
   ERP environment. Use a short-lived test token only for development and a
   properly managed system-user token for production.
4. Record the parent's international WhatsApp number (for example,
   `+919876543210`) and explicit consent in **Add User**. No message is sent
   without both values.

Configuration:

```dotenv
WHATSAPP_NOTIFICATIONS_ENABLED=true
WHATSAPP_GRAPH_API_VERSION=vXX.X
WHATSAPP_PHONE_NUMBER_ID=your-meta-phone-number-id
WHATSAPP_ACCESS_TOKEN=your-secret-meta-access-token
WHATSAPP_ABSENCE_TEMPLATE_NAME=class_absence_alert
WHATSAPP_TEMPLATE_LANGUAGE=en_US
WHATSAPP_REQUEST_TIMEOUT_SECONDS=10
WHATSAPP_MAX_ATTEMPTS=3
```

Keep the access token only in `erp-dummy/.env` locally or the deployment's
encrypted environment settings. The **WhatsApp Alerts** ERP page shows masked
phone numbers, delivery status and safe retry controls; it never returns the
access token to the browser.

### Offline classroom attendance

Faculty-entered physical classes use the same alert policy as online meetings:

1. Register the faculty member and students in the ERP.
2. Synchronize the course from EKEEKRTA so the ERP has its assigned faculty and cohort rules.
3. Open **Mark Offline Attendance**, then select the course, date, duration and assigned faculty.
4. Mark every learner present or absent and finalize the class.

The ERP validates the complete course roster and assigned faculty before
accepting the submission. Finalized offline records appear in the Academic
Register and attendance reports. Every absent learner with a consented parent
number enters the same deduplicated WhatsApp template workflow. Reusing a
submission identifier is rejected, preventing duplicate attendance and alerts.

## Why this is a separate service, not a module in `backend/`

This mirrors a real integration boundary: the ERP runs independently with its
own credentials, database, API validation and idempotency receipts. Restarting
or losing access to EKEEKRTA does not expose the ERP dashboard token.
