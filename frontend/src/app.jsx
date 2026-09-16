import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation } from "react-router-dom";
import { dashboardPath, isDashboardPage } from "./components/dashboard/navigation";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { BrandLoading } from "./branding/Brand";
import Login from "./pages/login";
import InstitutionRegistration from "./pages/InstitutionRegistration";
import { institutionHost } from "./api/institutionHost";
import StudentDashboard from "./pages/StudentDashboard";
import FacultyDashboard from "./pages/FacultyDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import HodDashboard from "./pages/HodDashboard";
import ClassroomPage from "./pages/ClassroomPage";
import CalendarPage from "./pages/CalendarPage";
import SchedulePage from "./pages/SchedulePage";
import FacultyCoursePage from "./pages/FacultyCoursePage";
import StudentCoursePage from "./pages/StudentCoursePage";
import ProgrammingAssessmentPage from "./pages/ProgrammingAssessmentPage";
import AIAssistantPage from "./pages/AIAssistantPage";
import AIReviewPage from "./pages/AIReviewPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import SettingsPage from "./pages/SettingsPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import { ThemeProvider } from "./context/ThemeContext";

function DashboardRouter() {
  const { user } = useAuth();
  const { page = "dashboard" } = useParams();
  if (!isDashboardPage(user.role, page)) return <Navigate to={dashboardPath(user.role)} replace />;
  if (page === "settings") return <SettingsPage />;
  if (page === "ai-assistant") return <AIAssistantPage />;
  if (page === "ai-review" && user.role === "admin") return <AIReviewPage />;
  if (page === "calendar" || (user.role === "student" && page === "timetable")) return <CalendarPage />;
  if (page === "schedule" && user.role === "faculty") return <SchedulePage />;
  if (user.role === "student") return <StudentDashboard />;
  if (user.role === "faculty") return <FacultyDashboard />;
  if (user.role === "admin") return <AdminDashboard />;
  if (user.role === "hod") return <HodDashboard />;
  return <p>Unknown role.</p>;
}

function AppRoutes() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <BrandLoading />;

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/register-institution" element={institutionHost() ? <Navigate to="/login" replace /> : <InstitutionRegistration />} />
        <Route path="*" element={<Navigate to="/login" state={{ from: location.pathname }} replace />} />
      </Routes>
    );
  }

  if (user.must_change_password) {
    return <Routes><Route path="/change-password" element={<ChangePasswordPage />} /><Route path="*" element={<Navigate to="/change-password" replace />} /></Routes>;
  }

  return (
    <Routes>
      {user.role === "faculty" && <Route path="/faculty/courses/:courseId" element={<FacultyCoursePage />} />}
      {user.role === "student" && <Route path="/student/courses/:courseId" element={<StudentCoursePage />} />}
      {user.role === "student" && <Route path="/student/programming-assessments/:assessmentId" element={<ProgrammingAssessmentPage />} />}
      <Route path={`/${user.role}/:page?`} element={<DashboardRouter />} />
      <Route path="/classroom" element={<ClassroomPage />} />
      <Route path="*" element={<Navigate to={
        location.pathname === "/login" && location.state?.from?.startsWith(`/${user.role}/`)
          ? location.state.from : dashboardPath(user.role)
      } replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
