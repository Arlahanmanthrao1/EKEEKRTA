import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";
import { EmptyState } from "./DashboardShell";
import "../../styles/faculty-course.css";

export const preparationLabel = recording => {
  const job = recording.preparation;
  if (job?.status === "failed") return `processing failed (${job.error_code || "media_preparation_failed"})`;
  if (recording.status === "transcript_draft_ready") return "private transcript and notes draft ready for faculty review";
  if (recording.status === "media_prepared") return "audio and frames prepared; transcription model not connected";
  if (!job) return "recording uploaded; preparation not requested";
  if (job.status === "queued") return "queued for the private institution worker";
  if (job.status === "processing") return "private worker is preparing audio and frames";
  if (job.status === "cancelled") return "preparation cancelled";
  return job.stage.replaceAll("_", " ");
};

export function LectureReviewControls({ lecture, busy, onReview, onEdit, onPublication }) {
  const candidates = lecture.summary.candidate_notes || lecture.summary.notes || [];
  const candidateTopics = lecture.summary.candidate_topics || lecture.summary.topics || [];
  const [selectedNotes, setSelectedNotes] = useState(() => (lecture.summary.notes || []).map(note => note.statement_number));
  const [selectedTopics, setSelectedTopics] = useState(() => lecture.summary.topics || []);
  const sameSelection = (selected, approved) => selected.length === approved.length
    && selected.every(item => approved.includes(item));
  const selectionSaved = sameSelection(selectedNotes, (lecture.summary.notes || []).map(note => note.statement_number))
    && sameSelection(selectedTopics, lecture.summary.topics || []);
  const toggleNote = number => setSelectedNotes(current => current.includes(number)
    ? current.filter(item => item !== number) : [...current, number]);
  const toggleTopic = topic => setSelectedTopics(current => current.includes(topic)
    ? current.filter(item => item !== topic) : [...current, topic]);

  return <div className="lecture-review-controls">
    {lecture.status !== "published" && <>
      <fieldset><legend>Approve transcript statements</legend><p>Exclude anything inaccurate or sensitive. Only selected statements can appear in the published summary and notes.</p>
        {candidates.map(note => <label className="check-row" key={note.statement_number}><input type="checkbox" checked={selectedNotes.includes(note.statement_number)} onChange={() => toggleNote(note.statement_number)} />Statement {note.statement_number}: {note.text}</label>)}
      </fieldset>
      {candidateTopics.length > 0 && <fieldset><legend>Approve topic labels</legend><div className="lecture-topic-options">{candidateTopics.map(topic => <label className="check-row" key={topic}><input type="checkbox" checked={selectedTopics.includes(topic)} onChange={() => toggleTopic(topic)} />{topic}</label>)}</div></fieldset>}
      <div className="lecture-review-actions"><button className="btn btn-soft" type="button" disabled={busy || !selectedNotes.length} onClick={() => onReview(lecture, selectedNotes, selectedTopics)}>{busy ? "Saving…" : "Save reviewed selection"}</button><button className="btn btn-soft" type="button" disabled={busy} onClick={() => onEdit(lecture)}>Correct transcript</button>{lecture.status === "reviewed" && <button className="btn btn-primary" type="button" disabled={busy || !selectionSaved} onClick={() => onPublication(lecture, true)}>Publish approved notes</button>}</div>
      {lecture.status === "reviewed" && !selectionSaved && <p role="status">Save your changed selection before publishing.</p>}
    </>}
    {lecture.status === "published" && <div className="lecture-review-actions"><button className="btn btn-soft" type="button" disabled={busy} onClick={() => onPublication(lecture, false)}>Unpublish</button></div>}
  </div>;
}

