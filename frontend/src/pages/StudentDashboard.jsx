import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import DashboardShell, { EmptyState, Icon, StatCard } from "../components/dashboard/DashboardShell";
import { useAuth } from "../context/AuthContext";
import { BrandLoading } from "../branding/Brand";
import "../styles/dashboard.css";

const ATTENDANCE_RISK_THRESHOLD = 75;

export const courseCategory = course => course?.course_type === "non_academic" ? "non_academic" : "academic";

export function QuizTaker({ quiz, onClose, onSubmitted }) {
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    try {
      const response = await apiFetch("/quizzes/attempt", {
        method: "POST",
        body: JSON.stringify({ quiz_id: quiz.id, answers }),
      });
      setResult(response);
      onSubmitted(quiz.id, response.score);
    } catch (err) { setError(err.message); }
  };

  return (
    <div className="quiz-taker">
      <div className="section-title-row">
        <div><p className="section-eyebrow">Quiz in progress</p><h4>{quiz.title}</h4></div>
        <button className="btn btn-ghost" onClick={onClose}>Close</button>
      </div>
      {result ? (
        <div className="result-banner"><Icon name="check" /> Your result: {result.correct}/{result.total} correct · {result.score.toFixed(0)}%</div>
      ) : (
        <>
          {quiz.questions.map((question, questionIndex) => (
            <fieldset key={question.id} className="quiz-question">
              <legend>{questionIndex + 1}. {question.text}</legend>
              {question.options.map((option, optionIndex) => (
                <label key={optionIndex} className="quiz-option">
                  <input type="radio" name={`question-${question.id}`} checked={answers[question.id] === optionIndex} onChange={() => setAnswers({ ...answers, [question.id]: optionIndex })} />
                  <span>{option}</span>
                </label>
              ))}
            </fieldset>
          ))}
          {error && <p className="error-banner">{error}</p>}
          <button onClick={submit} className="btn btn-primary">Submit answers</button>
        </>
      )}
    </div>
  );
}

