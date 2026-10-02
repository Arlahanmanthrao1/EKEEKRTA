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

export const trainingStudentPortalSections = [
  { id: "home", label: "Home", entry: "dashboard", items: [
    item("dashboard", "Dashboard", "dashboard"), item("notifications", "Notifications", "alert"),
    item("attendance", "Attendance", "check"), item("marks", "Marks", "chart"),
    item("timetable", "Timetable", "calendar"), item("settings", "Settings", "settings"),
  ] },
  { id: "learning", label: "Learning", entry: "batches", items: [
    item("batches", "My Batches", "courses"),
    item("assignments", "Assignments", "assignments"), item("quizzes", "Quizzes", "quiz"),
    item("programming-assessments", "Programming Assessments", "code"),
    item("notes", "Notes", "assignments"), item("study-materials", "Study Materials", "material"),
  ] },
  { id: "ai", label: "AI Assistant", entry: "ai-assistant", items: [item("ai-assistant", "AI Assistant", "quiz")] },
];

export function studentSectionsFor(institutionType = "university") {
  return institutionType === "training_institution" ? trainingStudentPortalSections : studentPortalSections;
}

export function studentSectionForPage(page = "dashboard", institutionType = "university") {
  const sections = studentSectionsFor(institutionType);
  return sections.find(section => section.items.some(entry => entry.id === page)) || sections[0];
}

export const dashboardNavigation = {
  platform_admin: [item("dashboard", "Overview", "dashboard"),
    item("institutions", "Institutions", "department"), item("audit", "Audit log", "assignments")],
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
    item("roster", "Student Roster", "users"), item("data-exchange", "Data Exchange", "upload"),
    item("ai-assistant", "AI Assistant", "quiz"),
    item("settings", "Settings", "settings")],
  hod: [item("dashboard", "Dashboard", "dashboard"), item("students", "Students", "users"),
    item("calendar", "Calendar", "calendar"),
    item("faculty", "Faculty", "users"), item("courses", "Courses", "courses"),
    item("attendance", "Attendance", "chart"), item("ai-assistant", "AI Assistant", "quiz"),
    item("settings", "Settings", "settings")],
};

export function dashboardPath(role, page = "dashboard") {
  const base = role === "platform_admin" ? "/platform" : `/${role}`;
  return `${base}${page === "dashboard" ? "" : `/${page}`}`;
}

export function navigationFor(role, institutionType = "university") {
  const items = dashboardNavigation[role] || [];
  if (institutionType !== "training_institution") return items;
  if (role === "admin") return items
    .filter((entry) => !["erp", "register-hod", "academic-progression"].includes(entry.id))
    .map((entry) => entry.id === "register-faculty" ? { ...entry, label: "Create trainer" }
      : entry.id === "departments" ? { ...entry, label: "Domains" }
      : entry.id === "courses" ? { ...entry, label: "Programs" } : entry)
    .flatMap((entry) => entry.id === "courses" ? [entry, item("batches", "Training Batches", "calendar")] : [entry]);
  if (role === "student") return trainingStudentPortalSections.flatMap(section => section.items);
  if (role === "faculty") return items
    .filter(entry => !["schedule", "data-exchange"].includes(entry.id))
    .map((entry) => entry.id === "courses" ? { ...entry, label: "Programs" }
      : entry.id === "create-course" ? { ...entry, label: "Create Program" } : entry)
    .flatMap((entry) => entry.id === "courses" ? [entry, item("batches", "My Batches", "calendar")] : [entry]);
  return items;
}

export function isDashboardPage(role, page = "dashboard", institutionType = "university") {
  return navigationFor(role, institutionType).some((item) => item.id === page);
}