export default function LectureNotesPanel({ courseId, sessions, manager = false }) {
  const [lectures, setLectures] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [transcript, setTranscript] = useState("");
  const [permissionsConfirmed, setPermissionsConfirmed] = useState(false);
  const [recordingCapabilities, setRecordingCapabilities] = useState(null);
  const [recordings, setRecordings] = useState([]);
  const [recordingSessionId, setRecordingSessionId] = useState("");
  const [recordingFile, setRecordingFile] = useState(null);
  const [recordingConsent, setRecordingConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const completed = sessions.filter(session => session.ended_at);

  const load = async () => {
    const [lectureRows, recordingRows] = await Promise.all([
      apiFetch(`/ai/lectures/course/${courseId}`),
      manager ? apiFetch(`/ai/lectures/recordings/course/${courseId}`) : Promise.resolve([]),
    ]);
    setLectures(lectureRows); setRecordings(recordingRows);
  };
  useEffect(() => { let active = true; Promise.all([
    apiFetch(`/ai/lectures/course/${courseId}`),
    manager ? apiFetch(`/ai/lectures/recordings/course/${courseId}`) : Promise.resolve([]),
    manager ? apiFetch("/ai/lectures/recording-capabilities") : Promise.resolve(null),
  ]).then(([lectureRows, recordingRows, capabilities]) => {
    if (active) { setLectures(lectureRows); setRecordings(recordingRows); setRecordingCapabilities(capabilities); }
  }).catch(requestError => { if (active) setError(requestError.message); });
    return () => { active = false; }; }, [courseId, manager]);
  useEffect(() => {
    if (!manager) return undefined;
    const timer = window.setInterval(() => {
      apiFetch(`/ai/lectures/recordings/course/${courseId}`).then(setRecordings).catch(() => {});
    }, 10000);
    return () => window.clearInterval(timer);
  }, [courseId, manager]);

  const uploadRecording = async event => {
    event.preventDefault(); const formElement = event.currentTarget;
    setBusy(true); setError(""); setMessage("");
    try {
      const body = new FormData();
      body.append("file", recordingFile);
      body.append("permissions_confirmed", String(recordingConsent));
      await apiFetch(`/ai/lectures/sessions/${recordingSessionId}/recording`, { method: "POST", body });
      setRecordingSessionId(""); setRecordingFile(null); setRecordingConsent(false);
      formElement.reset();
      setMessage("Private recording saved. It has not been transcribed; provide and verify the lecture transcript before preparing notes.");
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const removeRecording = async recording => {
    if (!window.confirm(`Permanently remove the private recording for class #${recording.session_id}? Published notes will remain.`)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await apiFetch(`/ai/lectures/recordings/${recording.id}`, { method: "DELETE" });
      setMessage("Private recording removed. Reviewed notes, if any, remain available according to their publication status.");
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const queuePreparation = async recording => {
    setBusy(true); setError(""); setMessage("");
    try {
      await apiFetch(`/ai/lectures/recordings/${recording.id}/prepare`, { method: "POST" });
      setMessage("Recording queued for the private institution worker. This prepares audio and frames only; it does not create a transcript or notes.");
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const prepare = async event => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      await apiFetch(`/ai/lectures/sessions/${sessionId}/transcript`, {
        method: "POST", body: JSON.stringify({ transcript, transcript_source: "faculty_text", permissions_confirmed: permissionsConfirmed }),
      });
      setTranscript(""); setSessionId(""); setPermissionsConfirmed(false); setMessage("Extractive summary and notes prepared. Review every statement before publishing.");
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const publication = async (lecture, publish) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await apiFetch(`/ai/lectures/${lecture.id}/publication`, {
        method: "PATCH", body: JSON.stringify({ publish }),
      });
      setMessage(publish ? "Lecture notes published to enrolled students and course AI sources." : "Lecture notes removed from student access.");
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const review = async (lecture, included_statement_numbers, included_topics) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await apiFetch(`/ai/lectures/${lecture.id}/review`, {
        method: "PATCH", body: JSON.stringify({ included_statement_numbers, included_topics }),
      });
      setMessage("Selection saved. Check the revised summary below before publishing.");
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const editTranscript = lecture => {
    setSessionId(String(lecture.session_id)); setTranscript(lecture.transcript || "");
    setPermissionsConfirmed(false);
    setMessage("Correct the original transcript and prepare a new private draft. Existing publication must be removed first.");
    document.getElementById("lecture-notes")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return <section className="card panel-card course-workspace-section lecture-notes-panel" id="lecture-notes">
    <div className="section-title-row"><div><p className="section-eyebrow">AI Stage 4 · Completed classes</p><h2>Lecture summaries & notes</h2></div><span className="pill pill-info">{manager ? "Faculty review required" : "Faculty approved"}</span></div>
    {manager && <>
      <p>This meeting provider does not currently deliver recordings or automatic speech transcripts to Ekeekrta. Paste a real transcript from a completed class; the local engine selects statements without inventing content.</p>
      <div className="lecture-recording-intake">
        <div className="section-title-row"><div><h3>Private class recordings</h3><p>Raw video stays outside student access. Automatic transcription runs only when an institution-reviewed EKEEKRTA model executable is configured.</p></div><span className="pill pill-muted">{recordings.length} stored</span></div>
        {recordingCapabilities?.automatic_transcription_available && <p className="lecture-recording-capability">Local speech model connected{recordingCapabilities.slide_ocr_available ? " · slide OCR connected" : " · slide OCR not connected"}. Every generated statement still requires faculty review.</p>}
        {recordingCapabilities?.local_upload_available && completed.length > 0 && <form className="lecture-transcript-form" onSubmit={uploadRecording}>
          <label className="field-label">Completed class<select className="field" value={recordingSessionId} onChange={event => setRecordingSessionId(event.target.value)} required><option value="">Choose a class</option>{completed.map(session => <option key={session.id} value={session.id}>Class #{session.id} · ended {new Date(session.ended_at).toLocaleString()}</option>)}</select></label>
          <label className="field-label">MP4 or WebM class recording<input className="field" type="file" accept=".mp4,.webm,video/mp4,video/webm" onChange={event => setRecordingFile(event.target.files?.[0] || null)} required /></label>
          <p>Local limit: {recordingCapabilities.maximum_upload_mb} MB. Keep recording access and participant consent aligned with your institution policy.</p>
          <label className="check-row"><input type="checkbox" checked={recordingConsent} onChange={event => setRecordingConsent(event.target.checked)} required />I confirm participants were informed and this recording may be privately processed.</label>
          <button className="btn btn-soft" disabled={busy || !recordingFile || !recordingConsent}>{busy ? "Saving…" : "Save private recording"}</button>
        </form>}
        {recordingCapabilities && !recordingCapabilities.local_upload_available && <p className="lecture-recording-unavailable">This public backend cannot store class videos. Recording upload requires a private institution worker; automatic Jitsi recording is not connected yet.</p>}
        {!recordings.length ? <EmptyState>No private class recording is registered for this course.</EmptyState> : <div className="lecture-recording-list">{recordings.map(recording => {
          const activeJob = ["queued", "processing"].includes(recording.preparation?.status);
          const canContinuePrepared = recording.status === "media_prepared" && recordingCapabilities?.automatic_transcription_available && !recording.notes_status;
          const canPrepare = recordingCapabilities?.preparation_queue_available && recording.status !== "transcript_draft_ready" && (recording.status !== "media_prepared" || canContinuePrepared) && !activeJob;
          const prepareLabel = canContinuePrepared ? "Create transcript draft" : recording.preparation?.status === "failed" ? "Retry processing" : "Prepare recording";
          return <article key={recording.id}><div><strong>Class #{recording.session_id} · {recording.original_filename}</strong><p>{(recording.size_bytes / (1024 * 1024)).toFixed(1)} MB · {preparationLabel(recording)} · notes {recording.notes_status || "not prepared"}</p></div><div className="lecture-recording-actions">{canPrepare && <button type="button" className="btn btn-soft" disabled={busy} onClick={() => queuePreparation(recording)}>{prepareLabel}</button>}{recordingCapabilities?.local_upload_available && <button type="button" className="btn btn-soft" disabled={busy} onClick={() => removeRecording(recording)}>Remove recording</button>}</div></article>;
        })}</div>}
      </div>
      {!completed.length ? <EmptyState>End a class before preparing lecture notes.</EmptyState> : <form className="lecture-transcript-form" onSubmit={prepare}>
        <label className="field-label">Completed class<select className="field" value={sessionId} onChange={event => setSessionId(event.target.value)} required><option value="">Choose a class</option>{completed.map(session => <option key={session.id} value={session.id}>Class #{session.id} · ended {new Date(session.ended_at).toLocaleString()}</option>)}</select></label>
        <label className="field-label">Verified lecture transcript<textarea className="field" rows="8" minLength="180" maxLength="100000" value={transcript} onChange={event => setTranscript(event.target.value)} placeholder="Paste the actual lecture transcript. Check personal information and errors before submitting." required /></label>
        <label className="check-row"><input type="checkbox" checked={permissionsConfirmed} onChange={event => setPermissionsConfirmed(event.target.checked)} required />I confirm this lecture text may be processed and I removed sensitive personal details.</label>
        <button className="btn btn-primary" disabled={busy || !permissionsConfirmed}>{busy ? "Preparing…" : "Prepare review draft"}</button>
      </form>}
    </>}
    {error && <div className="error-banner" role="alert">{error}</div>}
    {message && <div className="success-banner" role="status">{message}</div>}
    {!lectures.length && <EmptyState>{manager ? "No lecture digest has been prepared for this course." : "Faculty has not published lecture notes for this course yet."}</EmptyState>}
    <div className="lecture-digest-list">{lectures.map(lecture => <article key={lecture.id}>
      <div className="section-title-row"><div><h3>Class #{lecture.session_id}</h3><p>{lecture.transcript_source === "faculty_text" ? "Faculty-provided transcript" : lecture.transcript_source === "ekeekrta_local_models" ? "EKEEKRTA local-model draft" : lecture.transcript_source === "faculty_corrected_local_model" ? "Faculty-corrected local-model transcript" : lecture.transcript_source} · {lecture.summary.statement_count} source statements</p></div><span className={`pill ${lecture.status === "published" ? "pill-ok" : lecture.status === "reviewed" ? "pill-info" : "pill-muted"}`}>{lecture.status === "published" ? "Published" : lecture.status === "reviewed" ? "Reviewed · private" : "Private draft"}</span></div>
      {manager && lecture.summary.model_provenance && <p className="lecture-model-provenance">Speech model: {lecture.summary.model_provenance.speech_model_id} · segments {lecture.summary.model_provenance.segment_count} · average confidence {Math.round(lecture.summary.model_provenance.average_confidence * 100)}% · slide evidence {lecture.summary.model_provenance.slide_count || 0}{lecture.summary.model_provenance.corrected_by_faculty ? " · faculty corrected" : ""}</p>}
      <p className="lecture-summary">{lecture.summary.summary}</p>
      {lecture.summary.topics?.length > 0 && <div className="lecture-topics">{lecture.summary.topics.map(topic => <span className="pill pill-muted" key={topic}>{topic}</span>)}</div>}
      <div className="lecture-note-list">{lecture.summary.notes?.map(note => <blockquote key={note.statement_number}><p>{note.text}</p><cite>Transcript statement {note.statement_number}</cite></blockquote>)}</div>
      {manager && <LectureReviewControls key={`${lecture.id}-${lecture.status}-${lecture.summary.summary}`} lecture={lecture} busy={busy} onReview={review} onEdit={editTranscript} onPublication={publication} />}
    </article>)}</div>
  </section>;
}
