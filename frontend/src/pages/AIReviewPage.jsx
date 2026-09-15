import { useCallback, useEffect, useState } from "react";
import DashboardShell, { EmptyState } from "../components/dashboard/DashboardShell";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import "../styles/dashboard.css";

const labels = { schedule_class: "Schedule class", draft_assignment: "Draft assignment", draft_quiz: "Draft quiz",
  student_progress: "Progress insight", import_erp_students: "ERP role-based user import", create_department: "Create department",
  create_course: "Create course", bulk_create_accounts: "Bulk-create accounts", cgpa_plan: "Target CGPA roadmap", help: "Help" };

export default function AIReviewPage() {
  const { user, logout } = useAuth();
  const [items, setItems] = useState([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(null);
  const load = useCallback(() => apiFetch("/ai/review/actions").then(setItems).catch(requestError => setError(requestError.message)), []);
  useEffect(() => { load(); }, [load]);
  const reject = async id => {
    setBusy(id); setError("");
    try {
      const updated = await apiFetch(`/ai/review/actions/${id}/reject`, { method: "POST" });
      setItems(current => current.map(item => item.action.id === id ? { ...item, action: updated } : item));
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(null); }
  };
  return <DashboardShell user={user} title="AI Review" roleLabel="Administrator" onLogout={logout} activePage="ai-review">
    <section className="ai-review-hero"><p className="section-eyebrow">Institution governance</p><h2>AI action review centre</h2><p>Audit actions requested across your institution. Administrators may reject a pending request, but cannot silently confirm an action on another user’s behalf.</p></section>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {!items.length ? <EmptyState>No institution AI actions have been recorded.</EmptyState> : <div className="ledger-wrap"><table className="ledger ai-review-table"><thead><tr><th>Requester</th><th>Action</th><th>Command</th><th>Status</th><th>Created</th><th>Governance</th></tr></thead><tbody>{items.map(({ action, requester }) => <tr key={action.id}><td><strong>{requester.name}</strong><br /><small>{requester.role}</small></td><td>{labels[action.intent] || action.intent}</td><td>{action.prompt}</td><td><span className={`pill ${action.status === "completed" ? "pill-ok" : action.status === "draft" ? "pill-warning" : "pill-muted"}`}>{action.status}</span></td><td>{new Date(action.created_at).toLocaleString()}</td><td>{action.status === "draft" ? <button className="btn-text" disabled={busy === action.id} onClick={() => reject(action.id)}>{busy === action.id ? "Rejecting…" : "Reject pending action"}</button> : "—"}</td></tr>)}</tbody></table></div>}
  </DashboardShell>;
}
