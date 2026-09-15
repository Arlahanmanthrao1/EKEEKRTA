import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import DashboardShell, { EmptyState, Icon, StatCard } from "../components/dashboard/DashboardShell";
import { QuizTaker } from "./StudentDashboard";
import LectureNotesPanel from "../components/dashboard/LectureNotesPanel";
import "../styles/dashboard.css";
import "../styles/faculty-course.css";

const safeUrl = value => /^(https?:)\/\//i.test(value || "") ? value : null;
const materialType = material => (material.material_type || "").toLowerCase();

export function studentMaterialGroups(materials) {
  const notes = materials.filter(material => materialType(material) === "notes");
  const pyqs = materials.filter(material => ["pyq", "previous year questions", "previous-year questions"].includes(materialType(material)));
  return {
    notes,
    pyqs,
    other: materials.filter(material => !notes.includes(material) && !pyqs.includes(material)),
  };
}

function MaterialSection({ id, eyebrow, title, materials, emptyText }) {
  return <section className="card panel-card course-workspace-section" id={id}>
    <p className="section-eyebrow">{eyebrow}</p><h2>{title}</h2>
    {!materials.length ? <EmptyState>{emptyText}</EmptyState> : <div className="workspace-record-list">{materials.map(material => <article key={material.id}><div className="split-row"><div><span className="pill pill-muted">{material.material_type}</span><h3>{material.title}</h3>{material.description && <p>{material.description}</p>}</div>{safeUrl(material.file_url) ? <a className="btn btn-soft" href={material.file_url} target="_blank" rel="noreferrer">Open resource</a> : <span className="pill pill-muted">Link unavailable</span>}</div></article>)}</div>}
  </section>;
}

