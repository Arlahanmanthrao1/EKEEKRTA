import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import DashboardShell, { EmptyState, Icon, StatCard } from "../components/dashboard/DashboardShell";
import CourseEnrollmentPanel from "../components/dashboard/CourseEnrollmentPanel";
import { CreateAssignmentForm, CreateQuizForm, GradingPanel } from "./FacultyDashboard";
import { ScheduleForm, ScheduledClassList } from "./SchedulePage";
import ProgrammingAssessmentForm from "../components/dashboard/ProgrammingAssessmentForm";
import LectureNotesPanel from "../components/dashboard/LectureNotesPanel";
import "../styles/dashboard.css";
import "../styles/faculty-course.css";
import "../styles/programming.css";

const safeUrl = value => /^(https?:)\/\//i.test(value || "") ? value : null;
export const nextScheduledPlan = plans => [...plans]
  .filter(plan => plan.status === "scheduled")
  .sort((first, second) => new Date(first.starts_at) - new Date(second.starts_at))[0] || null;
export const shouldShowCourseHero = (sessions, plans = []) =>
  !sessions.some(session => session.ended_at) || sessions.some(session => !session.ended_at) || Boolean(nextScheduledPlan(plans));

function sessionDuration(session) {
  const started = new Date(session.scheduled_at).getTime();
  const ended = new Date(session.ended_at).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) return null;
  const minutes = Math.max(1, Math.round((ended - started) / 60000));
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

export function ClassHistory({ sessions }) {
  const completed = sessions.filter(session => session.ended_at);
  return <section className="class-history" aria-labelledby="class-history-title">
    <div className="section-title-row"><div><p className="section-eyebrow">Completed meetings</p><h2 id="class-history-title">Class history</h2></div><span className="pill pill-muted">{completed.length} ended</span></div>
    {!completed.length && <EmptyState>Ended classes will appear here automatically.</EmptyState>}
    <div className="class-history-list">{completed.map(session => <article key={session.id}>
      <div><span className="pill class-ended-pill">Ended</span><h3>Completed class</h3><p>Started {new Date(session.scheduled_at).toLocaleString()}</p></div>
      <dl><div><dt>Ended</dt><dd>{new Date(session.ended_at).toLocaleString()}</dd></div><div><dt>Duration</dt><dd>{sessionDuration(session) || "Unavailable"}</dd></div></dl>
    </article>)}</div>
  </section>;
}

function CourseCreditsEditor({ course, onSaved }) {
  const [credits, setCredits] = useState(course.credits ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const save = async event => {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await apiFetch(`/courses/${course.id}/credits`, { method: "PATCH", body: JSON.stringify({ credits: Number(credits) }) });
      setMessage("Course credits saved and synchronized to the ERP when enabled."); onSaved();
    } finally { setBusy(false); }
  };
  return <section className="card panel-card course-credit-editor" id="course-settings"><div><p className="section-eyebrow">Academic configuration</p><h2>Course credits</h2><p>Credits are used in student CGPA what-if calculations. Enter the official curriculum value.</p></div><form onSubmit={save}><label className="field-label">Official credits<input className="field" type="number" min="0.5" max="50" step="0.5" value={credits} onChange={event => setCredits(event.target.value)} required /></label><button className="btn btn-soft" disabled={busy}>{busy ? "Saving…" : "Save credits"}</button></form>{message && <p className="success-banner" role="status">{message}</p>}</section>;
}

