# Vercel deployment

EKEEKRTA uses three separate Vercel projects. The self-hosted Jitsi/Jibri stack and private recording/model workers are deliberately not deployed to Vercel.

## Current public services

| Service | Source | Stable URL |
| --- | --- | --- |
| Portal | `frontend/` | <https://ekeekrta.vercel.app> |
| Application API | `backend/` | <https://smart-virtual-lms-backend-gules.vercel.app> |
| ERP sandbox | `erp-dummy/` | <https://ekeekrta-erp-sandbox.vercel.app> |

These are portfolio/demo deployments. Protected pages still require provisioned accounts, and the ERP dashboard requires its token.

## Deployment order

Deploy dependencies before consumers:

1. ERP sandbox when its API or attendance/notification UI changes;
2. application backend;
3. frontend; and
4. public verification.

Do not promote a frontend that expects backend routes which have not been deployed.

## Required backend settings

Configure production values in the backend Vercel project, never in Git:

| Variable | Requirement |
| --- | --- |
| `DATABASE_URL` | Hosted PostgreSQL connection string with required SSL options |
| `SECRET_KEY` | Unique random value of at least 32 characters |
| `ALLOWED_ORIGINS` | Exact HTTPS frontend origin(s), no wildcard |
| `PASSWORD_RESET_BASE_URL` | `https://ekeekrta.vercel.app` when SMTP is enabled |
| `VIDEO_PROVIDER` | Explicit provider such as `jaas`; no silent public fallback |
| `JAAS_APP_ID`, `JAAS_API_KEY_ID`, `JAAS_PRIVATE_KEY` | Required only for JaaS; PEM stays backend-only |
| `GOOGLE_CLIENT_ID` | Required only for Google sign-in |
| SMTP variables | Required only for password-recovery delivery |
| Google Drive OAuth variables | Required only for trainer-owned recording folders |
| `CODE_RUNNER_URL` / API key | Required only for programming execution |

Production startup rejects local SQLite, an example/short secret, and wildcard or non-HTTPS CORS origins. FastAPI interactive documentation is disabled in production.

## Required frontend settings

`VITE_API_BASE_URL` must be the stable HTTPS backend address without a trailing slash. Google Picker browser configuration may also use `VITE_GOOGLE_PICKER_API_KEY` and `VITE_GOOGLE_DRIVE_APP_ID`.

Never put a database URL, private key, OAuth client secret, ERP token or mail password in a `VITE_` variable. Vite values are public browser code.

## Required ERP settings

| Variable | Requirement |
| --- | --- |
| `DATABASE_URL` | A database independent from the application database |
| `ERP_API_TOKEN` | Random token of at least 24 characters |
| `ERP_INSTITUTION_ID` | Must match the EKEEKRTA administrator configuration |
| `ERP_NAME` | Display name for the sandbox/institution ERP |
| WhatsApp variables | Optional; require Meta credentials, approved utility template and guardian consent |

## CLI deployment

Authenticate with the Vercel account/team that owns the existing projects:

```powershell
vercel login
vercel whoami
vercel teams ls
```

Deploy the backend and frontend from their project folders:

```powershell
cd backend
vercel deploy --prod --yes

cd ..\frontend
vercel deploy --prod --yes
```

The existing ERP project is configured with `erp-dummy` as its Root Directory. Deploy it from the repository root so that setting remains valid:

```powershell
cd ..
vercel deploy . --project ekeekrta-erp-sandbox --prod --yes
```

If Vercel reports that a configured Root Directory does not exist, the CLI was run from the wrong source level. Do not relink or create a new project until you confirm the intended project, team and environment settings.

## Database changes

The public backend and ERP should use separate PostgreSQL databases. Before a schema-affecting release:

1. identify the exact production database/branch;
2. stop or minimize writes;
3. create and restore-test a backup;
4. run the documented migration/compatibility procedure;
5. deploy backend code;
6. verify tenant counts, ownership and authentication; and
7. deploy the frontend only after API verification.

Reverting application code is not a database rollback.

## Verification after deployment

At minimum verify:

- portal `/login` returns HTTP 200 and loads its current hashed JavaScript bundle;
- backend `/` returns `{"status":"ok","service":"lms-backend"}`;
- a protected route returns 401 without a token rather than 404;
- ERP `/` returns HTTP 200 and the expected current screens;
- institution admin, faculty/trainer and student/learner can sign in;
- cross-role and cross-institution access is denied;
- a database write persists across a new serverless instance; and
- enabled integrations use production URLs rather than `127.0.0.1`.

Provider-specific verification still requires real accounts: a two-person meeting from different networks, Google OAuth/Drive, SMTP delivery, code-runner isolation and WhatsApp template delivery.

## What Vercel does not host here

- self-hosted Jitsi Videobridge or Jibri;
- long-running private recording workers;
- private recording files;
- locally trained speech/OCR/generative model services; or
- the production ERP of an institution.

Those workloads require institution-controlled infrastructure, retention rules, monitoring and capacity testing.
