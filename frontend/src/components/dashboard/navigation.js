const item = (id, label, icon) => ({ id, label, icon });

export const studentPortalSections = [
  { id: "home", label: "Home", entry: "dashboard", items: [
    item("dashboard", "Dashboard", "dashboard"), item("notifications", "Notifications", "alert"),
    item("attendance", "Attendance", "check"), item("marks", "Marks", "chart"),
    item("timetable", "Timetable", "calendar"),
    item("settings", "Settings", "settings"),
  ] },
  { id: "academics", label: "Academics", entry: "academic-courses", items: [
    item("academic-courses", "My Courses", "courses"), item("subject-enrollment", "Enroll Subjects", "check"),
    item("academic-assignments", "Assignments", "assignments"),
    item("syllabus", "Syllabus", "material"), item("notes", "Notes", "assignments"),
    item("study-materials", "Study Material", "material"),
  ] },
  { id: "non-academics", label: "Non Academics", entry: "non-academic-courses", items: [
    item("non-academic-courses", "Courses", "courses"), item("non-academic-assignments", "Assignments", "assignments"),
    item("programming-assessments", "Programming Assessments", "code"),
    item("weekly-tests", "Weekly Tests", "clock"), item("non-academic-quizzes", "Quizzes", "quiz"),
    item("non-academic-marks", "Marks", "chart"), item("leaderboard", "Leader Board · Top 10", "users"),
  ] },
  { id: "ai", label: "AI Assistant", entry: "ai-assistant", items: [item("ai-assistant", "AI Assistant", "quiz")] },
];

export function studentSectionForPage(page = "dashboard") {
  return studentPortalSections.find(section => section.items.some(entry => entry.id === page)) || studentPortalSections[0];
}

export const dashboardNavigation = {
  admin: [item("dashboard", "Dashboard", "dashboard"), item("users", "Users", "users"),
    item("erp", "ERP Integration", "department"), item("register-student", "Register student", "users"),
    item("register-faculty", "Create faculty", "users"),
    item("register-hod", "Create HOD", "users"), item("institution", "Institution profile", "department"),
    item("departments", "Departments", "department"), item("academic-progression", "Semester promotion", "calendar"), item("courses", "Courses", "courses"),
    item("materials", "Study Materials", "upload"), item("ai-assistant", "AI Assistant", "quiz"),
    item("ai-review", "AI Review", "check"), item("settings", "Settings", "settings")],
  student: studentPortalSections.flatMap(section => section.items),
  faculty: [item("dashboard", "Dashboard", "dashboard"), item("courses", "My Courses", "courses"),
    item("calendar", "Calendar", "calendar"),
    item("schedule", "Schedule class", "calendar"),
    item("create-course", "Create Course", "courses"), item("grading", "Grading", "check"),
    item("roster", "Student Roster", "users"), item("ai-assistant", "AI Assistant", "quiz"),
    item("settings", "Settings", "settings")],
  hod: [item("dashboard", "Dashboard", "dashboard"), item("students", "Students", "users"),
    item("calendar", "Calendar", "calendar"),
    item("faculty", "Faculty", "users"), item("courses", "Courses", "courses"),
    item("attendance", "Attendance", "chart"), item("ai-assistant", "AI Assistant", "quiz"),
    item("settings", "Settings", "settings")],
};

export function dashboardPath(role, page = "dashboard") {
  return `/${role}${page === "dashboard" ? "" : `/${page}`}`;
}

export function isDashboardPage(role, page = "dashboard") {
  return dashboardNavigation[role]?.some((item) => item.id === page) || false;
}
