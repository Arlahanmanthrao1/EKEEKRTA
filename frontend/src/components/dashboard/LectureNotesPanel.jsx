import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";
import { EmptyState } from "./DashboardShell";
import "../../styles/faculty-course.css";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const completed = sessions.filter(session => session.ended_at);

  const load = async () => setLectures(await apiFetch(`/ai/lectures/course/${courseId}`));
  useEffect(() => { let active = true; apiFetch(`/ai/lectures/course/${courseId}`)
    .then(rows => { if (active) setLectures(rows); }).catch(requestError => { if (active) setError(requestError.message); });
    return () => { active = false; }; }, [courseId]);

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
      <div className="section-title-row"><div><h3>Class #{lecture.session_id}</h3><p>{lecture.transcript_source === "faculty_text" ? "Faculty-provided transcript" : lecture.transcript_source} · {lecture.summary.statement_count} source statements</p></div><span className={`pill ${lecture.status === "published" ? "pill-ok" : lecture.status === "reviewed" ? "pill-info" : "pill-muted"}`}>{lecture.status === "published" ? "Published" : lecture.status === "reviewed" ? "Reviewed · private" : "Private draft"}</span></div>
      <p className="lecture-summary">{lecture.summary.summary}</p>
      {lecture.summary.topics?.length > 0 && <div className="lecture-topics">{lecture.summary.topics.map(topic => <span className="pill pill-muted" key={topic}>{topic}</span>)}</div>}
      <div className="lecture-note-list">{lecture.summary.notes?.map(note => <blockquote key={note.statement_number}><p>{note.text}</p><cite>Transcript statement {note.statement_number}</cite></blockquote>)}</div>
      {manager && <LectureReviewControls key={`${lecture.id}-${lecture.status}-${lecture.summary.summary}`} lecture={lecture} busy={busy} onReview={review} onEdit={editTranscript} onPublication={publication} />}
    </article>)}</div>
  </section>;
}