export default function FacultyCoursePage() {
  const { courseId } = useParams();
  const id = Number(courseId);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState({ course: null, assignments: [], quizzes: [], programming: [], materials: [], plans: [], sessions: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [openTool, setOpenTool] = useState(null);
  const [grading, setGrading] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    async function load() {
      if (!Number.isInteger(id) || id < 1) { setError("Course not found."); setLoading(false); return; }
      setLoading(true); setError("");
      try {
        const courses = await apiFetch("/courses/");
        const course = courses.find(item => item.id === id);
        if (!course) throw new Error("Course not found or you do not have access.");
        const [assignments, quizzes, programming, materials, plans, sessions] = await Promise.all([
          apiFetch(`/assignments/course/${id}`), apiFetch(`/quizzes/course/${id}`),
          apiFetch(`/programming/course/${id}`), apiFetch(`/materials/course/${id}`), apiFetch("/schedule"),
          apiFetch(`/attendance/sessions/${id}?include_ended=true`),
        ]);
        if (active) setData({ course, assignments, quizzes, programming, materials, plans: plans.filter(plan => plan.course_id === id), sessions });
      } catch (error) { if (active) setError(error.message); }
      finally { if (active) setLoading(false); }
    }
    load();
    return () => { active = false; };
  }, [id, reload, user.id]);

  async function startNow() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const session = await apiFetch("/attendance/sessions", { method: "POST", body: JSON.stringify({ course_id: id }) });
      navigate("/classroom", { state: { sessionId: session.id, roomId: session.jitsi_room_id, courseId: id, courseName: data.course.name, studentId: user.id, studentName: user.name, isFaculty: true } });
    } catch (error) { setError(error.message); }
    finally { inFlight.current = false; setBusy(false); }
  }

  async function createSchedule(payload) {
    setBusy(true); setNotice("");
    try { await apiFetch("/schedule", { method: "POST", body: JSON.stringify(payload) }); setNotice("Class scheduled and added to course calendars."); setOpenTool(null); setReload(value => value + 1); }
    finally { setBusy(false); }
  }

  async function scheduleAction(plan, action) {
    if (inFlight.current) return false;
    inFlight.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const session = await apiFetch(`/schedule/${plan.id}/${action}`, { method: "POST" });
      if (action === "start") navigate("/classroom", { state: { sessionId: session.id, roomId: session.jitsi_room_id, courseId: id, courseName: data.course.name, studentId: user.id, studentName: user.name, isFaculty: true } });
      else { setNotice("Class schedule cancelled."); setReload(value => value + 1); }
      return true;
    } catch (error) { setError(error.message); return false; }
    finally { inFlight.current = false; setBusy(false); }
  }

  const refresh = () => setReload(value => value + 1);
  if (loading) return <DashboardShell user={user} title="Course workspace" roleLabel="Faculty" onLogout={logout} activePage="courses"><p role="status">Loading course workspace…</p></DashboardShell>;
  if (error && !data.course) return <DashboardShell user={user} title="Course workspace" roleLabel="Faculty" onLogout={logout} activePage="courses"><div className="error-banner" role="alert">{error}</div><Link className="btn btn-soft" to="/faculty/courses">← Back to your courses</Link></DashboardShell>;
  const { course, assignments, quizzes, programming, materials, plans, sessions } = data;
  const activeSession = sessions.find(session => !session.ended_at);
  const completedSessions = sessions.filter(session => session.ended_at);
  const upcomingPlan = nextScheduledPlan(plans);
  const heroAction = activeSession ? startNow : upcomingPlan ? () => scheduleAction(upcomingPlan, "start") : startNow;
  return <DashboardShell user={user} title={course.name} roleLabel="Faculty" onLogout={logout} activePage="courses">
    <Link className="course-back-link" to="/faculty/courses">← All courses</Link>
    {shouldShowCourseHero(sessions, plans) ? <section className="course-workspace-hero"><div><div className="course-title-line"><span className="course-code">{course.code}</span><span className="pill pill-muted">{course.course_type === "non_academic" ? "Non-Academic" : "Academic"}</span></div><h1>{course.name}</h1>{upcomingPlan && !activeSession ? <div className="course-workspace-hero-plan"><span>Next scheduled class</span><strong>{upcomingPlan.title}</strong><time dateTime={upcomingPlan.starts_at}>{new Date(upcomingPlan.starts_at).toLocaleString()}</time></div> : <p>{course.department || "Department not set"} · {course.semester || "Semester not set"}</p>}</div><button className="btn btn-primary" disabled={busy} onClick={heroAction}><Icon name="video" /> {activeSession ? "Rejoin live class" : upcomingPlan ? "Start scheduled class" : "Start a new class"}</button></section> : <header className="course-workspace-compact-title"><div><div className="course-title-line"><span className="course-code">{course.code}</span><span className="pill pill-muted">{course.course_type === "non_academic" ? "Non-Academic" : "Academic"}</span></div><h1>{course.name}</h1><p>{course.department || "Department not set"} · {course.semester || "Semester not set"}</p></div><span className="pill class-ended-pill">Latest meeting ended</span></header>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {notice && <p className="schedule-notice" role="status">{notice}</p>}
    <nav className="course-section-nav" aria-label="Course workspace sections"><a href="#course-settings">Credits</a><a href="#classes">Classes</a><a href="#lecture-notes">Lecture notes</a><a href="#assignments">Assignments</a><a href="#quizzes">Quizzes</a><a href="#programming">Programming</a><a href="#students">Students</a><a href="#materials">Notes & materials</a></nav>
    <section className="stats-grid course-stats"><StatCard icon="assignments" label="Assignments" value={assignments.length} /><StatCard icon="quiz" label="Quizzes" value={quizzes.length} tone="purple" /><StatCard icon="code" label="Programming" value={programming.length} tone="amber" /><StatCard icon="calendar" label="Scheduled classes" value={plans.filter(plan => plan.status === "scheduled").length} tone="green" /><StatCard icon="video" label="Completed classes" value={completedSessions.length} /><StatCard icon="material" label="Materials" value={materials.length} tone="amber" /></section>
    <CourseCreditsEditor course={course} onSaved={refresh} />

    <div className="course-workspace-grid">
      <section className="card panel-card course-workspace-section" id="classes"><div className="section-title-row"><div><p className="section-eyebrow">Virtual classroom</p><h2>Classes and meetings</h2></div><button className="btn btn-soft" aria-expanded={openTool === "schedule"} onClick={() => setOpenTool(openTool === "schedule" ? null : "schedule")}>Schedule class</button></div>
        <p>Start immediately or schedule a time. Students can join only after you start the meeting.</p>
        {openTool === "schedule" && <ScheduleForm key={`schedule-${id}`} courses={[course]} fixedCourse={course} busy={busy} onSubmit={createSchedule} />}
        <ScheduledClassList plans={plans} busy={busy} onStart={plan => scheduleAction(plan,"start")} onCancel={plan => scheduleAction(plan,"cancel")} />
        <ClassHistory sessions={sessions} />
      </section>

      <LectureNotesPanel courseId={id} sessions={sessions} manager />

      <section className="card panel-card course-workspace-section" id="assignments"><div className="section-title-row"><div><p className="section-eyebrow">Coursework</p><h2>Assignments and copies</h2></div><button className="btn btn-soft" aria-expanded={openTool === "assignment"} onClick={() => setOpenTool(openTool === "assignment" ? null : "assignment")}>Create assignment</button></div>
        {openTool === "assignment" && <CreateAssignmentForm key={`assignment-${id}`} courses={[course]} fixedCourse={course} onCreated={() => { setOpenTool(null); refresh(); }} />}
        {!assignments.length && <EmptyState>No assignments created for this course.</EmptyState>}
        <div className="workspace-record-list">{assignments.map(assignment => <article key={assignment.id}><div className="split-row"><div><h3>{assignment.title}</h3><p>{assignment.due_date ? `Due ${new Date(assignment.due_date).toLocaleString()}` : "No deadline"} · {assignment.max_marks} marks</p></div><button className="btn-text" onClick={() => setGrading(grading === assignment.id ? null : assignment.id)}>{grading === assignment.id ? "Hide copies" : "View copies & grade"}</button></div>{assignment.description && <p>{assignment.description}</p>}{grading === assignment.id && <GradingPanel assignment={assignment} onGraded={refresh} />}</article>)}</div>
      </section>

      <section className="card panel-card course-workspace-section" id="quizzes"><div className="section-title-row"><div><p className="section-eyebrow">Assessment</p><h2>Quizzes</h2></div><button className="btn btn-soft" aria-expanded={openTool === "quiz"} onClick={() => setOpenTool(openTool === "quiz" ? null : "quiz")}>Create quiz</button></div>
        {openTool === "quiz" && <CreateQuizForm key={`quiz-${id}`} courses={[course]} fixedCourse={course} onCreated={() => { setOpenTool(null); refresh(); }} />}
        {!quizzes.length ? <EmptyState>No quizzes created for this course.</EmptyState> : <div className="workspace-record-list">{quizzes.map(quiz => <article key={quiz.id}><h3>{quiz.title}</h3><p>{quiz.total_marks} marks · Answers remain hidden from students until submission.</p></article>)}</div>}
      </section>

      <section className="card panel-card course-workspace-section" id="programming"><div className="section-title-row"><div><p className="section-eyebrow">Code assessment</p><h2>Programming assessments</h2></div><button className="btn btn-soft" aria-expanded={openTool === "programming"} onClick={() => setOpenTool(openTool === "programming" ? null : "programming")}>Create programming assessment</button></div>
        {openTool === "programming" && <ProgrammingAssessmentForm course={course} onCreated={() => { setOpenTool(null); refresh(); }} />}
        {!programming.length ? <EmptyState>No programming assessments created for this course.</EmptyState> : <div className="workspace-record-list">{programming.map(assessment => <article key={assessment.id}><h3>{assessment.title}</h3><p>{assessment.test_count} test case{assessment.test_count === 1 ? "" : "s"} · {assessment.allowed_languages.join(", ")}</p>{assessment.description && <p>{assessment.description}</p>}</article>)}</div>}
      </section>

      <section className="card panel-card course-workspace-section" id="students"><p className="section-eyebrow">Course access</p><h2>Manage students</h2><CourseEnrollmentPanel course={course} /></section>

      <section className="card panel-card course-workspace-section" id="materials"><div><p className="section-eyebrow">Study resources</p><h2>Notes and materials</h2></div><p>Materials are uploaded by administrators and are available here for reference.</p>
        {!materials.length ? <EmptyState>No notes or study materials for this course.</EmptyState> : <div className="workspace-record-list">{materials.map(material => <article key={material.id}><div className="split-row"><div><span className="pill pill-muted">{material.material_type}</span><h3>{material.title}</h3>{material.description && <p>{material.description}</p>}</div>{safeUrl(material.file_url) ? <a className="btn btn-soft" href={material.file_url} target="_blank" rel="noreferrer">Open material</a> : <span className="pill pill-muted">Link unavailable</span>}</div></article>)}</div>}
      </section>
    </div>
  </DashboardShell>;
}
