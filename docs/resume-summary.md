# Resume and interview summary

## One-line description

**EKEEKRTA is a multi-tenant education operations platform that unifies LMS, virtual classroom, attendance, ERP synchronization, university/training workflows and explainable AI-assisted actions.**

## Resume-ready project entry

**EKEEKRTA — Multi-tenant Learning and Institution Operations Platform**

React, Vite, FastAPI, SQLAlchemy, PostgreSQL, JWT, Jitsi/JaaS, Google OAuth/Drive, Vercel

- Designed and built a role-based, multi-tenant platform supporting university and training-institution workflows across accounts, courses, batches, assessments, live classes, attendance, learning materials, progress and certificates.
- Implemented server-enforced tenant, department, course and batch authorization for platform administrators, institution administrators, HODs, faculty/trainers and students/learners.
- Created an independent ERP sandbox and a reviewed synchronization pipeline for user import, course/attendance export, offline attendance, retryable delivery and consent-aware parent absence alerts.
- Developed explainable native-AI foundations including audited command previews, source-grounded teaching drafts, cited course retrieval, CGPA planning, evidence-based student progress insights and faculty-reviewed lecture digests.
- Deployed separate React, FastAPI and ERP services publicly and added automated API, role-boundary, migration, integration and frontend production-build checks.

Use only the bullets you can confidently explain in an interview. Do not describe planned models or unconfigured external integrations as completed production features.

## Short portfolio description

I built EKEEKRTA to investigate a recurring institutional problem: the same academic information is entered into separate LMS, ERP, classroom and reporting systems. The project uses a React portal, FastAPI APIs and tenant-aware relational models to connect these workflows while preserving role and institution boundaries. It supports separate university and training-institution experiences and demonstrates recoverable ERP synchronization, authenticated Jitsi access and human-reviewed local AI workflows.

## Engineering discussion points

### Why is the ERP a separate service?

It represents a real organizational boundary. It has its own database, API token and idempotency records, so the LMS cannot directly read internal ERP tables and an ERP outage does not undo a completed classroom action.

### How is multi-tenancy enforced?

The backend derives the account from a signed token and checks the institution on every protected resource. HOD, course-owner, trainer-assignment and enrollment rules narrow access further. Frontend navigation is never treated as security.

### What makes the AI approach responsible?

Current AI features are bounded and explainable. They use owned rules/data, return sources or evidence, preview mutations and require confirmation. Missing generative, speech, OCR and predictive models are documented as planned instead of being simulated.

### What was a difficult systems problem?

Attendance spans live meeting events, students who never joined, finalized session state and an unreliable external ERP. The design pairs real timestamps, finalizes the complete roster and sends records through a retryable idempotent delivery ledger.

### What would you improve next?

Introduce Alembic migrations, verified institution onboarding, observability, object storage, accessibility testing, isolated code execution, private Jitsi/Jibri load testing and evaluated institution-owned AI models.

## Public links

- Application: <https://ekeekrta.vercel.app>
- Backend health: <https://smart-virtual-lms-backend-gules.vercel.app>
- ERP sandbox: <https://ekeekrta-erp-sandbox.vercel.app>
- Source: <https://github.com/Arlahanmanthrao1/EKEEKRTA>

The public portal requires provisioned accounts for protected dashboards. The ERP sandbox requires its deployment token. This is expected access control, not a broken demo.