export default function StudentCoursePage() {
  const { courseId } = useParams();
  const id = Number(courseId);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState({ course: null, assignments: [], quizzes: [], materials: [], sessions: [], attendance: [], submissions: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitUrls, setSubmitUrls] = useState({});
  const [submitting, setSubmitting] = useState(null);
  const [activeQuiz, setActiveQuiz] = useState(null);
  const [completedQuizzes, setCompletedQuizzes] = useState({});

  useEffect(() => {
    let active = true;
    async function load() {
      if (!Number.isInteger(id) || id < 1) { setError("Course not found."); setLoading(false); return; }
      setLoading(true); setError("");
      try {
        const courses = await apiFetch("/courses/enrolled");
        const course = courses.find(item => item.id === id);
        if (!course) throw new Error("Course not found or you are not enrolled in it.");
        const [assignments, quizzes, materials, sessions, attendance, submissions] = await Promise.all([
          apiFetch(`/assignments/course/${id}`), apiFetch(`/quizzes/course/${id}`),
          apiFetch(`/materials/course/${id}`), apiFetch(`/attendance/sessions/${id}?include_ended=true`),
          apiFetch(`/attendance/${id}/${user.id}`), apiFetch("/assignments/submissions/me"),
        ]);
        if (active) setData({ course, assignments, quizzes, materials, sessions, attendance, submissions: submissions.filter(submission => assignments.some(assignment => assignment.id === submission.assignment_id)) });
      } catch (loadError) { if (active) setError(loadError.message); }
      finally { if (active) setLoading(false); }
    }
    load();
    return () => { active = false; };
  }, [id, user.id]);

  useEffect(() => {
    if (!data.course) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const sessions = await apiFetch(`/attendance/sessions/${id}?include_ended=true`);
        setData(current => ({ ...current, sessions }));
      } catch { /* The next poll can recover from a temporary connection failure. */ }
    }, 6000);
    return () => window.clearInterval(timer);
  }, [data.course, id]);

  const submissionFor = assignmentId => data.submissions.find(submission => submission.assignment_id === assignmentId);
  const submitAssignment = async assignmentId => {
    const fileUrl = submitUrls[assignmentId];
    if (!fileUrl) return;
    setSubmitting(assignmentId); setError("");
    try {
      const submission = await apiFetch("/assignments/submit", { method: "POST", body: JSON.stringify({ assignment_id: assignmentId, file_url: fileUrl }) });
      setData(current => ({ ...current, submissions: [...current.submissions, submission] }));
      setSubmitUrls(current => ({ ...current, [assignmentId]: "" }));
    } catch (submitError) { setError(submitError.message); }
    finally { setSubmitting(null); }
  };
  const openQuiz = async quiz => {
    setError("");
    try { setActiveQuiz(await apiFetch(`/quizzes/${quiz.id}`)); }
    catch (quizError) { setError(quizError.message); }
  };

  if (loading) return <DashboardShell user={user} title="Course" roleLabel="Student" onLogout={logout} activePage="academic-courses"><p role="status">Loading course…</p></DashboardShell>;
  if (!data.course) return <DashboardShell user={user} title="Course" roleLabel="Student" onLogout={logout} activePage="academic-courses"><div className="error-banner" role="alert">{error || "Course not found."}</div><Link className="btn btn-soft" to="/student/academic-courses">← Back to my courses</Link></DashboardShell>;

  const { course, assignments, quizzes, materials, sessions, attendance } = data;
  const activeSession = sessions.find(session => !session.ended_at);
  const presentCount = attendance.filter(record => record.present).length;
  const attendancePercent = attendance.length ? Math.round((presentCount / attendance.length) * 100) : null;
  const materialGroups = studentMaterialGroups(materials);
  const courseListPage = course.course_type === "non_academic" ? "non-academic-courses" : "academic-courses";
  const courseTypeLabel = course.course_type === "non_academic" ? "Non-Academic" : "Academic";
  const joinClass = () => navigate("/classroom", { state: { sessionId: activeSession.id, roomId: activeSession.jitsi_room_id, courseId: course.id, courseName: course.name, studentId: user.id, studentName: user.name, isFaculty: false } });

  return <DashboardShell user={user} title={course.name} roleLabel="Student" onLogout={logout} activePage={courseListPage}>
    <Link className="course-back-link" to={`/student/${courseListPage}`}>← All {courseTypeLabel.toLowerCase()} courses</Link>
    <section className="course-workspace-hero"><div><div className="course-title-line"><span className="course-code">{course.code}</span><span className="pill pill-muted">{courseTypeLabel}</span></div><h1>{course.name}</h1><p>{course.department || "Department not set"} · {course.semester || "Semester not set"}</p></div>{activeSession && <button className="btn btn-primary" onClick={joinClass}><Icon name="video" /> Join live class</button>}</section>
    {error && <p className="error-banner" role="alert">{error}</p>}
    <nav className="course-section-nav" aria-label="Course sections"><a href="#assignments">Assignments</a><a href="#quizzes">Quizzes</a><a href="#lecture-notes">Lecture notes</a><a href="#notes">Notes</a><a href="#pyqs">PYQs</a><a href="#materials">Other material</a></nav>
    <section className="stats-grid course-stats"><StatCard icon="assignments" label="Assignments" value={assignments.length} /><StatCard icon="quiz" label="Quizzes" value={quizzes.length} tone="purple" /><StatCard icon="material" label="Notes" value={materialGroups.notes.length} tone="green" /><StatCard icon="material" label="PYQs" value={materialGroups.pyqs.length} tone="amber" /><StatCard icon="check" label="Attendance" value={attendancePercent === null ? "—" : `${attendancePercent}%`} tone={attendancePercent !== null && attendancePercent < 75 ? "red" : "blue"} /></section>

    <div className="course-workspace-grid">
      <section className="card panel-card course-workspace-section" id="assignments"><p className="section-eyebrow">Coursework</p><h2>Assignments</h2>{!assignments.length && <EmptyState>No assignments posted for this course.</EmptyState>}<div className="workspace-record-list">{assignments.map(assignment => { const submission = submissionFor(assignment.id); return <article key={assignment.id}><div className="split-row"><div><h3>{assignment.title}</h3><p>{assignment.due_date ? `Due ${new Date(assignment.due_date).toLocaleString()}` : "No deadline"} · {assignment.max_marks} marks</p></div>{submission && <span className={`pill ${submission.marks_obtained != null ? "pill-ok" : "pill-muted"}`}>{submission.marks_obtained != null ? `${submission.marks_obtained}/${assignment.max_marks}` : "Awaiting grade"}</span>}</div>{assignment.description && <p>{assignment.description}</p>}{!submission && <div className="inline-submit"><input className="field" type="url" aria-label={`File URL for ${assignment.title}`} placeholder="Paste your file URL" value={submitUrls[assignment.id] || ""} onChange={event => setSubmitUrls(current => ({ ...current, [assignment.id]: event.target.value }))} /><button className="btn btn-primary" disabled={submitting === assignment.id || !submitUrls[assignment.id]} onClick={() => submitAssignment(assignment.id)}>{submitting === assignment.id ? "Submitting…" : "Submit assignment"}</button></div>}</article>; })}</div></section>

      <section className="card panel-card course-workspace-section" id="quizzes"><p className="section-eyebrow">Assessment</p><h2>Quizzes</h2>{!quizzes.length && <EmptyState>No quizzes posted for this course.</EmptyState>}<div className="workspace-record-list">{quizzes.map(quiz => <article key={quiz.id}><div className="split-row"><div><h3>{quiz.title}</h3><p>{quiz.total_marks} marks</p></div>{completedQuizzes[quiz.id] !== undefined ? <span className="pill pill-ok">{completedQuizzes[quiz.id].toFixed(0)}%</span> : <button className="btn btn-soft" onClick={() => openQuiz(quiz)}>Take quiz</button>}</div>{activeQuiz?.id === quiz.id && <QuizTaker quiz={activeQuiz} onClose={() => setActiveQuiz(null)} onSubmitted={(quizId, score) => setCompletedQuizzes(current => ({ ...current, [quizId]: score }))} />}</article>)}</div></section>

      <LectureNotesPanel courseId={id} sessions={sessions} />

      <MaterialSection id="notes" eyebrow="Study resources" title="Notes" materials={materialGroups.notes} emptyText="No notes uploaded for this course." />
      <MaterialSection id="pyqs" eyebrow="Exam preparation" title="Previous Year Questions (PYQs)" materials={materialGroups.pyqs} emptyText="No previous-year questions uploaded for this course." />
      <MaterialSection id="materials" eyebrow="Additional resources" title="Other study material" materials={materialGroups.other} emptyText="No additional study material uploaded for this course." />
    </div>
  </DashboardShell>;
}
