import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import DashboardShell, { EmptyState, Icon, StatCard } from "../components/dashboard/DashboardShell";
import { useAuth } from "../context/AuthContext";
import { BrandLoading } from "../branding/Brand";
import "../styles/dashboard.css";

export default function HodDashboard() {
  const { user, logout } = useAuth();
  const { page = "dashboard" } = useParams();
  const [users, setUsers] = useState([]);
  const [courses, setCourses] = useState([]);
  const [summaries, setSummaries] = useState({});
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [allUsers, allCourses] = await Promise.all([apiFetch("/users/"), apiFetch("/courses/")]);
        const department = (user.department || "").toLowerCase();
        const departmentUsers = department ? allUsers.filter((entry) => (entry.department || "").toLowerCase() === department) : [];
        const departmentCourses = department ? allCourses.filter((course) => (course.department || "").toLowerCase() === department) : [];
        const students = departmentUsers.filter((entry) => entry.role === "student");
        const attendanceEntries = await Promise.all(students.map((student) => apiFetch(`/attendance/summary/${student.id}`).then((summary) => [student.id, summary])));
        setUsers(departmentUsers);
        setCourses(departmentCourses);
        setSummaries(Object.fromEntries(attendanceEntries));
      } catch (err) { setError(err.message); }
      finally { setLoading(false); }
    }
    load();
  }, [user.department]);

  const students = users.filter((entry) => entry.role === "student");
  const faculty = users.filter((entry) => entry.role === "faculty");
  const percentages = students.map((student) => summaries[student.id]?.percent).filter((value) => value !== null && value !== undefined);
  const average = percentages.length ? Math.round(percentages.reduce((sum, value) => sum + value, 0) / percentages.length) : null;
  const atRisk = students.filter((student) => summaries[student.id]?.percent !== null && summaries[student.id]?.percent !== undefined && summaries[student.id].percent < 75);
  const aboveNinety = percentages.filter((value) => value >= 90).length;
  const onTrack = percentages.filter((value) => value >= 75 && value < 90).length;
  const belowTarget = percentages.filter((value) => value < 75).length;
  const percentageOfRecorded = (count) => percentages.length ? Math.round((count / percentages.length) * 100) : 0;
  const facultyById = Object.fromEntries(faculty.map((member) => [member.id, member]));
  const filteredAtRisk = useMemo(() => atRisk.filter((student) => `${student.name} ${student.email}`.toLowerCase().includes(search.toLowerCase())), [atRisk, search]);
  const filteredCourses = useMemo(() => courses.filter((course) => `${course.name} ${course.code}`.toLowerCase().includes(search.toLowerCase())), [courses, search]);

  if (loading) return <BrandLoading>Preparing the department overview…</BrandLoading>;

  return (
    <DashboardShell user={user} title="Department portal" roleLabel="HOD Dashboard" onLogout={logout} searchValue={search} onSearch={setSearch} searchPlaceholder="Search students and courses…">
      {page === "dashboard" && (<section className="page-hero" id="dashboard"><div><h1>Good day, {user.name}! <span className="wave">👋</span></h1><p>Here is your {user.department || "department"} academic overview.</p></div><span className="sync-badge"><Icon name="check" size={15} /> Loaded from LMS</span></section>)}
      {!user.department && <p className="error-banner">No department is assigned. Ask your administrator to update your account.</p>}
      {error && <p className="error-banner">{error}</p>}
      {page === "dashboard" && <section className="stats-grid stats-five">
        <StatCard icon="users" label="Total students" value={students.length} tone="blue" />
        <StatCard icon="users" label="Faculty" value={faculty.length} tone="purple" />
        <StatCard icon="courses" label="Department courses" value={courses.length} tone="amber" />
        <StatCard icon="chart" label="Avg attendance" value={average === null ? "—" : `${average}%`} tone="blue" />
        <StatCard icon="alert" label="At-risk students" value={atRisk.length} tone="red" />
      </section>}
      {page === "dashboard" && <div className="page-actions"><Link className="btn btn-primary" to="/hod/students">View students</Link><Link className="btn btn-soft" to="/hod/attendance">Review attendance</Link><Link className="btn btn-soft" to="/hod/courses">View courses</Link></div>}

      <div className="page-grid">
        <div className="content-stack">
          {page === "attendance" && <section className="card panel-card" id="attendance"><div className="section-title-row"><h2 className="section-title">Attendance overview</h2><Icon name="chart" /></div>{[
            ["Above 90%", aboveNinety, "green"], ["75% – 90%", onTrack, "amber"], ["Below 75%", belowTarget, "red"],
          ].map(([label, count, tone]) => <div className="distribution-row" key={label}><div className="split-row"><span>{label}</span><strong>{percentageOfRecorded(count)}%</strong></div><div className="progress-track"><div className={`progress-fill tone-${tone}`} style={{ width: `${percentageOfRecorded(count)}%` }} /></div></div>)}{!percentages.length && <p className="footnote">Attendance will appear after students complete class sessions.</p>}</section>}
          {page === "attendance" && (<section className="card panel-card" id="students"><div className="section-title-row"><div><p className="section-eyebrow">Attendance risk</p><h2 className="section-title">Students requiring attention</h2></div><span className="pill pill-risk">{filteredAtRisk.length}</span></div>{!filteredAtRisk.length ? <EmptyState>No students currently fall below the 75% attendance target.</EmptyState> : <div className="ledger-wrap"><table className="ledger"><thead><tr><th>Student</th><th>Email</th><th>Attendance</th><th>Risk level</th></tr></thead><tbody>{filteredAtRisk.map((student) => { const percentage = summaries[student.id].percent; return <tr key={student.id}><td><div className="person-cell"><span className="person-initial">{student.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><strong>{student.name}</strong></div></td><td className="mono-cell">{student.email}</td><td className="risk-number">{percentage}%</td><td><span className={`pill ${percentage < 60 ? "pill-risk" : "pill-warning"}`}>{percentage < 60 ? "High" : "Medium"}</span></td></tr>; })}</tbody></table></div>}</section>)}
        </div>

        <aside className="content-stack">
          {page === "dashboard" && (<section className="card panel-card insight-card"><h3><Icon name="chart" /> Academic insights</h3><div className="insight-item"><strong>{atRisk.length ? "Attention required" : "No risks recorded"}</strong>{atRisk.length ? `${atRisk.length} student${atRisk.length === 1 ? "" : "s"} are below the 75% attendance target.` : "No student with recorded attendance is currently below the target."}</div><div className="insight-item"><strong>Coverage</strong>{percentages.length} of {students.length} students have recorded attendance data.</div></section>)}
          {page === "courses" && (<section className="card panel-card" id="courses"><div className="section-title-row"><h3>Department courses</h3><Icon name="courses" /></div>{!filteredCourses.length && <p className="footnote">No course matches your search.</p>}{filteredCourses.map((course) => <div className="item-row" key={course.id}><div className="split-row"><strong>{course.name}</strong><span className="course-code">{course.code}</span></div><p className="footnote">{facultyById[course.faculty_id]?.name || "Faculty not assigned"}</p></div>)}</section>)}
        </aside>
      </div>

      {page === "faculty" && (<section className="section" id="faculty"><div className="section-title-row"><div><p className="section-eyebrow">Department team</p><h2 className="section-title">Faculty overview</h2></div></div>{!faculty.length ? <EmptyState>No faculty members are assigned to this department.</EmptyState> : <div className="ledger-wrap"><table className="ledger"><thead><tr><th>Faculty</th><th>Email</th><th>Department</th><th>Courses</th></tr></thead><tbody>{faculty.map((member) => <tr key={member.id}><td><div className="person-cell"><span className="person-initial">{member.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><strong>{member.name}</strong></div></td><td className="mono-cell">{member.email}</td><td>{member.department || "—"}</td><td>{courses.filter((course) => course.faculty_id === member.id).length}</td></tr>)}</tbody></table></div>}</section>)}
      {page === "students" && <section className="section" id="students"><h2 className="section-title">Department students</h2>{!students.length ? <EmptyState>No students are assigned to this department.</EmptyState> : <div className="ledger-wrap"><table className="ledger"><thead><tr><th>Student</th><th>Email</th><th>Program</th><th>Batch</th><th>Semester</th><th>Section</th><th>Attendance</th></tr></thead><tbody>{students.filter((student) => `${student.name} ${student.email} ${student.program || ""} ${student.batch || ""}`.toLowerCase().includes(search.toLowerCase())).map((student) => <tr key={student.id}><td>{student.name}</td><td>{student.email}</td><td>{student.program || "—"}</td><td>{student.batch || "—"}</td><td>{student.semester_number ? `${student.semester_number} · Year ${Math.ceil(student.semester_number / 2)}` : "—"}</td><td>{student.section || "—"}</td><td>{summaries[student.id]?.percent == null ? "No data" : `${summaries[student.id].percent}%`}</td></tr>)}</tbody></table></div>}</section>}
    </DashboardShell>
  );
}
