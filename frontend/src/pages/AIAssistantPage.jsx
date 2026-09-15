import { useCallback, useEffect, useMemo, useState } from "react";
import DashboardShell, { EmptyState, Icon } from "../components/dashboard/DashboardShell";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import "../styles/dashboard.css";

const roleLabels = { admin: "Administrator", faculty: "Faculty", hod: "HOD", student: "Student" };
const examples = {
  faculty: [
    "Schedule a Cloud Computing class tomorrow at 10:30 AM",
    "Create an assignment on load balancing for Cloud Computing due tomorrow",
    "Draft a 10 question quiz on recursion for Data Structures",
    "Show progress for my students who are at risk",
  ],
  admin: ["Create department Computer Science", "Create course Cloud Computing code CS401 department Computer Science program B.Tech CSE batch 2026-2030 semester 1 faculty FAC-001 compulsory", "Bulk create accounts", "Import users from ERP based on role"],
  hod: ["Show students who are at risk", "Show progress for Student Name", "What can you do?"],
  student: ["Show my progress", "Check my attendance and marks", "What can you do?"],
};

const intentNames = {
  schedule_class: "Schedule class", draft_assignment: "Draft assignment", draft_quiz: "Draft quiz",
  student_progress: "Student progress", import_erp_students: "Import ERP users by role", help: "Help",
  create_department: "Create department", create_course: "Create course", bulk_create_accounts: "Bulk-create accounts",
  cgpa_plan: "Target CGPA roadmap", course_question: "Course knowledge question",
};

const bulkHeaders = ["role", "name", "email", "institutional_id", "department", "program", "batch", "semester_number", "section"];

function csvRow(line) {
  const values = []; let value = ""; let quoted = false;
  for (let index = 0; index < line.length; index++) {
    const character = line[index];
    if (character === '"' && quoted && line[index + 1] === '"') { value += '"'; index++; }
    else if (character === '"') quoted = !quoted;
    else if (character === "," && !quoted) { values.push(value.trim()); value = ""; }
    else value += character;
  }
  if (quoted) throw new Error("A quoted CSV value is not closed.");
  values.push(value.trim()); return values;
}

export function parseBulkCsv(source) {
  const lines = source.split(/\r?\n/).filter(line => line.trim());
  if (lines.length < 2) throw new Error("Add a header row and at least one account row.");
  const headers = csvRow(lines[0]).map(value => value.toLowerCase().replaceAll(" ", "_"));
  const missing = bulkHeaders.filter(header => !headers.includes(header));
  if (missing.length) throw new Error(`Missing CSV columns: ${missing.join(", ")}`);
  return lines.slice(1).map((line, index) => {
    const values = csvRow(line); const record = {};
    headers.forEach((header, position) => { if (bulkHeaders.includes(header)) record[header] = values[position] || null; });
    if (values.length > headers.length) throw new Error(`Row ${index + 2} has more values than the header.`);
    record.semester_number = record.semester_number ? Number(record.semester_number) : null;
    if (record.semester_number !== null && !Number.isInteger(record.semester_number)) throw new Error(`Row ${index + 2} has an invalid semester.`);
    return record;
  });
}

function displayKey(value) {
  return value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function Value({ value }) {
  if (value === null || value === undefined) return <span className="ai-empty-value">Not available yet</span>;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) {
    if (!value.length) return <span className="ai-empty-value">No records</span>;
    return <div className="ai-list">{value.map((entry, index) => <div className="ai-list-item" key={index}><Value value={entry} /></div>)}</div>;
  }
  if (typeof value === "object") return <Preview data={value} />;
  return String(value);
}

function Preview({ data }) {
  return <dl className="ai-preview">{Object.entries(data || {}).map(([key, value]) => (
    <div key={key}><dt>{displayKey(key)}</dt><dd><Value value={value} /></dd></div>
  ))}</dl>;
}

