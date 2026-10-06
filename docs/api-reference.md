# API guide

The application API is a FastAPI service. In local development, the generated OpenAPI explorer is available at `http://127.0.0.1:8000/docs`. OpenAPI and interactive docs are intentionally disabled on Vercel production deployments.

This guide describes API families rather than duplicating generated request/response schemas. The router source and local OpenAPI document remain the authoritative contract.

## Authentication

Most routes require a bearer token:

```http
Authorization: Bearer <access-token>
```

Tokens contain account identity; callers do not send a trusted role or institution ID to elevate access. The backend loads the user and applies role, tenant and resource-specific checks.

Common responses:

| Status | Meaning |
| --- | --- |
| `200` / `201` | Successful read or creation |
| `204` | Successful operation with no response body |
| `400` | Invalid state transition or business rule |
| `401` | Missing, invalid or expired authentication |
| `403` | Authenticated but outside the permitted role/resource scope |
| `404` | Resource does not exist or is intentionally hidden from the caller |
| `409` | Duplicate/conflicting resource or idempotency key |
| `422` | Request schema validation failed |
| `503` | Required external/private infrastructure is unavailable |

## Route families

| Prefix | Responsibility | Typical access |
| --- | --- | --- |
| `/auth` | Login, Google identity, password recovery, session profile and role-specific account provisioning | Public configuration/login; protected account creation |
| `/institutions` | Registration, login profile, institution settings, themes, grading and departments/domains | Public registration/profile lookup; institution admin changes |
| `/users` | Tenant directory, profile updates, deletion and semester promotion | Admin; scoped HOD reads |
| `/courses` | Course creation, discovery, credits, enrollment and roster management | Role/resource scoped |
| `/assignments` | Assignment creation, submission lists, student submissions and grading | Faculty/student scoped |
| `/quizzes` | Quiz creation, safe student payload and attempts | Faculty/student scoped |
| `/materials` | Notes, exams and previous-year questions | Admin/faculty create; enrolled users read |
| `/calendar` | Aggregated role-aware calendar events | Authenticated |
| `/schedule` | Scheduled class creation, start and cancellation | Faculty/trainer ownership |
| `/attendance` | Sessions, meeting connection, fullscreen policy, end state, join/leave events and summaries | Membership/ownership scoped |
| `/programming` | Assessments, test-case execution and scored submission | Faculty/student scoped |
| `/training` | Batches, learners, modules, lessons, progress, certificates and analytics | Training-tenant role scoped |
| `/erp` | Per-university configuration, test, user preview/confirmation, sync ledger and retry | Institution admin only |
| `/data-exchange` | University export profiles, source records and usage tracking | University faculty/admin scope |
| `/integrations/google-drive` | Trainer OAuth status, connection, callback, Picker token and folder validation | Authenticated trainer/admin flow |
| `/ai` | Capabilities, typed/voice commands, progress, CGPA planning, content drafts, knowledge search and action review | Role-aware |
| `/ai/lectures` | Private recording metadata, preparation jobs, transcripts, review and publication | Course faculty/admin; published output to enrolled students |
| `/platform` | Cross-tenant summary, institution lifecycle and platform audit | Platform administrator only |

## Authentication examples

Password login:

```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@institution.example",
  "password": "user-supplied-password"
}
```

Read the current session:

```http
GET /auth/me
Authorization: Bearer <access-token>
```

Google login sends a Google ID token to `/auth/google`. The backend verifies its signature, audience and email before matching an existing EKEEKRTA account. It never provisions a role from Google claims.

## AI action pattern

AI-assisted writes use a two-step workflow:

1. create a command/draft and receive an audited preview/action ID;
2. explicitly confirm that action through `/ai/actions/{action_id}/confirm`.

The execution step repeats authorization and state checks. A preview is not proof the caller can still execute after permissions or data change.

## ERP API boundary

The ERP sandbox exposes a separate token-protected namespace under `/api/ekeekrta` for health, user directory, academic results, course sync and attendance sync. It also exposes protected operator endpoints for user entry, offline attendance, academic register and WhatsApp-delivery review.

Do not reuse the EKEEKRTA user JWT as an ERP token. See [ERP integration](erp-integration.md) for payload and idempotency rules.

## API evolution

The current prototype does not use a `/v1` URL prefix. Breaking contract changes should introduce explicit versioning before third-party institutions integrate. Pydantic schemas and integration tests should change in the same commit as router behavior.