export default function StudentDashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { page = "dashboard" } = useParams();
  const [courses, setCourses] = useState([]);
  const [allCourses, setAllCourses] = useState([]);
  const [enrolling, setEnrolling] = useState(null);
  const [sessionsByCourse, setSessionsByCourse] = useState({});
  const [attendanceByCourse, setAttendanceByCourse] = useState({});
  const [assignmentsByCourse, setAssignmentsByCourse] = useState({});
  const [quizzesByCourse, setQuizzesByCourse] = useState({});
  const [materialsByCourse, setMaterialsByCourse] = useState({});
  const [submissions, setSubmissions] = useState([]);
  const [programmingAssessments, setProgrammingAssessments] = useState([]);
  const [submitUrls, setSubmitUrls] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");

  const loadDashboard = async () => {
    try {
      const [enrolledCourses, everyCourse, assessments] = await Promise.all([apiFetch("/courses/enrolled"), apiFetch("/courses/"), apiFetch("/programming/assessments")]);
      setCourses(enrolledCourses);
      setAllCourses(everyCourse);
      setProgrammingAssessments(assessments);
      const [sessions, attendance, assignments, quizzes, materials, mySubmissions] = await Promise.all([
        Promise.all(enrolledCourses.map((course) => apiFetch(`/attendance/sessions/${course.id}`).then((data) => [course.id, data]))),
        Promise.all(enrolledCourses.map((course) => apiFetch(`/attendance/${course.id}/${user.id}`).then((data) => [course.id, data]))),
        Promise.all(enrolledCourses.map((course) => apiFetch(`/assignments/course/${course.id}`).then((data) => [course.id, data]))),
        Promise.all(enrolledCourses.map((course) => apiFetch(`/quizzes/course/${course.id}`).then((data) => [course.id, data]))),
        Promise.all(enrolledCourses.map((course) => apiFetch(`/materials/course/${course.id}`).then((data) => [course.id, data]))),
        apiFetch("/assignments/submissions/me"),
      ]);
      setSessionsByCourse(Object.fromEntries(sessions));
      setAttendanceByCourse(Object.fromEntries(attendance));
      setAssignmentsByCourse(Object.fromEntries(assignments));
      setQuizzesByCourse(Object.fromEntries(quizzes));
      setMaterialsByCourse(Object.fromEntries(materials));
      setSubmissions(mySubmissions);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (user) loadDashboard(); }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!courses.length) return undefined;
    const interval = window.setInterval(async () => {
      try {
        const entries = await Promise.all(courses.map((course) => apiFetch(`/attendance/sessions/${course.id}`).then((data) => [course.id, data])));
        setSessionsByCourse(Object.fromEntries(entries));
      } catch { /* A missed poll can safely wait for the next refresh. */ }
    }, 6000);
    return () => window.clearInterval(interval);
  }, [courses]);

  const enroll = async (courseId) => {
    setEnrolling(courseId);
    setError("");
    setNotice("");
    try {
      const course = allCourses.find((entry) => entry.id === courseId);
      await apiFetch(`/courses/${courseId}/enroll`, { method: "POST" });
      await loadDashboard();
      setNotice(`${course?.name || "Subject"} was added to your courses.`);
    }
    catch (err) { setError(err.message); }
    finally { setEnrolling(null); }
  };

  const attendancePercent = (courseId) => {
    const records = attendanceByCourse[courseId] || [];
    return records.length ? Math.round((records.filter((record) => record.present).length / records.length) * 100) : null;
  };

  const joinSession = (course, session) => navigate("/classroom", { state: {
    sessionId: session.id, roomId: session.jitsi_room_id, courseId: course.id, courseName: course.name,
    studentId: user.id, studentName: user.name, isFaculty: false,
  } });

  const submissionFor = (assignmentId) => submissions.find((submission) => submission.assignment_id === assignmentId);
  const submitAssignment = async (assignmentId) => {
    const fileUrl = submitUrls[assignmentId];
    if (!fileUrl) return;
    try {
      const submission = await apiFetch("/assignments/submit", { method: "POST", body: JSON.stringify({ assignment_id: assignmentId, file_url: fileUrl }) });
      setSubmissions([...submissions, submission]);
      setSubmitUrls({ ...submitUrls, [assignmentId]: "" });
    } catch (err) { setError(err.message); }
  };
  const allAssignments = Object.values(assignmentsByCourse).flat();
  const allQuizzes = Object.values(quizzesByCourse).flat();
  const attendanceRecords = Object.values(attendanceByCourse).flat();
  const overallAttendance = attendanceRecords.length ? Math.round((attendanceRecords.filter((record) => record.present).length / attendanceRecords.length) * 100) : null;
  const pendingAssignments = allAssignments.filter((assignment) => !submissionFor(assignment.id));
  const activeClasses = courses.flatMap((course) => (sessionsByCourse[course.id] || []).filter((session) => !session.ended_at).map((session) => ({ course, session })));
  const enrolledIds = new Set(courses.map((course) => course.id));
  const availableCourses = allCourses.filter((course) => !enrolledIds.has(course.id));
  const matchesSearch = (course) => `${course.name} ${course.code} ${course.department || ""}`.toLowerCase().includes(search.toLowerCase());
  const shownCourses = useMemo(() => courses.filter(course => matchesSearch(course) &&
    (!['syllabus', 'notes', 'study-materials'].includes(page) || courseCategory(course) === "academic")), [courses, search, page]); // eslint-disable-line react-hooks/exhaustive-deps
  const academicCourses = courses.filter(course => courseCategory(course) === "academic");
  const nonAcademicCourses = courses.filter(course => courseCategory(course) === "non_academic");
  const shownAcademicCourses = academicCourses.filter(matchesSearch);
  const shownNonAcademicCourses = nonAcademicCourses.filter(matchesSearch);
  const availableAcademicCourses = availableCourses.filter(course => courseCategory(course) === "academic");
  const availableNonAcademicCourses = availableCourses.filter(course => courseCategory(course) === "non_academic");
  const shownAvailableCourses = availableCourses.filter(matchesSearch);
  const activeAcademicClasses = activeClasses.filter(({ course }) => courseCategory(course) === "academic");
  const activeNonAcademicClasses = activeClasses.filter(({ course }) => courseCategory(course) === "non_academic");
  const courseById = new Map(courses.map((course) => [course.id, course]));
  const assignmentById = new Map(allAssignments.map((assignment) => [assignment.id, assignment]));
  const gradedResults = submissions.map((submission) => ({ submission, assignment: assignmentById.get(submission.assignment_id) }))
    .filter(({ submission, assignment }) => assignment && submission.marks_obtained != null);
  const nonAcademicGradedResults = gradedResults.filter(({ assignment }) => courseCategory(courseById.get(assignment.course_id)) === "non_academic");
  const materialPage = ["syllabus", "notes", "study-materials"].includes(page);
  const materialFilter = (material) => {
    const type = (material.material_type || "").toLowerCase();
    if (page === "syllabus") return type.includes("syllabus");
    if (page === "notes") return type.includes("note");
    return true;
  };
  const nonAcademicPages = new Set(["weekly-tests", "leaderboard"]);
  const nonAcademicTitles = {
    "non-academic-courses": "Non-academic courses",
    "non-academic-assignments": "Non-academic assignments",
    "weekly-tests": "Weekly tests",
    "non-academic-quizzes": "Non-academic quizzes",
    "non-academic-marks": "Non-academic marks",
    leaderboard: "Leader Board · Top 10",
  };

  const renderCourseCatalogue = (eyebrow, listedCourses, available, liveClasses) => { const shownAvailable = available.filter(matchesSearch); return <div className="content-grid"><section className="section"><p className="section-eyebrow">{eyebrow}</p><h2 className="section-title">My courses</h2>{liveClasses.map(({ course, session }) => <div className="active-class-card" key={session.id}><span className="active-class-icon"><Icon name="video" /></span><div><span className="pill pill-live">Live now</span><h3>{course.name}</h3><p>{course.code} · Attendance starts when you enter</p></div><button className="btn btn-primary" onClick={() => joinSession(course, session)}>Join now</button></div>)}{!listedCourses.length && <EmptyState>{search ? `No ${eyebrow.toLowerCase()} course matches your search.` : `You are not enrolled in an ${eyebrow.toLowerCase()} course yet.`}</EmptyState>}<div className="course-list">{listedCourses.map((course) => { const percentage = attendancePercent(course.id); const atRisk = percentage !== null && percentage < ATTENDANCE_RISK_THRESHOLD; const assignments = assignmentsByCourse[course.id] || []; const quizzes = quizzesByCourse[course.id] || []; const materials = materialsByCourse[course.id] || []; return <article className="card course-card" key={course.id}><div className="course-row"><div><span className="course-name">{course.name}</span><span className="course-code">{course.code}</span><div className="course-meta"><span>{course.department || "Department not set"}</span><span>{course.semester || "Semester not set"}</span></div></div><span className={`pill ${atRisk ? "pill-risk" : percentage === null ? "pill-muted" : "pill-ok"}`}>{percentage === null ? "No attendance yet" : `${percentage}% attendance${atRisk ? " · at risk" : ""}`}</span></div><div className="course-card-footer"><p className="footnote">{assignments.length} assignments · {quizzes.length} quizzes · {materials.length} resources</p><Link className="btn btn-primary" to={`/student/courses/${course.id}`}>Open course →</Link></div></article>; })}</div></section><aside className="content-stack"><section className="card panel-card"><div className="section-title-row"><h3>Available subjects</h3><Icon name="courses" /></div>{!shownAvailable.length && <p className="footnote">{search ? `No available ${eyebrow.toLowerCase()} subject matches your search.` : `No other ${eyebrow.toLowerCase()} subjects match your cohort.`}</p>}{shownAvailable.map((course) => <div className="item-row split-row" key={course.id}><div><strong>{course.name}</strong><div className="footnote">{course.code} · {course.enrollment_mode === "compulsory" ? "Required" : "Elective"}</div></div><button className="btn btn-soft" disabled={enrolling === course.id} onClick={() => enroll(course.id)}>{enrolling === course.id ? "Adding…" : "Enroll"}</button></div>)}<Link className="btn-text" to="/student/subject-enrollment">Open subject enrollment →</Link></section></aside></div>; };

  const renderSubjectEnrollment = () => <section className="section subject-enrollment-page"><p className="section-eyebrow">Academics</p><div className="section-title-row"><div><h2 className="section-title">Subject enrollment</h2><p className="section-description">Choose from the real subjects available for your department, program, batch, semester and section.</p></div><span className="pill pill-muted">{shownAvailableCourses.length} available</span></div><div className="card panel-card cohort-summary"><strong>Your academic cohort</strong><div className="course-meta"><span>{user.department || "Department not set"}</span><span>{user.program || "Program not set"}</span><span>{user.batch || "Batch not set"}</span><span>{user.semester_number ? `Semester ${user.semester_number}` : "Semester not set"}</span><span>{user.section ? `Section ${user.section}` : "Section not set"}</span></div></div>{!shownAvailableCourses.length && <EmptyState>{search ? "No available subject matches your search." : "There are no additional subjects for your cohort. Required subjects are enrolled automatically; an elective appears here after faculty creates it for your cohort."}</EmptyState>}<div className="course-list enrollment-course-list">{shownAvailableCourses.map((course) => <article className="card course-card" key={course.id}><div className="course-row"><div><div className="course-title-line"><span className="course-name">{course.name}</span><span className="pill pill-muted">{course.course_type === "non_academic" ? "Non-Academic" : "Academic"}</span></div><span className="course-code">{course.code}</span><div className="course-meta"><span>{course.department || "All departments"}</span><span>{course.program || "All programs"}</span><span>{course.semester_number ? `Semester ${course.semester_number}` : "All semesters"}</span><span>{course.enrollment_mode === "compulsory" ? "Required subject" : "Elective subject"}</span></div></div><button className="btn btn-primary" disabled={enrolling === course.id} onClick={() => enroll(course.id)}>{enrolling === course.id ? "Enrolling…" : "Enroll subject"}</button></div></article>)}</div>{courses.length > 0 && <div className="card panel-card enrolled-summary"><div className="section-title-row"><h3>Already enrolled</h3><span className="pill pill-ok">{courses.length}</span></div><div className="course-meta">{courses.map((course) => <span key={course.id}>{course.code} · {course.name}</span>)}</div></div>}</section>;

  const renderAssignmentCourses = (eyebrow, listedCourses) => <section className="section"><p className="section-eyebrow">{eyebrow}</p><h2 className="section-title">Course assignments</h2>{!listedCourses.length && <EmptyState>{search ? "No enrolled course matches your search." : `You are not enrolled in an ${eyebrow.toLowerCase()} course yet.`}</EmptyState>}<div className="course-list">{listedCourses.map((course) => { const assignments = assignmentsByCourse[course.id] || []; return <article className="card course-card" key={course.id}><div className="course-row"><div><span className="course-name">{course.name}</span><span className="course-code">{course.code}</span></div><Link className="btn btn-soft" to={`/student/courses/${course.id}`}>Open course</Link></div>{!assignments.length && <p className="footnote">Nothing posted yet.</p>}{assignments.map((assignment) => { const mine = submissionFor(assignment.id); return <div className="item-row" key={assignment.id}><div className="split-row"><span>{assignment.title}</span>{mine && <span className={`pill ${mine.marks_obtained != null ? "pill-ok" : "pill-muted"}`}>{mine.marks_obtained != null ? `${mine.marks_obtained}/${assignment.max_marks}` : "Awaiting grade"}</span>}</div>{!mine && <div className="inline-submit"><input className="field" type="url" placeholder="Paste your file URL" value={submitUrls[assignment.id] || ""} onChange={(event) => setSubmitUrls({ ...submitUrls, [assignment.id]: event.target.value })} /><button className="btn btn-soft" onClick={() => submitAssignment(assignment.id)}>Submit</button></div>}</div>; })}</article>; })}</div></section>;

  if (loading) return <BrandLoading>Preparing your dashboard…</BrandLoading>;

  return (
    <DashboardShell user={user} title="Student Hub" roleLabel="Student" onLogout={logout} searchValue={search} onSearch={setSearch} searchPlaceholder="Search your courses…">
      {page === "dashboard" && <section className="page-hero" id="dashboard">
        <div><h1>Good day, {user.name}! <span className="wave">👋</span></h1><p>Here’s what’s happening across your courses.</p></div>
        {activeClasses[0] && <button className="btn btn-primary hero-button" onClick={() => joinSession(activeClasses[0].course, activeClasses[0].session)}><Icon name="video" /> Join active class</button>}
      </section>}
      {error && <p className="error-banner">{error}</p>}
      {notice && <p className="success-banner" role="status">{notice}</p>}
      {page === "dashboard" && <section className="stats-grid" aria-label="Student overview">
        <StatCard icon="courses" label="Enrolled courses" value={courses.length} tone="blue" />
        <StatCard icon="check" label="Overall attendance" value={overallAttendance === null ? "—" : `${overallAttendance}%`} tone="green" detail="Target: 75%" />
        <StatCard icon="assignments" label="Pending assignments" value={pendingAssignments.length} tone="red" />
        <StatCard icon="quiz" label="Available quizzes" value={allQuizzes.length} tone="amber" />
      </section>}
      {page === "dashboard" && <><div className="page-actions"><Link className="btn btn-primary" to="/student/academic-courses">Open my courses</Link><Link className="btn btn-soft" to="/student/subject-enrollment">Enroll subjects</Link><Link className="btn btn-soft" to="/student/academic-assignments">View assignments</Link><Link className="btn btn-soft" to="/student/study-materials">Study material</Link></div><div className="content-grid"><section className="section"><h2 className="section-title">Live classes</h2>{!activeClasses.length && <EmptyState>No classes are live right now.</EmptyState>}{activeClasses.map(({ course, session }) => <div className="active-class-card" key={session.id}><div><span className="pill pill-live">Live now</span><h3>{course.name}</h3></div><button className="btn btn-primary" onClick={() => joinSession(course, session)}>Join now</button></div>)}</section><aside className="content-stack"><section className="card panel-card profile-card"><div className="profile-card-avatar">{user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</div><h3>{user.name}</h3><p>{user.email}</p><span className="pill pill-muted">{user.department || "Department not set"}</span></section><section className="card panel-card"><div className="section-title-row"><h3>Attendance overview</h3><Icon name="chart" /></div><div className="attendance-number">{overallAttendance === null ? "—" : `${overallAttendance}%`}</div><div className="split-row footnote"><span>Overall attendance</span><span>Target 75%</span></div><div className="progress-track"><div className={`progress-fill ${overallAttendance !== null && overallAttendance < 75 ? "risk" : ""}`} style={{ width: `${overallAttendance || 0}%` }} /></div></section></aside></div></>}

      {page === "notifications" && <section className="section"><p className="section-eyebrow">Updates from your enrolled courses</p><h2 className="section-title">Notifications</h2><div className="card panel-card">{!activeClasses.length && !pendingAssignments.length && !allQuizzes.length && <EmptyState>You have no current course notifications.</EmptyState>}{activeClasses.map(({ course, session }) => <div className="item-row split-row" key={`live-${session.id}`}><div><strong>{course.name} is live</strong><div className="footnote">Join now to begin attendance tracking.</div></div><button className="btn btn-primary" onClick={() => joinSession(course, session)}>Join</button></div>)}{pendingAssignments.map((assignment) => <div className="item-row" key={`assignment-${assignment.id}`}><strong>Assignment: {assignment.title}</strong><div className="footnote">{courseById.get(assignment.course_id)?.name || "Enrolled course"}</div></div>)}{allQuizzes.map((quiz) => <div className="item-row" key={`quiz-${quiz.id}`}><strong>Quiz available: {quiz.title}</strong><div className="footnote">{courseById.get(quiz.course_id)?.name || "Enrolled course"}</div></div>)}</div></section>}

      {page === "attendance" && <section className="section"><p className="section-eyebrow">Recorded class sessions</p><h2 className="section-title">Attendance</h2>{!shownCourses.length && <EmptyState>{search ? "No enrolled course matches your search." : "You are not enrolled in a course yet."}</EmptyState>}<div className="course-list">{shownCourses.map((course) => { const records = attendanceByCourse[course.id] || []; const present = records.filter((record) => record.present).length; const percentage = attendancePercent(course.id); const atRisk = percentage !== null && percentage < ATTENDANCE_RISK_THRESHOLD; return <article className="card course-card" key={course.id}><div className="course-row"><div><span className="course-name">{course.name}</span><span className="course-code">{course.code}</span></div><span className={`pill ${atRisk ? "pill-risk" : percentage === null ? "pill-muted" : "pill-ok"}`}>{percentage === null ? "No attendance yet" : `${percentage}%${atRisk ? " · at risk" : ""}`}</span></div><div className="split-row footnote"><span>{present} attended</span><span>{Math.max(records.length - present, 0)} missed · {records.length} recorded</span></div><div className="progress-track"><div className={`progress-fill ${atRisk ? "risk" : ""}`} style={{ width: `${percentage || 0}%` }} /></div></article>; })}</div></section>}

      {page === "marks" && <section className="section"><p className="section-eyebrow">Published results only</p><h2 className="section-title">Marks</h2><div className="card panel-card">{!gradedResults.length && <EmptyState>No assignment marks have been published yet.</EmptyState>}{gradedResults.map(({ submission, assignment }) => <div className="item-row split-row" key={submission.id}><div><strong>{assignment.title}</strong><div className="footnote">{courseById.get(assignment.course_id)?.name || "Enrolled course"}</div></div><span className="pill pill-ok">{submission.marks_obtained}/{assignment.max_marks}</span></div>)}</div></section>}

      {page === "academic-courses" && renderCourseCatalogue("Academics", shownAcademicCourses, availableAcademicCourses, activeAcademicClasses)}

      {page === "subject-enrollment" && renderSubjectEnrollment()}

      {page === "academic-assignments" && renderAssignmentCourses("Academics", shownAcademicCourses)}

      {page === "non-academic-courses" && renderCourseCatalogue("Non Academics", shownNonAcademicCourses, availableNonAcademicCourses, activeNonAcademicClasses)}

      {page === "non-academic-assignments" && renderAssignmentCourses("Non Academics", shownNonAcademicCourses)}

      {page === "non-academic-quizzes" && <section className="section"><p className="section-eyebrow">Non Academics</p><h2 className="section-title">Course quizzes</h2>{!shownNonAcademicCourses.length && <EmptyState>No non-academic courses match your search.</EmptyState>}<div className="course-list">{shownNonAcademicCourses.map(course => <article className="card course-card" key={course.id}><div className="course-row"><div><span className="course-name">{course.name}</span><span className="course-code">{course.code}</span></div><Link className="btn btn-primary" to={`/student/courses/${course.id}`}>Open quizzes →</Link></div><p className="footnote">{(quizzesByCourse[course.id] || []).length} quiz{(quizzesByCourse[course.id] || []).length === 1 ? "" : "zes"} available</p></article>)}</div></section>}

      {page === "non-academic-marks" && <section className="section"><p className="section-eyebrow">Non Academics</p><h2 className="section-title">Published marks</h2><div className="card panel-card">{!nonAcademicGradedResults.length && <EmptyState>No non-academic marks have been published yet.</EmptyState>}{nonAcademicGradedResults.map(({ submission, assignment }) => <div className="item-row split-row" key={submission.id}><div><strong>{assignment.title}</strong><div className="footnote">{courseById.get(assignment.course_id)?.name}</div></div><span className="pill pill-ok">{submission.marks_obtained}/{assignment.max_marks}</span></div>)}</div></section>}

      {page === "programming-assessments" && <section className="section"><p className="section-eyebrow">Non Academics</p><h2 className="section-title">Programming Assessments</h2><p className="section-description">Write and run code, then submit it against the assessment test cases.</p>{!programmingAssessments.length && <EmptyState>No programming assessments have been published for your enrolled courses.</EmptyState>}<div className="course-list">{programmingAssessments.map(assessment => <article className="card course-card" key={assessment.id}><div className="course-row"><div><span className="course-name">{assessment.title}</span><span className="course-code">{assessment.course_code}</span><div className="course-meta"><span>{assessment.course_name}</span><span>{assessment.test_count} test case{assessment.test_count === 1 ? "" : "s"}</span><span>{assessment.allowed_languages.join(", ")}</span></div></div><Link className="btn btn-primary" to={`/student/programming-assessments/${assessment.id}`}>Open compiler →</Link></div>{assessment.description && <p>{assessment.description}</p>}</article>)}</div></section>}

      {materialPage && <section className="section"><p className="section-eyebrow">Academics</p><h2 className="section-title">{{ syllabus: "Syllabus", notes: "Notes", "study-materials": "Study Material" }[page]}</h2>{!shownCourses.length && <EmptyState>{search ? "No enrolled course matches your search." : "You are not enrolled in a course yet."}</EmptyState>}<div className="course-list">{shownCourses.map((course) => { const materials = (materialsByCourse[course.id] || []).filter(materialFilter); return <article className="card course-card" key={course.id}><div className="course-row"><div><span className="course-name">{course.name}</span><span className="course-code">{course.code}</span></div></div>{!materials.length && <p className="footnote">No {page === "study-materials" ? "study material" : page} uploaded for this course yet.</p>}<div className="material-links">{materials.map((material) => <a key={material.id} href={material.file_url} target="_blank" rel="noreferrer"><Icon name="material" size={16} /><span>{material.title}</span><small>{material.material_type}</small></a>)}</div></article>; })}</div></section>}

      {nonAcademicPages.has(page) && <section className="section"><p className="section-eyebrow">Non Academics</p><h2 className="section-title">{nonAcademicTitles[page]}</h2><div className="card panel-card"><EmptyState>No {nonAcademicTitles[page].toLowerCase()} have been configured for your institution yet.</EmptyState></div></section>}

      {page === "ai-assistant" && <section className="section"><p className="section-eyebrow">AI Assistant</p><h2 className="section-title">Learning assistant</h2><div className="card panel-card"><EmptyState>The AI Assistant is not connected in the current build. When an approved AI service is configured, this page will provide course-aware assistance.</EmptyState></div></section>}
    </DashboardShell>
  );
}