export function ActionCard({ action, busy, onConfirm, onReject, onCorrect }) {
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctedIntent, setCorrectedIntent] = useState(action.intent);
  const [consent, setConsent] = useState(false);
  const content = action.result || action.preview;
  return (
    <article className="panel ai-action-card">
      <div className="panel-title-row">
        <div><span className={`pill ${action.status === "completed" ? "pill-good" : action.status === "rejected" ? "pill-risk" : "pill-info"}`}>{action.status}</span><h2>{intentNames[action.intent] || displayKey(action.intent)}</h2></div>
        <span className="ai-confidence">Intent confidence {Math.round(action.confidence * 100)}%</span>
      </div>
      <p className="ai-command-quote">“{action.prompt}”</p>
      <Preview data={content} />
      {action.requires_confirmation && action.status === "draft" && <div className="ai-actions">
        <button className="btn btn-primary" disabled={busy} onClick={() => onConfirm(action.id)}>Confirm action</button>
        <button className="btn btn-soft" disabled={busy} onClick={() => onReject(action.id)}>Reject</button>
      </div>}
      <button className="ai-correction-toggle" type="button" onClick={() => setShowCorrection(value => !value)}>{showCorrection ? "Close correction" : "AI understood this incorrectly"}</button>
      {showCorrection && <div className="ai-correction-box">
        <label>Correct action<select value={correctedIntent} onChange={event => setCorrectedIntent(event.target.value)}>{Object.entries(intentNames).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="check-row"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />Allow this command and correction to be stored for a reviewed EKEEKRTA training run.</label>
        <button className="btn btn-soft" disabled={!consent || busy} onClick={() => onCorrect(action.id, correctedIntent, consent)}>Save correction</button>
      </div>}
    </article>
  );
}

export function BulkAccountsPanel({ busy, onPreview }) {
  const [csv, setCsv] = useState(bulkHeaders.join(","));
  const [error, setError] = useState("");
  const preview = () => {
    setError("");
    try { onPreview(parseBulkCsv(csv)); }
    catch (parseError) { setError(parseError.message); }
  };
  return <section className="panel ai-bulk-panel">
    <div className="panel-title-row"><div><p className="section-eyebrow">Administrator tool</p><h2>Bulk account builder</h2></div><span className="pill pill-info">CSV · maximum 250 rows</span></div>
    <p>Paste student and faculty records below. Passwords are not accepted; created accounts sign in with their verified institution Google account.</p>
    <label htmlFor="bulk-account-csv">Account CSV</label>
    <textarea id="bulk-account-csv" rows="8" value={csv} onChange={event => setCsv(event.target.value)} spellCheck="false" />
    <p className="footnote">Student rows require program, batch, semester_number and section. Faculty rows may leave those four values empty.</p>
    {error && <p className="error-banner" role="alert">{error}</p>}
    <button className="btn btn-primary" type="button" disabled={busy} onClick={preview}>{busy ? "Validating…" : "Preview account creation"}</button>
  </section>;
}

