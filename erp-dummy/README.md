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

## Why this is a separate service, not a module in `backend/`

This mirrors a real integration boundary: the ERP runs independently with its
own credentials, database, API validation and idempotency receipts. Restarting
or losing access to EKEEKRTA does not expose the ERP dashboard token.
