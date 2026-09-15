# EKEEKRTA ERP integration contract

EKEEKRTA connects separately to each institution's ERP. An institution
administrator enters the ERP base URL and API token on **Admin → ERP
Integration**. The token is encrypted at rest and never returned by the API.

## ERP endpoints

The institution ERP must expose these HTTPS endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/ekeekrta/health` | Verify credentials and availability |
| `GET` | `/api/ekeekrta/users` | Export ERP student, faculty, and HOD master data to EKEEKRTA |
| `GET` | `/api/ekeekrta/students` | Legacy student-only export supported during migration |
| `GET` | `/api/ekeekrta/results/{institutional_id}` | Export one student's official CGPA and credit summary for a requested roadmap refresh |
| `POST` | `/api/ekeekrta/courses/sync` | Upsert a course |
| `POST` | `/api/ekeekrta/attendance/sync` | Upsert one student's attendance for one class session |

Every request includes an `Authorization: Bearer <institution ERP token>`
header. Outbound course and attendance requests also include:

- `Idempotency-Key: ekeekrta-<sync-event-id>-<record-revision>`
- `Content-Type: application/json`

The ERP should authenticate the token, use the idempotency key to make repeated
requests safe, upsert the supplied record, and return any `2xx` response only
after the record is accepted. Redirects are not followed.

## Identifier rules

- `student.institutional_id` is the official roll, admission, or registration
  number shared by EKEEKRTA and the ERP. Email is not the primary match key.
- `course.faculty.institutional_id` is the official employee number supplied
  when the faculty or HOD account is created.
- `course.code` is the institution's course identifier.
- `class_session.ekeekrta_id` plus `student.institutional_id` identifies an
  attendance record.
- `institution.external_id` is the optional ERP-side institution code entered
  by the administrator.

## Delivery and recovery

Student, faculty, and HOD identities can originate in the ERP. An EKEEKRTA
administrator selects **Preview ERP users** to retrieve the directory. The
preview marks every record as Create, Update, or Skip and shows the reason for
each skipped record. No account changes are made until the same administrator
selects **Confirm user import** within 15 minutes. If either system changes in
the meantime, confirmation is rejected and a new preview is required.

Accounts are matched by official registration/employee number inside the
institution. New departments in valid records are created automatically;
student cohort fields are updated and matching compulsory courses are enrolled.
Faculty and HOD records receive only their staff role and department. ERP admin
records, domain mismatches, email conflicts, duplicate records, and attempts to
change an existing role are skipped for manual review. Passwords never cross
the ERP boundary: imported accounts use verified institution Google sign-in.

Academic results remain ERP-owned. The protected result endpoint returns only
the record matching the requested official ID and contains current CGPA,
completed credits, remaining credits, and the ERP grading-scale maximum.
EKEEKRTA rejects a grading-scale mismatch and never writes a projected result
back to the ERP.

The user export body is:

```json
{
  "institution_id": "COLLEGE-ERP-CODE",
  "users": [
    {
      "role": "student",
      "institutional_id": "26CS001",
      "name": "Student name",
      "email": "student@institution.edu",
      "department": "Computer Science",
      "program": "B.Tech",
      "batch": "2026-2030",
      "semester_number": 1,
      "section": "A"
    },
    {
      "role": "faculty",
      "institutional_id": "EMP042",
      "name": "Faculty name",
      "email": "faculty@institution.edu",
      "department": "Computer Science"
    }
  ]
}
```

Course creation and meeting attendance changes trigger automatic best-effort
delivery back to the ERP. A failed ERP call never rolls back the original
EKEEKRTA action. Instead, the event is stored in the institution's delivery
ledger with its HTTP status and can be retried by an administrator.

The **Sync courses & attendance** action creates or refreshes outbound events
for real course and attendance records. User imports are intentionally separate
and always use the reviewed role-based import above. Each request
delivers at most 25 waiting events so it remains safe on serverless hosting;
**Retry waiting** sends the next batch. No sample records are created.

## Example attendance body

```json
{
  "event": "attendance.upsert",
  "institution": {
    "ekeekrta_id": 12,
    "external_id": "COLLEGE-ERP-CODE",
    "name": "Institution name",
    "email_domain": "institution.edu"
  },
  "student": {
    "ekeekrta_id": 240,
    "institutional_id": "26CS001",
    "email": "student@institution.edu",
    "name": "Student name"
  },
  "course": {
    "ekeekrta_id": 81,
    "code": "CS301",
    "name": "Course name"
  },
  "class_session": {
    "ekeekrta_id": 92,
    "scheduled_at": "2026-09-05T09:00:00+00:00",
    "ended_at": "2026-09-05T10:00:00+00:00"
  },
  "attendance": {
    "ekeekrta_id": 510,
    "duration_minutes": 51.25,
    "present": true
  },
  "occurred_at": "2026-09-05T10:00:10+00:00"
}
```

Production endpoints must use a public HTTPS hostname. Private and reserved
IP-address URLs are rejected to protect the backend from server-side request
forgery. `http://localhost` and `http://127.0.0.1` are accepted only by a local,
non-Vercel backend so the ERP sandbox can be tested on one computer.
