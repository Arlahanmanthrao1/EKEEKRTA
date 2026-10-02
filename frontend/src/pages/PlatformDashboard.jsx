import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../api/client";
import { BrandLoading } from "../branding/Brand";
import DashboardShell, { EmptyState, Icon, StatCard } from "../components/dashboard/DashboardShell";
import { useAuth } from "../context/AuthContext";
import "../styles/dashboard.css";

const statusLabels = { pending: "Pending review", active: "Active", suspended: "Suspended", rejected: "Rejected" };
const typeLabels = { university: "University", training_institution: "Training institution" };

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export default function PlatformDashboard() {
  const { user, logout } = useAuth();
  const { page = "dashboard" } = useParams();
  const [summary, setSummary] = useState(null);
  const [institutions, setInstitutions] = useState([]);
  const [audit, setAudit] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [review, setReview] = useState(null);
  const [reason, setReason] = useState("");
  const [deletion, setDeletion] = useState(null);
  const [confirmationName, setConfirmationName] = useState("");
  const [deletionReason, setDeletionReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [summaryData, institutionData, auditData] = await Promise.all([
        apiFetch("/platform/summary"), apiFetch("/platform/institutions"), apiFetch("/platform/audit?limit=100"),
      ]);
      setSummary(summaryData); setInstitutions(institutionData); setAudit(auditData);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => institutions.filter((entry) => {
    const matchesSearch = `${entry.name} ${entry.email_domain} ${entry.primary_administrator_name || ""} ${entry.primary_administrator_email || ""}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch && (!statusFilter || entry.status === statusFilter) && (!typeFilter || entry.institution_type === typeFilter);
  }), [institutions, search, statusFilter, typeFilter]);

  const beginReview = (institution, status) => { setDeletion(null); setReview({ institution, status }); setReason(""); setError(""); setSuccess(""); };
  const beginDeletion = (institution) => {
    setReview(null); setDeletion(institution); setConfirmationName(""); setDeletionReason(""); setError(""); setSuccess("");
  };
  const submitReview = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setSuccess("");
    try {
      const updated = await apiFetch(`/platform/institutions/${review.institution.id}/status`, {
        method: "PATCH", body: JSON.stringify({ status: review.status, reason: reason || null }),
      });
      setInstitutions((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      setReview(null); setReason(""); setSuccess(`${updated.name} is now ${statusLabels[updated.status].toLowerCase()}.`);
      const [summaryData, auditData] = await Promise.all([apiFetch("/platform/summary"), apiFetch("/platform/audit?limit=100")]);
      setSummary(summaryData); setAudit(auditData);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const submitDeletion = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setSuccess("");
    try {
      const result = await apiFetch(`/platform/institutions/${deletion.id}`, {
        method: "DELETE",
        body: JSON.stringify({ confirmation_name: confirmationName, reason: deletionReason }),
      });
      setInstitutions((current) => current.filter((entry) => entry.id !== result.institution_id));
      setDeletion(null); setConfirmationName(""); setDeletionReason("");
      setSuccess(`${result.institution_name} was permanently deleted with ${result.deleted_user_count} account(s) and ${result.deleted_course_count} course(s).`);
      const [summaryData, auditData] = await Promise.all([apiFetch("/platform/summary"), apiFetch("/platform/audit?limit=100")]);
      setSummary(summaryData); setAudit(auditData);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  if (loading) return <BrandLoading>Preparing platform operations…</BrandLoading>;
  return <DashboardShell user={user} title="Ekeekrta Operations" roleLabel="Platform operator" onLogout={logout}
    searchValue={search} onSearch={setSearch} searchPlaceholder="Search institutions or administrators…">
    {page === "dashboard" && <section className="page-hero"><div><p className="section-eyebrow">Platform operations</p><h1>Institution control centre</h1><p>Review onboarding and manage tenant access without entering institution data areas.</p></div><span className="sync-badge"><i /> Isolated operator access</span></section>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {success && <p className="success-banner" role="status">{success}</p>}
    {page === "dashboard" && summary && <>
      <section className="stats-grid stats-five">
        <StatCard icon="department" label="Institutions" value={summary.institutions_total} tone="blue" detail={`${summary.universities} universities · ${summary.training_institutions} training`} />
        <StatCard icon="clock" label="Awaiting review" value={summary.pending} tone="amber" />
        <StatCard icon="check" label="Active" value={summary.active} tone="green" />
        <StatCard icon="alert" label="Restricted" value={summary.suspended + summary.rejected} tone="red" detail={`${summary.suspended} suspended · ${summary.rejected} rejected`} />
        <StatCard icon="users" label="Institution users" value={summary.institution_users} tone="purple" detail={`${summary.courses} courses`} />
      </section>
      <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Priority queue</p><h2 className="section-title">Registrations awaiting review</h2></div><span className="pill pill-warning">{summary.pending} pending</span></div>
        {!institutions.some((entry) => entry.status === "pending") ? <EmptyState>No institution registrations are waiting.</EmptyState> : <InstitutionTable entries={institutions.filter((entry) => entry.status === "pending")} beginReview={beginReview} beginDeletion={beginDeletion} />}
      </section>
    </>}
    {page === "institutions" && <>
      <section className="card panel-card platform-filters"><label className="field-label">Status<select className="field" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">All statuses</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field-label">Institution type<select className="field" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="">All types</option>{Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="btn btn-ghost" type="button" onClick={() => { setStatusFilter(""); setTypeFilter(""); }}>Clear filters</button></section>
      <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Tenant directory</p><h2 className="section-title">Institutions</h2></div><span className="pill pill-muted">{filtered.length} shown</span></div>{!filtered.length ? <EmptyState>No institution matches these filters.</EmptyState> : <InstitutionTable entries={filtered} beginReview={beginReview} beginDeletion={beginDeletion} />}</section>
    </>}
    {review && <section className="card panel-card platform-review-card"><div className="section-title-row"><div><p className="section-eyebrow">Confirm access change</p><h2 className="section-title">{statusLabels[review.status]} · {review.institution.name}</h2></div><button className="btn-text" type="button" onClick={() => setReview(null)}>Cancel</button></div><form className="form-grid" onSubmit={submitReview}><label className="field-label wide">Review note {review.status === "suspended" || review.status === "rejected" ? "(required)" : "(optional)"}<textarea className="field" value={reason} onChange={(event) => setReason(event.target.value)} required={review.status === "suspended" || review.status === "rejected"} maxLength={500} placeholder="Record the reason for the audit trail." /></label><div className="wide"><button className={`btn ${review.status === "active" ? "btn-primary" : "btn-danger"}`} disabled={busy}>{busy ? "Saving…" : `Confirm ${statusLabels[review.status].toLowerCase()}`}</button></div></form></section>}
    {deletion && <section className="card panel-card platform-delete-card"><div className="section-title-row"><div><p className="section-eyebrow">Permanent deletion</p><h2 className="section-title">Delete {deletion.name}</h2></div><button className="btn-text" type="button" onClick={() => setDeletion(null)}>Cancel</button></div><p className="danger-copy">This permanently removes the institution, its Ekeekrta accounts, courses and learning records. Data already sent to an ERP or a trainer’s Google Drive is not deleted.</p><form className="form-grid" onSubmit={submitDeletion}><label className="field-label wide">Type <strong>{deletion.name}</strong> to confirm<input className="field" value={confirmationName} onChange={(event) => setConfirmationName(event.target.value)} autoComplete="off" required /></label><label className="field-label wide">Deletion reason<textarea className="field" value={deletionReason} onChange={(event) => setDeletionReason(event.target.value)} minLength="5" maxLength="500" required placeholder="Explain why this institution and its data must be deleted." /></label><div className="wide"><button className="btn btn-danger" disabled={busy || confirmationName !== deletion.name}>{busy ? "Deleting…" : "Permanently delete institution"}</button></div></form></section>}
    {page === "audit" && <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Security record</p><h2 className="section-title">Platform audit log</h2></div><span className="pill pill-muted">Latest {audit.length}</span></div>{!audit.length ? <EmptyState>No platform actions have been recorded.</EmptyState> : <div className="ledger-wrap"><table className="ledger"><thead><tr><th>When</th><th>Operator</th><th>Institution</th><th>Action</th><th>Change</th></tr></thead><tbody>{audit.map((entry) => <tr key={entry.id}><td>{formatDate(entry.created_at)}</td><td><strong>{entry.operator_name}</strong><br /><small>{entry.operator_email}</small></td><td>{entry.institution_name || entry.details.institution_name || "Platform"}</td><td>{entry.event_type.replaceAll("_", " ")}</td><td>{entry.event_type === "institution_permanently_deleted" ? `Permanently deleted · ${entry.details.deleted_user_count} users · ${entry.details.deleted_course_count} courses` : entry.details.previous_status ? `${statusLabels[entry.details.previous_status] || entry.details.previous_status} → ${statusLabels[entry.details.new_status] || entry.details.new_status}` : "—"}{entry.details.reason && <><br /><small>{entry.details.reason}</small></>}</td></tr>)}</tbody></table></div>}</section>}
  </DashboardShell>;
}

function InstitutionTable({ entries, beginReview, beginDeletion }) {
  return <div className="ledger-wrap"><table className="ledger platform-institution-table"><thead><tr><th>Institution</th><th>Type</th><th>Status</th><th>Primary administrator</th><th>Usage</th><th>Registered</th><th>Actions</th></tr></thead><tbody>{entries.map((entry) => <tr key={entry.id}><td><div className="person-cell">{entry.logo_url ? <img className="platform-institution-logo" src={entry.logo_url} alt="" /> : <span className="person-initial">{entry.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span>}<div><strong>{entry.name}</strong><br /><small>{entry.email_domain}</small></div></div></td><td>{typeLabels[entry.institution_type] || entry.institution_type}</td><td><span className={`pill platform-status-${entry.status}`}>{statusLabels[entry.status]}</span>{entry.status_reason && <><br /><small>{entry.status_reason}</small></>}</td><td>{entry.primary_administrator_name || "Not available"}<br /><small>{entry.primary_administrator_email || `${entry.administrator_count} administrators`}</small></td><td>{entry.user_count} users<br /><small>{entry.course_count} courses</small></td><td>{formatDate(entry.created_at)}</td><td><div className="platform-review-actions">{entry.status !== "active" && <button type="button" className="btn-text" onClick={() => beginReview(entry, "active")}>{entry.status === "pending" ? "Approve" : "Reactivate"}</button>}{entry.status !== "suspended" && <button type="button" className="btn-text btn-text-danger" onClick={() => beginReview(entry, "suspended")}>Suspend</button>}{entry.status === "pending" && <button type="button" className="btn-text btn-text-danger" onClick={() => beginReview(entry, "rejected")}>Reject</button>}{(entry.status === "suspended" || entry.status === "rejected") && <button type="button" className="btn-text btn-text-danger" onClick={() => beginDeletion(entry)}>Delete permanently</button>}</div></td></tr>)}</tbody></table></div>;
}
