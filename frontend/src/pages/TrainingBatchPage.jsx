import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import DashboardShell, { EmptyState } from "../components/dashboard/DashboardShell";
import GoogleDriveFolderPicker from "../components/GoogleDriveFolderPicker";
import "../styles/dashboard.css";
import "../styles/training.css";

function ProgressBar({ value = 0 }) {
  return <div className="batch-progress"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /><strong>{value}%</strong></div>;
}

export default function TrainingBatchPage() {
  const { batchId } = useParams();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const manager = user.role === "admin" || user.role === "faculty";
  const trainer = user.role === "faculty";
  const [batch, setBatch] = useState(null);
  const [learners, setLearners] = useState([]);
  const [trainers, setTrainers] = useState([]);
  const [available, setAvailable] = useState([]);
  const [modules, setModules] = useState([]);
  const [progress, setProgress] = useState([]);
  const [certificates, setCertificates] = useState([]);
  const [printCertificate, setPrintCertificate] = useState(null);
  const [classes, setClasses] = useState({ scheduled: [], sessions: [] });
  const [selectedLearner, setSelectedLearner] = useState("");
  const [moduleForm, setModuleForm] = useState({ title: "", description: "", published: true });
  const [lessonDrafts, setLessonDrafts] = useState({});
  const [classForm, setClassForm] = useState({ title: "", starts_at: "" });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const fileRef = useRef(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const calls = [apiFetch(`/training/batches/${batchId}`), apiFetch(`/training/batches/${batchId}/modules`),
          apiFetch(`/training/batches/${batchId}/progress`), apiFetch(`/training/batches/${batchId}/certificates`),
          apiFetch(`/training/batches/${batchId}/classes`)];
        if (manager) calls.push(apiFetch(`/training/batches/${batchId}/learners`), apiFetch(`/training/batches/${batchId}/available-learners`));
        if (user.role === "admin") calls.push(apiFetch("/users/"));
        const result = await Promise.all(calls);
        if (!active) return;
        setBatch(result[0]); setModules(result[1]); setProgress(result[2].learners || []);
        setCertificates(result[3]); setClasses(result[4]);
        if (manager) { setLearners(result[5]); setAvailable(result[6]); }
        if (user.role === "admin") setTrainers(result[7].filter(account => account.role === "faculty"));
        setError("");
      } catch (err) { if (active) setError(err.message); }
      finally { if (active) setLoading(false); }
    }
    load();
    return () => { active = false; };
  }, [batchId, manager, reload, user.role]);

  const certificateByStudent = useMemo(() => new Map(certificates.filter(row => !row.revoked_at).map(row => [row.student_id, row])), [certificates]);
  const printIssuedCertificate = certificate => {
    setPrintCertificate(certificate);
    window.setTimeout(() => window.print(), 50);
  };
  async function run(action, success) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await action(); if (success) setNotice(success); setReload(value => value + 1); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  const updateBatch = values => run(() => apiFetch(`/training/batches/${batchId}`, { method: "PATCH", body: JSON.stringify(values) }), "Batch settings updated.");
  const enroll = event => { event.preventDefault(); run(() => apiFetch(`/training/batches/${batchId}/learners`, { method: "POST", body: JSON.stringify({ student_id: Number(selectedLearner) }) }), "Learner enrolled."); };
  const importCsv = event => {
    const file = event.target.files?.[0]; if (!file) return;
    const body = new FormData(); body.append("file", file);
    run(async () => { const result = await apiFetch(`/training/batches/${batchId}/learners/csv`, { method: "POST", body }); setNotice(`${result.added} learners added, ${result.already_enrolled} already enrolled${result.errors.length ? `, ${result.errors.length} rows need attention` : ""}.`); }, null);
    event.target.value = "";
  };
  const addModule = event => { event.preventDefault(); run(() => apiFetch(`/training/batches/${batchId}/modules`, { method: "POST", body: JSON.stringify(moduleForm) }).then(() => setModuleForm({ title: "", description: "", published: true })), "Module added."); };
  const addLesson = (event, moduleId) => {
    event.preventDefault(); const draft = lessonDrafts[moduleId] || {};
    run(() => apiFetch(`/training/modules/${moduleId}/lessons`, { method: "POST", body: JSON.stringify({ title: draft.title, description: draft.description || null, resource_url: draft.resource_url || null, estimated_minutes: Number(draft.estimated_minutes || 30), required: true }) }).then(() => setLessonDrafts(current => ({ ...current, [moduleId]: {} }))), "Lesson added in order.");
  };
  const moveModule = (moduleId, direction) => {
    const ids = modules.map(row => row.id); const index = ids.indexOf(moduleId); const next = index + direction;
    if (index < 0 || next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    run(() => apiFetch(`/training/batches/${batch.id}/modules/order`, { method: "PUT", body: JSON.stringify({ ordered_ids: ids }) }), "Module order updated.");
  };
  const moveLesson = (module, lessonId, direction) => {
    const ids = module.lessons.map(row => row.id); const index = ids.indexOf(lessonId); const next = index + direction;
    if (index < 0 || next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    run(() => apiFetch(`/training/modules/${module.id}/lessons/order`, { method: "PUT", body: JSON.stringify({ ordered_ids: ids }) }), "Lesson order updated.");
  };
  const completeLesson = lessonId => run(() => apiFetch(`/training/lessons/${lessonId}/complete`, { method: "POST" }), "Lesson marked complete.");
  const scheduleClass = event => {
    event.preventDefault();
    const starts = new Date(classForm.starts_at);
    if (!Number.isFinite(starts.getTime()) || starts <= new Date()) { setError("Choose a future class time."); return; }
    run(() => apiFetch("/schedule", { method: "POST", body: JSON.stringify({ course_id: batch.course_id, training_batch_id: batch.id, title: classForm.title, starts_at: starts.toISOString() }) }).then(() => setClassForm({ title: "", starts_at: "" })), "Class scheduled for this batch.");
  };
  async function openClass(session) {
    navigate("/classroom", { state: { sessionId: session.id, roomId: session.jitsi_room_id, courseId: batch.course_id,
      courseName: `${batch.course_name} · ${batch.name}`, studentId: user.id, studentName: user.name, isFaculty: trainer } });
  }
  const startNow = () => run(async () => openClass(await apiFetch("/attendance/sessions", { method: "POST", body: JSON.stringify({ course_id: batch.course_id, training_batch_id: batch.id }) })), null);
  const startPlan = plan => run(async () => openClass(await apiFetch(`/schedule/${plan.id}/start`, { method: "POST" })), null);
  const joinSession = sessionId => run(async () => openClass(await apiFetch(`/attendance/sessions/detail/${sessionId}`)), null);

  if (loading) return <DashboardShell user={user} title="Batch" roleLabel={trainer ? "Trainer" : user.role === "student" ? "Learner" : "Administrator"} onLogout={logout} activePage="batches"><p role="status">Loading batch workspace…</p></DashboardShell>;
  return <DashboardShell user={user} title={batch?.name || "Batch"} roleLabel={trainer ? "Trainer" : user.role === "student" ? "Learner" : "Administrator"} onLogout={logout} activePage="batches">
    <Link className="back-link" to={`/${user.role}/batches`}>← All batches</Link>
    {error && <p className="error-banner" role="alert">{error}</p>}{notice && <p className="success-banner" role="status">{notice}</p>}
    {batch && <>
      <section className="training-batch-hero card"><div><span className={`pill batch-status-${batch.status}`}>{batch.status}</span><p className="section-eyebrow">{batch.code} · {batch.course_code}</p><h1>{batch.name}</h1><p>{batch.course_name} · Trainer {batch.trainer_name}</p></div><div className="batch-hero-facts"><div><small>Dates</small><strong>{batch.start_date} – {batch.end_date}</strong></div><div><small>Capacity</small><strong>{batch.learner_count} / {batch.capacity}</strong></div><div><small>Certificate rule</small><strong>{batch.certificate_min_progress}% progress · {batch.certificate_min_attendance}% attendance</strong></div></div>
        {manager && <div className="batch-hero-actions">{user.role === "admin" && <select className="field" aria-label="Assigned trainer" value={batch.trainer_id} disabled={busy} onChange={event => updateBatch({ trainer_id: Number(event.target.value) })}>{trainers.map(account => <option key={account.id} value={account.id}>{account.name}</option>)}</select>}<select className="field" aria-label="Batch status" value={batch.status} disabled={busy} onChange={event => updateBatch({ status: event.target.value })}><option value="planned">Planned</option><option value="active">Active</option><option value="completed">Completed</option><option value="archived">Archived</option></select><label className="compact-field-label">Capacity<input className="field" type="number" min={batch.learner_count || 1} max="10000" defaultValue={batch.capacity} disabled={busy} onBlur={event => { const value = Number(event.target.value); if (value && value !== batch.capacity) updateBatch({ capacity: value }); }} /></label>{trainer && batch.status !== "completed" && batch.status !== "archived" && <button className="btn btn-primary" disabled={busy} onClick={startNow}>Start class now</button>}</div>}
      </section>

      <div className="batch-workspace-grid">
        <main className="batch-workspace-main">
          <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Ordered curriculum</p><h2>Modules and lessons</h2></div><span className="pill pill-muted">{modules.length} modules</span></div>
            {!modules.length && <EmptyState>No modules have been added yet.</EmptyState>}
            <div className="module-list">{modules.map((module, moduleIndex) => <article className="module-card" key={module.id}><header><span>{module.position}</span><div><h3>{module.title}</h3><p>{module.description || "No description"}</p></div><div className="order-controls"><span className={`pill ${module.published ? "pill-success" : "pill-muted"}`}>{module.published ? "Published" : "Draft"}</span>{manager && <><button type="button" aria-label={`Move ${module.title} up`} disabled={busy || moduleIndex === 0} onClick={() => moveModule(module.id, -1)}>↑</button><button type="button" aria-label={`Move ${module.title} down`} disabled={busy || moduleIndex === modules.length - 1} onClick={() => moveModule(module.id, 1)}>↓</button></>}</div></header>
              <ol>{module.lessons.map((lesson, lessonIndex) => <li key={lesson.id}><div><strong>{lesson.title}</strong><p>{lesson.description || `${lesson.estimated_minutes} minute lesson`}</p>{lesson.resource_url && <a href={lesson.resource_url} target="_blank" rel="noreferrer">Open resource ↗</a>}</div>{user.role === "student" && <button className="btn btn-soft" disabled={lesson.completed || busy} onClick={() => completeLesson(lesson.id)}>{lesson.completed ? "Completed" : "Mark complete"}</button>}{manager && <div className="order-controls"><button type="button" aria-label={`Move ${lesson.title} up`} disabled={busy || lessonIndex === 0} onClick={() => moveLesson(module, lesson.id, -1)}>↑</button><button type="button" aria-label={`Move ${lesson.title} down`} disabled={busy || lessonIndex === module.lessons.length - 1} onClick={() => moveLesson(module, lesson.id, 1)}>↓</button></div>}</li>)}</ol>
              {manager && <form className="inline-lesson-form" onSubmit={event => addLesson(event, module.id)}><input className="field" required placeholder="Next lesson title" value={lessonDrafts[module.id]?.title || ""} onChange={event => setLessonDrafts(current => ({ ...current, [module.id]: { ...current[module.id], title: event.target.value } }))} /><input className="field" type="url" placeholder="Optional resource URL" value={lessonDrafts[module.id]?.resource_url || ""} onChange={event => setLessonDrafts(current => ({ ...current, [module.id]: { ...current[module.id], resource_url: event.target.value } }))} /><button className="btn btn-soft" disabled={busy}>Add lesson</button></form>}
            </article>)}</div>
            {manager && <form className="module-builder" onSubmit={addModule}><h3>Add module</h3><input className="field" required placeholder="Module title" value={moduleForm.title} onChange={event => setModuleForm({ ...moduleForm, title: event.target.value })} /><textarea className="field" placeholder="What learners will achieve" value={moduleForm.description} onChange={event => setModuleForm({ ...moduleForm, description: event.target.value })} /><label className="check-row"><input type="checkbox" checked={moduleForm.published} onChange={event => setModuleForm({ ...moduleForm, published: event.target.checked })} /> Publish to learners</label><button className="btn btn-primary" disabled={busy}>Add next module</button></form>}
          </section>

          <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Live delivery</p><h2>Classes, recordings and attendance</h2></div>{trainer && <button className="btn btn-primary" onClick={startNow} disabled={busy || ["completed", "archived"].includes(batch.status)}>Start now</button>}</div>
            {trainer && <form className="batch-schedule-form" onSubmit={scheduleClass}><input className="field" required placeholder="Class title" value={classForm.title} onChange={event => setClassForm({ ...classForm, title: event.target.value })} /><input className="field" type="datetime-local" required value={classForm.starts_at} onChange={event => setClassForm({ ...classForm, starts_at: event.target.value })} /><button className="btn btn-soft" disabled={busy}>Schedule</button></form>}
            {!classes.scheduled.length && !classes.sessions.length && <EmptyState>No classes have been scheduled or started.</EmptyState>}
            <div className="class-ledger">{classes.scheduled.map(plan => <article key={`p-${plan.id}`}><div><span className="pill pill-muted">{plan.status}</span><strong>{plan.title}</strong><time>{new Date(plan.starts_at).toLocaleString()}</time></div>{trainer && plan.status === "scheduled" && <button className="btn btn-soft" onClick={() => startPlan(plan)} disabled={busy}>Start class</button>}{plan.status === "live" && <button className="btn btn-primary" onClick={() => joinSession(plan.session_id)} disabled={busy}>{trainer ? "Rejoin" : "Join class"}</button>}</article>)}{classes.sessions.filter(session => !session.ended_at && !classes.scheduled.some(plan => plan.session_id === session.id)).map(session => <article key={`live-${session.id}`}><div><span className="pill batch-status-active">Live</span><strong>Live class</strong><time>{new Date(session.scheduled_at).toLocaleString()}</time></div><button className="btn btn-primary" onClick={() => joinSession(session.id)} disabled={busy}>{trainer ? "Rejoin" : "Join class"}</button></article>)}{classes.sessions.filter(session => session.ended_at).map(session => <article key={`s-${session.id}`}><div><span className="pill batch-status-completed">Ended</span><strong>Class session</strong><time>{new Date(session.scheduled_at).toLocaleString()}</time></div>{session.recording_url ? <a className="btn btn-soft" href={session.recording_url} target="_blank" rel="noreferrer">Open recording</a> : <span className="footnote">Recording processing or unavailable</span>}</article>)}</div>
            {trainer && <GoogleDriveFolderPicker value={batch.recording_drive_folder_configured ? "configured" : ""} onChange={folder => updateBatch({ recording_drive_folder_id: folder })} />}
          </section>

          <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Measured outcomes</p><h2>{manager ? "Learner progress" : "My progress"}</h2></div></div>
            <div className="progress-ledger">{progress.map(row => <article key={row.student_id}><div><h3>{row.student_name}</h3><p>{row.institutional_id || "Learner"}</p></div><ProgressBar value={row.overall_percent} /><div className="progress-breakdown"><span>Lessons {row.lesson_completed}/{row.lesson_total}</span><span>Assignments {row.assignment_completed}/{row.assignment_total}</span><span>Quizzes {row.quiz_completed}/{row.quiz_total}</span><span>Attendance {row.sessions_attended}/{row.session_total}</span></div><div>{certificateByStudent.has(row.student_id) ? <button className="btn btn-soft" onClick={() => printIssuedCertificate(certificateByStudent.get(row.student_id))}>Print certificate</button> : manager && <button className="btn btn-soft" disabled={!row.certificate_eligible || busy} onClick={() => run(() => apiFetch(`/training/batches/${batch.id}/certificates/${row.student_id}`, { method: "POST" }), "Certificate generated.")}>{row.certificate_eligible ? "Generate certificate" : "Not yet eligible"}</button>}</div></article>)}</div>
          </section>
        </main>

        {manager && <aside className="batch-workspace-side"><section className="card panel-card"><h2>Enroll learners</h2><form onSubmit={enroll}><label className="field-label">Individual learner<select className="field" required value={selectedLearner} onChange={event => setSelectedLearner(event.target.value)}><option value="">Select learner</option>{available.map(learner => <option key={learner.id} value={learner.id}>{learner.name} · {learner.institutional_id || learner.email}</option>)}</select></label><button className="btn btn-primary" disabled={busy || !available.length}>Add learner</button></form><hr /><input ref={fileRef} hidden type="file" accept=".csv,text/csv" onChange={importCsv} /><div className="csv-actions"><button className="btn btn-soft" onClick={() => fileRef.current?.click()} disabled={busy}>Import CSV</button><a className="btn btn-soft" href="data:text/csv;charset=utf-8,institutional_id%2Cemail%0ALEARNER-001%2Clearner%40example.org" download="batch-enrollment-template.csv">Download template</a></div><p className="footnote">CSV headers: <code>institutional_id</code> or <code>email</code>. Existing learner accounts are matched; no duplicate accounts are created.</p></section>
          <section className="card panel-card"><div className="section-title-row"><h2>Roster</h2><span className="pill pill-muted">{learners.filter(row => row.status !== "withdrawn").length}</span></div><div className="compact-roster">{learners.filter(row => row.status !== "withdrawn").map(row => <article key={row.id}><div><strong>{row.student_name}</strong><span>{row.institutional_id || row.student_email}</span></div><button className="text-danger-button" disabled={busy} onClick={() => run(() => apiFetch(`/training/batches/${batch.id}/learners/${row.student_id}`, { method: "DELETE" }), "Learner removed from this batch.")}>Remove</button></article>)}</div></section>
        </aside>}
      </div>

      {printCertificate && <section className="print-certificate"><p>Certificate of Completion</p><h1>{printCertificate.learner_name}</h1><p>has successfully completed</p><h2>{printCertificate.course_name}</h2><h3>{printCertificate.batch_name}</h3><p>{printCertificate.institution_name}</p><small>Certificate {printCertificate.certificate_number} · Issued {new Date(printCertificate.issued_at).toLocaleDateString()}</small></section>}
    </>}
  </DashboardShell>;
}
