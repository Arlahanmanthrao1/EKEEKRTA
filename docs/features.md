# Feature status

This matrix is the source of truth for what can be demonstrated from the repository. “Implemented” means code and a workflow exist; it does not mean the feature has passed an institutional production audit.

## Identity and institution management

| Feature | Status | Notes |
| --- | --- | --- |
| Institution registration | Implemented | University or training-institution profile plus first administrator |
| Institution branding | Implemented | Name, hosted logo, light/dark theme and dashboard identity |
| Platform operations portal | Implemented | Institution list, status management, deletion workflow and audit |
| Password authentication | Implemented | JWT sessions with bcrypt password hashing |
| Google Workspace sign-in | Configurable | Verifies Google tokens for pre-provisioned accounts; no automatic role/account creation |
| Password recovery | Configurable | Hashed, expiring, single-use reset tokens; requires SMTP |
| Public ownership verification | Planned | Registration currently needs stronger domain/email approval and abuse controls |

## University workflows

| Feature | Status | Notes |
| --- | --- | --- |
| Departments and HOD scope | Implemented | HOD sees only assigned department faculty, students, courses and attendance |
| Account management | Implemented | Manual student, faculty and HOD creation plus editing/deletion rules |
| Academic/non-academic courses | Implemented | Year/semester/section targeting and course-specific workspaces |
| Semester promotion | Implemented | Administrator-controlled student promotion workflow |
| Faculty course roster | Implemented | Faculty can inspect and remove enrollments only from owned courses |
| University data exchange | Implemented | Reusable column-mapping profiles and exports for external platforms |
| ERP import/export | Configurable | Requires a compatible HTTPS ERP endpoint and API token |

## Training-institution workflows

| Feature | Status | Notes |
| --- | --- | --- |
| Training programs | Implemented | Reusable program definition separate from delivery dates |
| Batches | Implemented | Start/end dates, status, capacity and assigned trainer |
| Learner enrollment | Implemented | Individual and CSV enrollment of existing tenant learners |
| Modules and lessons | Implemented | Ordered curriculum with publish/completion state |
| Batch meetings and attendance | Implemented | Scheduled/live classes linked directly to a batch |
| Progress calculation | Implemented | Uses available stored evidence; categories without records are excluded |
| Certificate eligibility | Implemented | Batch completion, progress and attendance gates with retained snapshot |
| Trainer Drive recording folder | Configurable | Trainer connects a personal Google account and selects a batch folder |
| Training analytics | Implemented | Administrator and trainer scopes |

## Learning management

| Feature | Status | Notes |
| --- | --- | --- |
| Courses and enrollment | Implemented | Tenant-aware browsing and explicit enrollment |
| Assignments | Implemented | Faculty creation, URL-based submission and grading |
| Managed file upload/storage | Planned | Current assignment submission expects a hosted file URL |
| Quizzes | Implemented | Multiple-choice builder and automatic grading; answers hidden before submission |
| Materials | Implemented | Notes, exams and previous-year-question categories |
| Calendar and scheduling | Implemented | Role dashboards and optional faculty class scheduling |
| Programming assessments | Configurable | Test cases, hidden cases and scoring; requires a configured runner |
| Full gamification system | Planned | No production points economy, achievement engine, streak service or ranked leaderboard yet |

## Virtual classroom and attendance

| Feature | Status | Notes |
| --- | --- | --- |
| Jitsi/JaaS iframe classroom | Configurable | Provider/domain and backend signing credentials required |
| Student mic/camera off initially | Implemented | Initial state only; not represented as a permanent restriction |
| Teacher moderator privileges | Implemented | Issued by backend identity checks, never by a UI role selector |
| Audio, screen sharing, hand raise, chat and participants | Implemented through Jitsi | In-meeting controls remain partly Jitsi UI |
| Start now and scheduled class | Implemented | Course and batch flows |
| Fullscreen policy and end-for-all | Implemented | Faculty controls with persisted session state |
| Real-duration attendance | Implemented | Paired authenticated join/leave timestamps and configurable threshold |
| Completed class history | Implemented | Ended sessions leave the active hero and remain in history |
| Production self-hosted Jitsi/Jibri | Planned deployment | Configuration guidance exists; no capacity claim without load testing |
| Automatic recording | Foundation | Self-hosted Jibri and private storage/worker are required |

## ERP and communication

| Feature | Status | Notes |
| --- | --- | --- |
| Independent ERP sandbox | Implemented | Separate FastAPI app, database, token and deployment |
| Reviewed user-directory import | Implemented | Matches official IDs; excludes ERP admins and conflicting role changes |
| Course and attendance synchronization | Implemented | Durable delivery ledger with retry |
| Academic register | Implemented | Online and finalized offline periods by subject/date |
| Offline-class attendance | Implemented | Complete roster validation and assigned-faculty checks |
| Parent absence alerts | Configurable | Meta template, sender credentials, guardian number and explicit consent required |

## Native AI

| Capability | Status | Honest boundary |
| --- | --- | --- |
| Role-aware typed commands | Implemented | Locally trained deterministic intent classifier over owned phrases |
| Audited preview/confirmation workflow | Implemented | Write operations are not silently executed |
| Source-grounded assignment/quiz drafts | Implemented | Uses faculty-provided notes; does not claim open-ended generation |
| Target-CGPA roadmap | Implemented | Transparent projection, scenarios and stored checkpoints; not an official result |
| Course question assistant | Implemented | Lexical retrieval with exact citations and refusal when evidence is weak |
| Lecture digest | Implemented foundation | Extractive draft from verified text, followed by faculty review/publication |
| Progress/risk insights | Implemented foundation | Explainable stored-evidence thresholds, not predictive machine learning |
| Voice-controlled UI | Foundation | Recording and executable contract exist; trained institution-owned model is not bundled |
| Recording preprocessing | Foundation | Private worker can prepare audio/frames; automatic transcription depends on reviewed local models |
| Handwriting recognition/assessment | Planned | No model bundled |
| Automatic free-resource recommendation | Planned | No web recommendation model/service bundled |
| Custom generative language model | Planned | No external model fallback and no hidden claim of generation |
| Autonomous institutional recommendations | Planned | Current actions retain human review and bounded authority |
