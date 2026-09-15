# AI-Powered Smart Virtual LMS — backend

FastAPI backend scaffold for the Phase 1 feature set: authentication,
courses, attendance, assignments, and quizzes.

## Setup

For the video classroom, follow [JaaS Dev setup](JAAS_SETUP.md). JaaS credentials
must be supplied on the backend before meetings can connect.

```bash
python3 -m venv venv
source venv/bin/activate          # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Visit `http://localhost:8000/docs` for interactive API docs (Swagger UI) —
FastAPI generates this automatically from the routes and schemas.

## What's implemented

| Module | Endpoints | Notes |
|---|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` | Registration is restricted to the `ALLOWED_EMAIL_DOMAIN` set in `.env`. Returns a JWT on login. |
| Courses | `POST/GET /courses`, `POST /courses/{id}/enroll` | Faculty/admin create courses, students enroll. |
| Attendance | `POST /attendance/event`, `GET /attendance/{course_id}/{student_id}` | Authenticated Jitsi join/leave events are paired into real elapsed durations and synchronized to the ERP. |
| Live sessions | `POST /attendance/sessions`, `PATCH /attendance/sessions/{id}/fullscreen`, `PATCH /attendance/sessions/{id}/end` | Faculty can control fullscreen policy and durably end a class for every connected student. |
| Assignments | `POST /assignments`, `GET /assignments/course/{id}`, `POST /assignments/submit`, `POST /assignments/submissions/{id}/grade` | Basic submit/grade flow. File upload itself isn't wired up yet — `file_url` currently expects a pre-uploaded URL (e.g. from S3). |
| Quizzes | `POST /quizzes`, `POST /quizzes/attempt` | Auto-grades multiple-choice attempts. |
| Native AI | `POST /ai/commands`, `POST /ai/actions/{id}/confirm`, `GET /ai/actions` | EKEEKRTA-owned intent classification, permission-scoped previews, explicit confirmation, progress insights, and audited actions. No external AI model/API is used. |

## Roles

Faculty can open **My Courses → Manage enrolled students** to review and remove
enrollments. `GET /courses/{course_id}/students` and
`DELETE /courses/{course_id}/students/{student_id}` require the faculty owner of
that course. Removal requires confirmation in the UI and preserves the student
account, other enrollments, assignment submissions, quiz attempts, and attendance
history. It is not a ban: existing self-enrollment remains available, and removal
does not disconnect an ongoing video call. No database migration is needed.

`POST /auth/register` is the administrator-only manual student-registration
option. It remains available when ERP import is enabled; administrators should
use the same official registration/roll number so a later ERP import updates the
existing profile rather than creating a duplicate. ERP-imported students sign in
through their verified institution Google account.
Administrators can also use **Create faculty** in their dashboard. It calls
`POST /auth/register-faculty`, which requires administrator access and creates only
faculty accounts using the same domain and password validation. Faculty use the
same login page and are directed to their teaching dashboard. Neither endpoint
accepts a client-selected role or creates HOD/admin accounts.
Existing accounts are unchanged; an initial administrator must be provisioned locally by an authorized
operator. Registration checks the configured domain, not mailbox ownership.
Further security review is needed before public deployment.

Four roles live on the `User` model: `student`, `faculty`, `hod`, `admin`.
Route access is enforced with the `require_roles(...)` dependency in
`app/core/deps.py` — see any router for examples.

## Database

Defaults to SQLite (`lms.db`, created automatically) so the project runs
with zero setup. To switch to Postgres, just change `DATABASE_URL` in
`.env` to something like:

```
DATABASE_URL=postgresql://user:password@localhost:5432/lms
```

and add `psycopg2-binary` to `requirements.txt`. No code changes needed —
SQLAlchemy handles the rest.

Tables are created directly from the models on startup
(`Base.metadata.create_all`). That's fine for a student project; if you
need to evolve the schema without losing data later, introduce Alembic.

## Not yet built (Phase 2 — see the AI-services module in the diagram)

- Lecture recording upload/storage
- Whisper transcription + LLM summarization pipeline
- Plagiarism similarity checker (`plagiarism_score` field already exists
  on `Submission`, ready to be populated)
- At-risk student scoring
- Staff analytics aggregation endpoints

## ERP integration

Each institution administrator configures its own real ERP HTTPS endpoint and
API token from **Admin → ERP Integration**. Student, faculty, and HOD master
records are pulled from the ERP, previewed, and explicitly confirmed by the
administrator. Accounts are matched by official registration/employee number;
ERP administrators and conflicting role changes are never imported. Courses and
actual meeting attendance are sent back through a durable institution-scoped
delivery ledger, so an ERP outage never rolls back an EKEEKRTA action and failed
outbound records can be retried.

The ERP-side REST endpoints and payloads are documented in
[`docs/erp-integration.md`](../docs/erp-integration.md). The independent
`erp-dummy/` Sandbox implements the same protected contract for demonstrations.

## EKEEKRTA Native AI v1

Every role has an **AI Assistant** page, but only receives actions already
permitted by that role. Faculty can schedule a class, prepare an assignment,
prepare a non-published quiz outline, and inspect students in their course scope.
HODs see only department-scoped progress, students see only their own progress,
and administrators can review institution-wide progress or confirm an ERP
student import.

The intent model is trained at startup from EKEEKRTA-owned command phrases in
`app/native_ai/intent_model.py`. It performs no network inference and loads no
external model weights. Every write starts as a preview and is executed only
after the requesting user confirms it; role, institution, course, and student
access are checked again at execution time. Quiz outlines are never published
with invented answers. User corrections are stored for a future reviewed
training run only after explicit consent. Passwords, private keys, and API tokens
are rejected from command text.

Stage 2A adds administrator/faculty course-structure commands, administrator
department creation, reviewed CSV account creation, and an institution-wide AI
governance view. The CSV flow accepts student and faculty records only, validates
all rows before creating anything, and caps each request at 250 accounts. It does
not accept or store passwords: created accounts use their pre-provisioned,
verified institution Google identity. Administrators may audit every AI action
inside their institution and reject a pending request, but cannot silently
confirm a faculty member's action on that person's behalf.

### Native AI Stage 2B: source-grounded teaching drafts

Faculty can use the AI Assistant's lesson-note content studio to generate an
assignment structure or an MCQ draft from notes they provide. The EKEEKRTA Local
Content Draft Engine is deterministic and runs inside the backend; it does not
call an external model or inference API. Quiz answers and distractors are taken
only from terms present in the supplied notes, and the preview includes each
source statement so the faculty member can verify it.

`POST /ai/content-drafts` creates an audited review draft only. The owning
faculty member must explicitly confirm the action before an assignment, quiz,
or answer key is stored in the course. Existing student quiz responses continue
to omit `correct_option`, so draft answers never enter the student quiz payload.

### Student Progress Intelligence Stage 1: target CGPA planner

Students can use the AI Assistant's Target CGPA Planner with values from their
latest official record: grading scale, current and target CGPA, completed and
remaining credits, semesters remaining, and weekly study time. The planner
calculates the average SGPA required across remaining credits, maximum possible
final CGPA, feasibility status, and semester checkpoints. It then ranks only
the student's enrolled courses using real EKEEKRTA attendance, missing work,
assignment, quiz, and programming evidence and allocates the available weekly
study time accordingly.

`POST /ai/cgpa-plan` is student-only and stores an institution-scoped audited
projection. It does not modify grades, call an external model, or claim to be an
official result. Student-entered CGPA values are planning inputs; the institution
ERP remains the source of official academic results.

### Student Progress Intelligence Stage 2: persistent academic planning

Stage 2 saves one private CGPA goal per student and keeps up to 24 dated
checkpoints. Administrators configure the institution grading-scale maximum and
passing grade point in Settings. Faculty configure official credits on each
course; existing courses can be updated without recreation.

Students may enter expected grade points for their enrolled courses that have
official credits. The planner shows the credit-weighted CGPA after that scenario
without writing a mark or promising an outcome. `GET /ai/cgpa-goal` restores the
saved goal, while `POST /ai/cgpa-goal/refresh-erp` reads the matching official-ID
result from the verified ERP connection. An ERP/institution scale mismatch fails
closed and requires administrator review. All projections remain local, audited,
student-only, and use no external AI model.

### Native AI Stage 3: course knowledge assistant

Faculty and administrators can add approved text sources to a course knowledge
base and decide whether each source is visible to enrolled students. The local
retrieval engine searches only published sources in the authenticated user's
course and institution scope. It returns exact passages with source titles; if
the evidence is weak or absent it refuses to guess. Sources can be unpublished
or archived without deleting the AI audit trail.

`POST /ai/course-question` stores the question and cited result in the requester's
private, audited AI history. The implementation is an explainable lexical
retrieval baseline: it uses no network service, external model weights, or hidden
training data. It is intentionally not presented as a generative language model.

### Native AI Stage 4 foundation: completed-class lecture digests

After a class has actually ended, its authorized faculty member or institution
administrator can submit a verified text transcript through the course page or
`POST /ai/lectures/sessions/{id}/transcript`. The local extractive engine selects
real transcript statements for a summary and numbered notes, then leaves them
as a private draft. Faculty explicitly publish through
`PATCH /ai/lectures/{id}/review` to approve individual excerpts and topic labels,
then `PATCH /ai/lectures/{id}/publication`. Direct publication of an unreviewed
draft is refused. Enrolled students receive only the
reviewed digest, never the raw transcript. Publishing also creates a course
knowledge source for the Stage 3 cited-question assistant. Unpublishing removes
both student and assistant access. The audit trail records preparation and
publication changes without copying the transcript into audit details.

This is **not automatic recording or automatic speech-to-text**. Current JaaS
tokens disable recording/transcription, and no self-hosted Jibri or native
speech model is configured. The form labels its input `faculty_text`; browser
callers cannot mark it as an automatic transcript. Do not paste confidential
student information into a transcript. The chosen transcript statements are
extractive, not a generative or semantic summary, and require human review.
Automatic recorded-audio ingestion requires the separately planned self-hosted
Jitsi/Jibri deployment, consent and retention policy, secure storage, and a
locally trained speech model. Official Jitsi documentation says Jibri requires
one recording system per simultaneous meeting and recommends running it apart
from a resource-constrained main server.

## Security notes before this goes anywhere near production

- Set a real, random `SECRET_KEY` in `.env` (don't commit it)
- Tighten CORS `allow_origins` in `app/main.py` to your actual frontend URL
- Add rate limiting on `/auth/login`