export function FacultyContentDraftPanel({ courses, busy, onPreview }) {
  const [form, setForm] = useState({ course_id: "", content_type: "assignment", topic: "",
    source_text: "", question_count: 5, max_marks: 100, due_date: "" });
  const update = event => setForm(current => ({ ...current, [event.target.name]: event.target.value }));
  const submit = event => {
    event.preventDefault();
    onPreview({ ...form, course_id: Number(form.course_id), question_count: Number(form.question_count),
      max_marks: Number(form.max_marks), due_date: form.due_date ? new Date(form.due_date).toISOString() : null });
  };
  return <section className="panel ai-content-panel">
    <div className="panel-title-row"><div><p className="section-eyebrow">Native AI Stage 2B</p><h2>Lesson-note content studio</h2></div><span className="pill pill-info">Local · source grounded</span></div>
    <p>Paste your own lesson notes. EKEEKRTA extracts the teaching points locally and prepares a review draft; it never publishes before you confirm.</p>
    {!courses.length ? <EmptyState>Create a course before generating teaching content.</EmptyState> : <form className="form-grid ai-content-grid" onSubmit={submit}>
      <label className="field-label">Course<select className="field" name="course_id" value={form.course_id} onChange={update} required><option value="">Select your course</option>{courses.map(course => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></label>
      <label className="field-label">Draft type<select className="field" name="content_type" value={form.content_type} onChange={update}><option value="assignment">Assignment</option><option value="quiz">Quiz with answer key</option></select></label>
      <label className="field-label wide">Topic<input className="field" name="topic" value={form.topic} onChange={update} placeholder="Load balancing" minLength="3" maxLength="160" required /></label>
      <label className="field-label wide">Faculty lesson notes<textarea className="field" name="source_text" value={form.source_text} onChange={update} rows="9" minLength="80" maxLength="12000" placeholder="Paste definitions, explanations and facts from the lesson here. Include at least four distinct subject terms." required /></label>
      {form.content_type === "quiz" && <label className="field-label">Requested questions<input className="field" type="number" name="question_count" value={form.question_count} onChange={update} min="1" max="20" required /></label>}
      <label className="field-label">Maximum marks<input className="field" type="number" name="max_marks" value={form.max_marks} onChange={update} min="1" max="1000" step="1" required /></label>
      {form.content_type === "assignment" && <label className="field-label">Due date (optional)<input className="field" type="datetime-local" name="due_date" value={form.due_date} onChange={update} /></label>}
      <div className="wide ai-content-submit"><small>Generated quiz answers are visible only in the faculty review draft.</small><button className="btn btn-primary" disabled={busy}>{busy ? "Preparing draft…" : "Generate review draft"}</button></div>
    </form>}
  </section>;
}

export function CourseKnowledgePanel({ courses, role }) {
  const canManage = ["faculty", "admin"].includes(role);
  const [courseId, setCourseId] = useState("");
  const [sources, setSources] = useState([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [form, setForm] = useState({ title: "", source_type: "faculty_note", content: "", publish_to_students: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!courseId && courses.length) setCourseId(String(courses[0].id));
  }, [courseId, courses]);

  const loadSources = useCallback(async selected => {
    if (!selected) { setSources([]); return; }
    try { setSources(await apiFetch(`/ai/knowledge-sources/course/${selected}`)); }
    catch (requestError) { setError(requestError.message); }
  }, []);
  useEffect(() => { loadSources(courseId); }, [courseId, loadSources]);

  const addSource = async event => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/ai/knowledge-sources", { method: "POST", body: JSON.stringify({ ...form, course_id: Number(courseId) }) });
      setMessage(response.message); setForm({ title: "", source_type: "faculty_note", content: "", publish_to_students: true });
      await loadSources(courseId);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const setPublication = async source => {
    setBusy(true); setError("");
    try {
      await apiFetch(`/ai/knowledge-sources/${source.id}/publication`, { method: "PATCH", body: JSON.stringify({ published: !source.is_published }) });
      await loadSources(courseId);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const archive = async source => {
    if (!window.confirm(`Remove “${source.title}” from the course knowledge base?`)) return;
    setBusy(true); setError("");
    try { await apiFetch(`/ai/knowledge-sources/${source.id}`, { method: "DELETE" }); await loadSources(courseId); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const ask = async event => {
    event.preventDefault(); setBusy(true); setError(""); setMessage(""); setAnswer(null);
    try {
      const response = await apiFetch("/ai/course-question", { method: "POST", body: JSON.stringify({ course_id: Number(courseId), question }) });
      setAnswer(response.action.result); setQuestion("");
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  return <section className="panel ai-knowledge-panel">
    <div className="panel-title-row"><div><p className="section-eyebrow">Native AI Stage 3</p><h2>Course knowledge assistant</h2></div><span className="pill pill-info">Private · cited · no external model</span></div>
    <p>Answers use only published course text. Every result shows the exact approved passage it came from, and the assistant refuses when evidence is insufficient.</p>
    {!courses.length ? <EmptyState>No course is available in your account scope.</EmptyState> : <>
      <label className="field-label ai-knowledge-course">Course<select className="field" value={courseId} onChange={event => { setCourseId(event.target.value); setAnswer(null); setError(""); }}><option value="">Select a course</option>{courses.map(course => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></label>
      {canManage && <form className="form-grid ai-source-form" onSubmit={addSource}>
        <label className="field-label">Source title<input className="field" value={form.title} onChange={event => setForm(current => ({ ...current, title: event.target.value }))} minLength="3" maxLength="180" placeholder="Unit 1 approved notes" required /></label>
        <label className="field-label">Source type<select className="field" value={form.source_type} onChange={event => setForm(current => ({ ...current, source_type: event.target.value }))}><option value="faculty_note">Faculty note</option><option value="syllabus">Syllabus</option><option value="lecture">Lecture text</option><option value="reference">Approved reference</option><option value="other">Other</option></select></label>
        <label className="field-label wide">Approved course text<textarea className="field" rows="7" minLength="80" maxLength="50000" value={form.content} onChange={event => setForm(current => ({ ...current, content: event.target.value }))} placeholder="Paste verified text for this course. Do not include passwords, tokens or private personal information." required /></label>
        <label className="check-row wide"><input type="checkbox" checked={form.publish_to_students} onChange={event => setForm(current => ({ ...current, publish_to_students: event.target.checked }))} />Make this source available to enrolled students</label>
        <div className="wide"><button className="btn btn-primary" disabled={busy || !courseId}>{busy ? "Saving…" : "Add approved source"}</button></div>
      </form>}
      <div className="ai-source-list"><div className="section-title-row"><h3>Available sources</h3><span className="pill pill-muted">{sources.length}</span></div>
        {!sources.length ? <EmptyState>{canManage ? "Add approved course text before asking questions." : "Faculty has not published an AI source for this course yet."}</EmptyState> : sources.map(source => <article key={source.id}><div><strong>{source.title}</strong><p>{source.source_type.replaceAll("_", " ")} · {source.character_count.toLocaleString()} characters</p></div><span className={`pill ${source.is_published ? "pill-ok" : "pill-muted"}`}>{source.is_published ? "Published" : "Faculty only"}</span>{canManage && (source.managed_by_lecture ? <span className="pill pill-info">Managed from lecture notes</span> : <div className="ai-source-actions"><button type="button" className="btn-text" disabled={busy} onClick={() => setPublication(source)}>{source.is_published ? "Unpublish" : "Publish"}</button><button type="button" className="btn-text danger-text" disabled={busy} onClick={() => archive(source)}>Remove</button></div>)}</article>)}
      </div>
      <form className="ai-question-form" onSubmit={ask}><label className="field-label">Ask from approved course sources<textarea className="field" rows="3" minLength="3" maxLength="500" value={question} onChange={event => setQuestion(event.target.value)} placeholder="For example: How does round-robin load balancing work?" required /></label><button className="btn btn-primary" disabled={busy || !courseId}>{busy ? "Searching sources…" : "Find a cited answer"}</button></form>
      {answer && <div className={`ai-grounded-answer ${answer.answered ? "answered" : "unanswered"}`} aria-live="polite"><div className="section-title-row"><h3>{answer.answered ? "Source-backed answer" : "Not enough evidence"}</h3><span className={`pill ${answer.answered ? "pill-ok" : "pill-warning"}`}>{answer.answered ? `${answer.citations.length} citation${answer.citations.length === 1 ? "" : "s"}` : "No guess made"}</span></div><p>{answer.answer}</p>{answer.citations.map((citation, index) => <blockquote key={`${citation.source_id}-${index}`}><p>{citation.excerpt}</p><cite>[{index + 1}] {citation.title} · {citation.source_type.replaceAll("_", " ")}</cite></blockquote>)}</div>}
    </>}
    {error && <div className="error-banner" role="alert">{error}</div>}
    {message && <div className="success-banner" role="status">{message}</div>}
  </section>;
}

const cgpaStatus = {
  achievable: "Achievable",
  challenging: "Challenging",
  very_demanding: "Very demanding",
  target_already_reached: "Target currently reached",
  not_mathematically_reachable: "Not mathematically reachable",
};

export function CgpaPlannerPanel({ busy, onPlan, onRefreshERP, latestPlan, courses = [], initialGoal, gradingScale = 10, passingGrade = 4 }) {
  const [form, setForm] = useState({ grading_scale_max: gradingScale, current_cgpa: "", target_cgpa: "",
    completed_credits: "", remaining_credits: "", remaining_semesters: "", weekly_study_hours: "" });
  const [scenarioGrades, setScenarioGrades] = useState({});
  useEffect(() => {
    setForm(current => initialGoal ? { ...current, grading_scale_max: gradingScale,
      current_cgpa: initialGoal.current_cgpa, target_cgpa: initialGoal.target_cgpa,
      completed_credits: initialGoal.completed_credits, remaining_credits: initialGoal.remaining_credits,
      remaining_semesters: initialGoal.remaining_semesters, weekly_study_hours: initialGoal.weekly_study_hours } :
      { ...current, grading_scale_max: gradingScale });
    if (initialGoal?.course_scenarios) setScenarioGrades(Object.fromEntries(initialGoal.course_scenarios.map(item => [item.course_id, item.expected_grade_point])));
  }, [initialGoal, gradingScale]);
  const update = event => setForm(current => ({ ...current, [event.target.name]: event.target.value }));
  const submit = event => {
    event.preventDefault();
    onPlan({ ...Object.fromEntries(Object.entries(form).map(([key, value]) => [key, Number(value)])),
      course_scenarios: Object.entries(scenarioGrades).filter(([, value]) => value !== "" && value !== undefined)
        .map(([courseId, expected]) => ({ course_id: Number(courseId), expected_grade_point: Number(expected) })) });
  };
  const result = latestPlan?.result;
  const projection = result?.projection;
  return <section className="panel ai-cgpa-panel">
    <div className="panel-title-row"><div><p className="section-eyebrow">Student Progress Intelligence · Stage 2</p><h2>Target CGPA planner</h2></div><span className="pill pill-info">Saved private goal</span></div>
    <p>Enter values from your latest official academic record. Your institution uses a {gradingScale}-point scale with {passingGrade} as the passing grade point.</p>
    {initialGoal && <div className="cgpa-saved-goal"><span>Goal restored · last source: <strong>{initialGoal.data_source === "erp" ? "verified ERP" : "student entry"}</strong></span><button className="btn btn-soft" type="button" disabled={busy} onClick={onRefreshERP}>{busy ? "Refreshing…" : "Refresh official values from ERP"}</button></div>}
    <form className="form-grid ai-cgpa-form" onSubmit={submit}>
      <label className="field-label">Institution grading scale<input className="field" type="number" name="grading_scale_max" value={gradingScale} readOnly /></label>
      <label className="field-label">Current official CGPA<input className="field" type="number" name="current_cgpa" value={form.current_cgpa} onChange={update} min="0" max={form.grading_scale_max || 10} step="0.01" placeholder="7.20" required /></label>
      <label className="field-label">Target CGPA<input className="field" type="number" name="target_cgpa" value={form.target_cgpa} onChange={update} min="0.01" max={form.grading_scale_max || 10} step="0.01" placeholder="8.00" required /></label>
      <label className="field-label">Credits already completed<input className="field" type="number" name="completed_credits" value={form.completed_credits} onChange={update} min="0.01" max="1000" step="0.5" placeholder="80" required /></label>
      <label className="field-label">Credits still remaining<input className="field" type="number" name="remaining_credits" value={form.remaining_credits} onChange={update} min="0.01" max="1000" step="0.5" placeholder="80" required /></label>
      <label className="field-label">Semesters remaining<input className="field" type="number" name="remaining_semesters" value={form.remaining_semesters} onChange={update} min="1" max="16" step="1" placeholder="4" required /></label>
      <label className="field-label">Weekly study hours available<input className="field" type="number" name="weekly_study_hours" value={form.weekly_study_hours} onChange={update} min="1" max="112" step="0.5" placeholder="18" required /></label>
      <fieldset className="wide cgpa-scenario-fields"><legend>Current-course grade scenario (optional)</legend><p>See how expected results in this semester’s enrolled courses would affect your CGPA.</p>{courses.filter(course => course.course_type === "academic").map(course => <label className="field-label" key={course.id}>{course.code} · {course.name} <small>{course.credits ? `${course.credits} credits` : "credits not configured by faculty"}</small><input className="field" type="number" min="0" max={gradingScale} step="0.01" disabled={!course.credits} value={scenarioGrades[course.id] ?? ""} placeholder={`0–${gradingScale}`} onChange={event => setScenarioGrades(current => ({ ...current, [course.id]: event.target.value }))} /></label>)}</fieldset>
      <div className="wide ai-content-submit"><small>Your entries are planning inputs. They do not overwrite official ERP grades.</small><button className="btn btn-primary" disabled={busy}>{busy ? "Calculating…" : "Create my roadmap"}</button></div>
    </form>
    {projection && <div className="cgpa-plan-result" aria-live="polite">
      <div className="cgpa-result-header"><div><p className="section-eyebrow">Latest calculation</p><h3>{cgpaStatus[projection.status] || projection.status}</h3></div><span className={`pill ${projection.status === "not_mathematically_reachable" ? "pill-risk" : projection.status === "achievable" || projection.status === "target_already_reached" ? "pill-ok" : "pill-warning"}`}>{cgpaStatus[projection.status]}</span></div>
      <p>{projection.explanation}</p>
      <div className="cgpa-metrics"><div><small>Required average</small><strong>{projection.required_average_for_remaining_credits}</strong></div><div><small>Best possible final CGPA</small><strong>{projection.best_possible_final_cgpa}</strong></div><div><small>Credits at goal</small><strong>{projection.total_credits_at_goal}</strong></div></div>
      {result.course_scenario && <div className="cgpa-scenario-result"><h4>What-if result</h4><p>If you earn the entered grade points across {result.course_scenario.scenario_credits} configured credits, your CGPA after those courses would be <strong>{result.course_scenario.projected_cgpa_after_scenario}</strong>.</p><div className="ledger-wrap"><table className="ledger"><thead><tr><th>Course</th><th>Credits</th><th>Expected grade point</th><th>Quality points</th></tr></thead><tbody>{result.course_scenario.courses.map(course => <tr key={course.course_id}><td>{course.course_code} · {course.course}</td><td>{course.credits}</td><td>{course.expected_grade_point}</td><td>{course.quality_points}</td></tr>)}</tbody></table></div></div>}
      <div className="cgpa-plan-grid">
        <div><h4>Semester checkpoints</h4><div className="ledger-wrap"><table className="ledger"><thead><tr><th>Remaining semester</th><th>Planned SGPA</th><th>Projected CGPA</th></tr></thead><tbody>{projection.milestones.map(item => <tr key={item.remaining_semester}><td>{item.remaining_semester}</td><td>{item.planned_sgpa}</td><td>{item.projected_cgpa}</td></tr>)}</tbody></table></div></div>
        <div><h4>Weekly course priorities</h4>{result.course_priorities.length ? <div className="cgpa-course-list">{result.course_priorities.map(course => <article key={course.course_id}><div><strong>{course.course_code} · {course.course}</strong><span>{course.weekly_hours} hours/week</span></div><p>{course.evidence.join(" · ")}</p><small>{course.recommended_actions[0]}</small></article>)}</div> : <EmptyState>Enroll in courses to receive course-level priorities.</EmptyState>}</div>
      </div>
      <div className="cgpa-roadmap"><h4>How to use this roadmap</h4><ol>{result.roadmap.map(step => <li key={step}>{step}</li>)}</ol><p className="footnote">{result.official_record_notice}</p></div>
      {initialGoal?.checkpoints?.length > 0 && <div className="cgpa-checkpoints"><h4>Saved checkpoints</h4><div className="ledger-wrap"><table className="ledger"><thead><tr><th>Date</th><th>Current</th><th>Target</th><th>Required average</th><th>Source</th></tr></thead><tbody>{[...initialGoal.checkpoints].reverse().slice(0, 8).map((item, index) => <tr key={`${item.recorded_at}-${index}`}><td>{new Date(item.recorded_at).toLocaleDateString()}</td><td>{item.current_cgpa}</td><td>{item.target_cgpa}</td><td>{item.required_average}</td><td>{item.source === "erp" ? "Verified ERP" : "Student entry"}</td></tr>)}</tbody></table></div></div>}
    </div>}
  </section>;
}

export default function AIAssistantPage() {
  const { user, logout } = useAuth();
  const [command, setCommand] = useState("");
  const [actions, setActions] = useState([]);
  const [capabilities, setCapabilities] = useState(null);
  const [courses, setCourses] = useState([]);
  const [cgpaGoal, setCgpaGoal] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [history, available, managedCourses, savedGoal] = await Promise.all([apiFetch("/ai/actions"), apiFetch("/ai/capabilities"),
        apiFetch(user.role === "student" ? "/courses/enrolled" : "/courses/"),
        user.role === "student" ? apiFetch("/ai/cgpa-goal") : Promise.resolve({ goal: null })]);
      setActions(history); setCapabilities(available); setCourses(managedCourses); setCgpaGoal(savedGoal.goal);
    } catch (requestError) { setError(requestError.message); }
  }, [user.role]);
  useEffect(() => { load(); }, [load]);
  const suggestions = useMemo(() => examples[user.role] || [], [user.role]);

  const submit = async event => {
    event.preventDefault();
    if (!command.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/ai/commands", { method: "POST", body: JSON.stringify({ command: command.trim(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata" }) });
      setMessage(response.message); setActions(current => [response.action, ...current.filter(item => item.id !== response.action.id)]); setCommand("");
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const updateAction = async (id, operation) => {
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch(`/ai/actions/${id}/${operation}`, { method: "POST" });
      const action = response.action || response;
      setActions(current => current.map(item => item.id === id ? action : item));
      setMessage(response.message || (operation === "reject" ? "Draft rejected." : "Action updated."));
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const previewBulkAccounts = async records => {
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/ai/bulk-accounts/preview", { method: "POST", body: JSON.stringify({ records }) });
      setActions(current => [response.action, ...current.filter(item => item.id !== response.action.id)]);
      setMessage(response.message);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const refreshCgpaFromERP = async () => {
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/ai/cgpa-goal/refresh-erp", { method: "POST" });
      setActions(current => [response.action, ...current.filter(item => item.id !== response.action.id)]);
      const saved = await apiFetch("/ai/cgpa-goal"); setCgpaGoal(saved.goal); setMessage(response.message);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const previewContentDraft = async payload => {
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/ai/content-drafts", { method: "POST", body: JSON.stringify(payload) });
      setActions(current => [response.action, ...current.filter(item => item.id !== response.action.id)]);
      setMessage(response.message);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const correct = async (id, correctedIntent, consent) => {
    setBusy(true); setError("");
    try {
      const response = await apiFetch(`/ai/actions/${id}/correction`, { method: "POST", body: JSON.stringify({ corrected_intent: correctedIntent, corrected_payload: {}, consent }) });
      setMessage(response.message);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const createCgpaPlan = async payload => {
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await apiFetch("/ai/cgpa-plan", { method: "POST", body: JSON.stringify(payload) });
      setActions(current => [response.action, ...current.filter(item => item.id !== response.action.id)]);
      const saved = await apiFetch("/ai/cgpa-goal"); setCgpaGoal(saved.goal);
      setMessage(response.message);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  return <DashboardShell user={user} title="AI Assistant" roleLabel={roleLabels[user.role]} onLogout={logout} activePage="ai-assistant">
    <section className="ai-hero">
      <div className="ai-hero-mark"><Icon name="quiz" size={30} /></div>
      <div><p className="section-eyebrow">EKEEKRTA Native AI · Private by design</p><h2>What would you like to do?</h2><p>Commands are interpreted inside EKEEKRTA. No external model or AI API receives your data.</p></div>
      {capabilities && <span className="ai-engine-badge">{capabilities.engine}</span>}
    </section>
    <form className="panel ai-composer" onSubmit={submit}>
      <label htmlFor="ai-command">Describe the task</label>
      <textarea id="ai-command" rows="4" value={command} onChange={event => setCommand(event.target.value)} placeholder="For example: Schedule a Cloud Computing class tomorrow at 10:30 AM" maxLength="2000" />
      <div className="ai-composer-footer"><small>Write the exact course name or code when the action concerns a course.</small><button className="btn btn-primary" disabled={busy || command.trim().length < 3}>{busy ? "Working…" : "Preview with AI"}</button></div>
    </form>
    <div className="ai-suggestions" aria-label="Example commands">{suggestions.map(suggestion => <button type="button" key={suggestion} onClick={() => setCommand(suggestion)}>{suggestion}</button>)}</div>
    <CourseKnowledgePanel courses={courses} role={user.role} />
    {user.role === "student" && <CgpaPlannerPanel busy={busy} onPlan={createCgpaPlan} onRefreshERP={refreshCgpaFromERP} latestPlan={actions.find(action => action.intent === "cgpa_plan")} courses={courses} initialGoal={cgpaGoal} gradingScale={user.institution?.grading_scale_max || 10} passingGrade={user.institution?.passing_grade_point || 4} />}
    {user.role === "faculty" && <FacultyContentDraftPanel courses={courses} busy={busy} onPreview={previewContentDraft} />}
    <div className="ai-voice-note"><Icon name="alert" size={18} /><span>Voice control will be enabled only after EKEEKRTA’s own speech model is ready; browser cloud speech is intentionally not used.</span></div>
    {user.role === "admin" && <BulkAccountsPanel busy={busy} onPreview={previewBulkAccounts} />}
    {error && <div className="error-banner" role="alert">{error}</div>}
    {message && <div className="success-banner" role="status">{message}</div>}
    <section className="ai-history"><div className="section-heading"><div><p className="section-eyebrow">Audited history</p><h2>Your AI actions</h2></div></div>
      {!actions.length ? <EmptyState>No AI commands have been submitted from this account.</EmptyState> : <div className="ai-action-list">{actions.map(action => <ActionCard key={action.id} action={action} busy={busy} onConfirm={id => updateAction(id, "confirm")} onReject={id => updateAction(id, "reject")} onCorrect={correct} />)}</div>}
    </section>
  </DashboardShell>;
}
