# EKEEKRTA documentation

This directory separates product overview, development setup, architecture, operational guidance, and research/model contracts. Start with the first four documents if you are reviewing the repository for engineering work or an interview.

## Start here

| Document | Purpose |
| --- | --- |
| [Architecture](architecture.md) | Components, boundaries, data flows and design decisions |
| [Feature status](features.md) | Implemented, configurable, foundation-only and planned capabilities |
| [Local development](local-development.md) | Reproducible Windows and cross-platform setup |
| [Development life cycle](development-lifecycle.md) | How requirements move from an idea to a verified release |
| [Security and privacy](security-and-privacy.md) | Trust boundaries, controls, known gaps and release gates |
| [Resume summary](resume-summary.md) | Concise portfolio description and interview talking points |

## Technical references

| Document | Purpose |
| --- | --- |
| [API guide](api-reference.md) | API families, authentication and local discovery |
| [Data model](db-schema.md) | Main entities and relationships |
| [ERP integration](erp-integration.md) | Import/export contract and retry behavior |
| [University data exchange](university-data-exchange.md) | Reusable export-profile workflow |
| [Training batch workflow](training-batch-workflow.md) | Programs, batches, modules, progress and certificates |

## Native AI and private model work

| Document | Purpose |
| --- | --- |
| [AI development roadmap](ai-development-roadmap.md) | Planned delivery sequence and release gates |
| [Voice model contract](ai-voice-model-contract.md) | Private executable interface for short voice commands |
| [Stage 4 model contract](ai-stage4-model-contract.md) | Local speech/OCR inputs, outputs and human review |
| [Voice dataset specification](voice-dataset-spec.md) | Audio, metadata, consent and acceptance requirements |
| [Voice dataset collection guide](voice-dataset-collection-guide.md) | Operational collection and validation procedure |

## Operations and deployment

- [Institution onboarding](../INSTITUTION_SETUP.md)
- [Platform-operator runbook](../EKEEKRTA_OPERATIONS.md)
- [Google sign-in setup](../GOOGLE_SIGN_IN_SETUP.md)
- [JaaS development setup](../backend/JAAS_SETUP.md)
- [Vercel deployment](../VERCEL_DEPLOYMENT.md)
- [Private Jitsi/Jibri plan](../deployment/jitsi/README.md)
- [ERP sandbox](../erp-dummy/README.md)

## Status language used in this repository

- **Implemented:** application code and a user/API flow are present.
- **Configurable:** code is present, but an external account, credentials or private infrastructure is required.
- **Foundation:** safety boundaries, UI, storage or an executable contract exist, but the claimed intelligence/model is not bundled.
- **Planned:** not available as a working product feature.

These labels describe code state, not certification for production use.
