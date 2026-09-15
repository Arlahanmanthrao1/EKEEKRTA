import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useParams } from "react-router-dom";
import { dashboardNavigation, dashboardPath, studentPortalSections, studentSectionForPage } from "./navigation";
import { BrandLogo, pageTitle } from "../../branding/Brand";

const paths = {
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/></>,
  dashboard: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></>,
  courses: <><path d="m3 10 9-5 9 5-9 5-9-5Z"/><path d="M7 12.5V17l5 3 5-3v-4.5"/></>,
  assignments: <><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5M9 9h6M9 13h6M9 17h4"/></>,
  quiz: <><path d="M8.5 9a3.5 3.5 0 1 1 5.6 2.8c-1.3 1-2.1 1.5-2.1 3.2"/><path d="M12 19h.01"/><circle cx="12" cy="12" r="10"/></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></>,
  video: <><rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-3v10l-4-3"/></>,
  upload: <><path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M5 20h14"/></>,
  chart: <><path d="M4 19V9M10 19V5M16 19v-7M22 19V2"/></>,
  alert: <><path d="M10.3 2.9 1.8 17a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 2.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/></>,
  logout: <><path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  material: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></>,
  department: <><path d="M3 21h18M6 21V9h12v12M9 13h2m2 0h2m-6 4h2m2 0h2M8 9V5h8v4"/></>,
  check: <><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></>,
  clock: <><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></>,
  chevron: <path d="m15 18-6-6 6-6"/>,
  code: <><path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.1A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3V9.6h.1A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.1A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.2.38.6.76 1 1 .35.2.72.34 1.1.4h.1v4h-.1A1.7 1.7 0 0 0 19.4 15Z"/></>,
};

export function Icon({ name, size = 20 }) {
  return (
    <svg className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name] || paths.dashboard}
    </svg>
  );
}

export function StatCard({ icon, label, value, tone = "blue", detail }) {
  return (
    <div className="stat-card">
      <div className={`stat-icon stat-${tone}`}><Icon name={icon} size={22} /></div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

export function EmptyState({ children }) {
  return <div className="empty-state">{children}</div>;
}

export default function DashboardShell({ user, title, roleLabel, onLogout, searchPlaceholder, searchValue, onSearch, activePage, children }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [compactLayout, setCompactLayout] = useState(false);
  const [institutionLogoFailed, setInstitutionLogoFailed] = useState(false);
  const routeParams = useParams();
  const page = activePage || routeParams.page || "dashboard";
  const { pathname } = useLocation();
  const mainRef = useRef(null);
  const allNavItems = dashboardNavigation[user.role];
  const studentSection = user.role === "student" ? studentSectionForPage(page) : null;
  const navItems = studentSection?.items || allNavItems;
  const currentPage = allNavItems.find((item) => item.id === page);
  const initials = user.name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  const institutionName = user.institution?.name || title;
  const institutionInitials = institutionName.split(/\s+/).filter(Boolean).map(part => part[0]).join("").slice(0, 2).toUpperCase();

  useEffect(() => {
    const media = window.matchMedia("(max-width: 820px)");
    const updateLayout = () => {
      setCompactLayout(media.matches);
      if (!media.matches) setMobileNavOpen(false);
    };
    updateLayout();
    media.addEventListener?.("change", updateLayout);
    return () => media.removeEventListener?.("change", updateLayout);
  }, []);

  useEffect(() => setInstitutionLogoFailed(false), [user.institution?.logo_url]);

  useEffect(() => {
    setMobileNavOpen(false);
    onSearch?.("");
    window.scrollTo({ top: 0, behavior: "instant" });
    mainRef.current?.focus({ preventScroll: true });
    document.title = pageTitle(currentPage?.label || "Dashboard", user.institution?.name || title);
  }, [pathname, currentPage?.label, title, user.institution?.name, onSearch]);

  const sidebarOpen = compactLayout ? mobileNavOpen : !sidebarCollapsed;
  const toggleSidebar = () => {
    if (compactLayout) setMobileNavOpen(open => !open);
    else setSidebarCollapsed(collapsed => !collapsed);
  };

  return (
    <div className={`portal-shell ${!compactLayout && sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside id="portal-navigation" className={`portal-sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-header"><Link className="platform-home sidebar-platform" to={dashboardPath(user.role)}><BrandLogo /></Link><button className="sidebar-collapse-toggle" type="button" onClick={toggleSidebar} aria-label={`${sidebarOpen ? "Close" : "Open"} left menu`} aria-controls="portal-navigation" aria-expanded={sidebarOpen}><Icon name="chevron" /></button></div>
        <div className="profile-block">
          <div className="avatar">{initials}</div>
          <div><strong>{user.name}</strong><span>{user.department || roleLabel}</span></div>
        </div>
        {studentSection && <div className="sidebar-context-title"><span>{studentSection.label}</span></div>}
        <nav className="portal-nav" aria-label="Dashboard sections">
          {navItems.map((item) => (
            <NavLink key={item.id} to={dashboardPath(user.role, item.id)} end onClick={() => setMobileNavOpen(false)} title={sidebarOpen ? undefined : item.label}>
              <Icon name={item.icon} /><span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <button className="sidebar-logout" onClick={onLogout} title={sidebarOpen ? undefined : "Sign out"}><Icon name="logout" /><span>Sign out</span></button>
      </aside>
      {compactLayout && mobileNavOpen && <button className="sidebar-backdrop" type="button" onClick={() => setMobileNavOpen(false)} aria-label="Close left menu" />}

      <div className="portal-main">
        <header className={`portal-topbar ${user.role === "student" ? "student-portal-topbar" : ""}`}>
          <Link className="portal-brand" to={dashboardPath(user.role)}>{user.institution?.logo_url && !institutionLogoFailed ? <img className="institution-brand-logo" src={user.institution.logo_url} alt={`${institutionName} logo`} referrerPolicy="no-referrer" onError={() => setInstitutionLogoFailed(true)} /> : <span className="institution-fallback-logo" aria-hidden="true">{institutionInitials || "IN"}</span>}<span className="institution-heading"><strong>{institutionName}</strong><small>{roleLabel}</small></span></Link>
          {user.role === "student" && <nav className="student-top-nav" aria-label="Student portal areas">{studentPortalSections.map(section => <Link key={section.id} to={dashboardPath("student", section.entry)} className={studentSection?.id === section.id ? "active" : ""} aria-current={studentSection?.id === section.id ? "location" : undefined}>{section.label}</Link>)}</nav>}
          {onSearch && (
            <label className="search-box">
              <Icon name="search" size={18} />
              <input value={searchValue} onChange={(event) => onSearch(event.target.value)} placeholder={searchPlaceholder || "Search…"} />
            </label>
          )}
          <div className="top-avatar">{initials}</div>
        </header>
        <main className="portal-content" ref={mainRef} tabIndex={-1}>
          {page !== "dashboard" && <div className="page-heading"><p className="section-eyebrow">{roleLabel}</p><h1>{currentPage?.label}</h1></div>}
          {children}
        </main>
      </div>
    </div>
  );
}
