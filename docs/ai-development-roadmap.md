# EKEEKRTA owned-AI development roadmap

EKEEKRTA does not call an external inference API. Every learned feature must use
institution-approved data, immutable local model versions, held-out evaluation,
role-scoped access, an audit event and a human override. A feature remains
labelled **experimental** until it passes its acceptance gate with real data.

## Delivery order

1. **Handwriting recognition and assessment.** Collect consented page images,
   line/word transcripts, language/script labels, rubric scores and reviewer
   disagreements. Build handwriting recognition first; rubric assistance comes
   only after transcription quality passes per-script tests. Faculty see the
   source crop, confidence and editable result.
2. **Voice control (application pipeline built; model training pending).** The
   browser captures a user-initiated short recording, a private EKEEKRTA
   executable returns text/confidence, and sufficiently confident text enters
   the existing role checks and preview/confirmation flow. Audio is deleted
   after inference and there is no browser/cloud fallback. Collect consented
   commands covering roles, accents, languages, noise and device types; evaluate
   speech and intent separately before configuring the executable.
   The required recording format, manifest and acceptance gate are defined in
   [`voice-dataset-spec.md`](voice-dataset-spec.md).
3. **Resource recommendation.** Create an approved catalogue of free/licensed
   resources with URL, publisher, license, course outcome, language and review
   date. Retrieval may rank only allow-listed sources; it must check link health
   and display why each item was recommended.
4. **Predictive student-support model.** Use time-correct attendance and
   assessment features without protected attributes. Split by student and term,
   compare against the transparent rules baseline, calibrate probabilities, test
   subgroup false-alert rates and prevent the score from making automatic
   disciplinary or grading decisions.
5. **Institutional recommendations.** Aggregate only authorized metrics, attach
   evidence and uncertainty, and generate reviewable proposals. The system must
   not change accounts, curriculum, grades or policy without an authorized human.
6. **EKEEKRTA generative language model.** Begin only after governance and
   datasets above are stable. Train a small domain model in stages: tokenizer and
   corpus validation, continued pre-training, instruction tuning, safety tuning,
   retrieval grounding and role-specific evaluation. Generated claims need
   citations when institutional facts are involved.

## Minimum dataset records

Every record must have provenance, consent/licence, institution, language,
creation date, reviewer status and deletion/retention status. Personally
identifying data must be removed unless it is strictly required and explicitly
approved. Training, validation and test splits must not share the same student,
document, course recording or near-duplicate content.

## Release gate for every model

- A frozen model ID and reproducible training configuration.
- A held-out evaluation report with task metrics and subgroup/error analysis.
- Comparison against the current non-ML baseline.
- Confidence calibration and an abstain/insufficient-evidence state.
- Security, privacy, licensing and data-retention review.
- Human review and reversal controls in the product.
- Shadow-mode pilot before any user-facing recommendation.
- Monitoring for drift, false alerts and rollback to the previous model.

No accuracy or capacity claim is valid until the corresponding EKEEKRTA model is
tested against institution-approved held-out data.
