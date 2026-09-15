import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";
import { EmptyState, Icon } from "./DashboardShell";

const blank = { base_url: "", api_token: "", external_institution_id: "", enabled: false,
  sync_students: true, sync_courses: true, sync_attendance: true };

const editableSettings = settings => ({
  base_url: settings.base_url || "",
  api_token: "",
  external_institution_id: settings.external_institution_id || "",
  enabled: Boolean(settings.enabled),
  sync_students: Boolean(settings.sync_students),
  sync_courses: Boolean(settings.sync_courses),
  sync_attendance: Boolean(settings.sync_attendance),
});

const formatTime = value => value ? new Date(value).toLocaleString() : "Not yet";

export function ERPUserImportPreview({ preview, busy = false, onConfirm, onCancel }) {
  return <section className="card panel-card erp-import-preview">
    <div className="section-title-row"><div><p className="section-eyebrow">Administrator confirmation required</p><h2 className="section-title">ERP user import preview</h2></div><span className="pill pill-muted">Expires in {preview.expires_in_minutes} minutes</span></div>
    <div className="stats-grid"><div className="stat-card"><div className="stat-label">Create</div><div className="stat-value">{preview.creates}</div></div><div className="stat-card"><div className="stat-label">Update</div><div className="stat-value">{preview.updates}</div></div><div className="stat-card"><div className="stat-label">Skip</div><div className="stat-value">{preview.skipped}</div></div></div>
    <div className="ledger-wrap"><table className="ledger"><thead><tr><th>ERP user</th><th>Role</th><th>Official ID</th><th>Department</th><th>Action</th><th>Reason</th></tr></thead><tbody>{preview.records.map(record => <tr key={`${record.row}-${record.institutional_id}`}><td><strong>{record.name}</strong><br /><small>{record.email}</small></td><td>{record.role}</td><td className="mono-cell">{record.institutional_id}</td><td>{record.department || "—"}</td><td><span className={`pill ${record.action === "skip" ? "pill-risk" : record.action === "create" ? "pill-ok" : "pill-muted"}`}>{record.action}</span></td><td>{record.reason || "Ready"}</td></tr>)}</tbody></table></div>
    <p className="footnote">Newly imported users sign in with their Official ID as a temporary password and must replace it immediately. Later ERP imports do not reset their chosen password.</p>
    <div className="page-actions"><button className="btn btn-primary" disabled={busy || preview.creates + preview.updates === 0} onClick={onConfirm}>{busy ? "Importing…" : "Confirm user import"}</button><button className="btn btn-soft" onClick={onCancel}>Cancel</button></div>
  </section>;
}

export default function ERPIntegration() {
  const [form, setForm] = useState(blank);
  const [events, setEvents] = useState([]);
  const [configured, setConfigured] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [connection, setConnection] = useState(null);
  const [importPreview, setImportPreview] = useState(null);

  const refreshEvents = () => apiFetch("/erp/events").then(setEvents);
  useEffect(() => {
    Promise.all([apiFetch("/erp/configuration"), apiFetch("/erp/events")]).then(([settings, history]) => {
      setConfigured(settings.configured); setConnection(settings); setEvents(history);
      setForm(editableSettings(settings));
    }).catch(err => setError(err.message));
  }, []);

  const run = async (kind, action) => {
    setBusy(kind); setError(""); setMessage("");
    try { await action(); await refreshEvents(); }
    catch (err) { setError(err.message); }
    finally { setBusy(""); }
  };
  const save = event => { event.preventDefault(); return run("save", async () => {
    const saved = await apiFetch("/erp/configuration", { method: "PUT", body: JSON.stringify({
      base_url: form.base_url,
      api_token: form.api_token || null,
      external_institution_id: form.external_institution_id || null,
      enabled: form.enabled,
      sync_students: form.sync_students,
      sync_courses: form.sync_courses,
      sync_attendance: form.sync_attendance,
    }) });
    setConfigured(true); setConnection(saved); setForm(current => ({ ...current, api_token: "" }));
    setMessage("ERP settings saved. Test the connection before starting a full synchronization.");
  }); };
  const test = () => run("test", async () => { const result = await apiFetch("/erp/test", { method: "POST" });
    setConnection(result); if (!result.last_test_success) throw new Error(result.last_test_message || "ERP connection test failed");
    setMessage("ERP connection verified successfully."); });
  const sync = () => run("sync", async () => { const result = await apiFetch("/erp/sync", { method: "POST" });
    setMessage(`${result.synced} course/attendance records sent; ${result.pending} remain waiting. User-directory imports use the separate reviewed preview.`); });
  const previewUsers = () => run("preview-users", async () => {
    const result = await apiFetch("/erp/import-users/preview", { method: "POST" });
    setImportPreview(result);
    setMessage(`Review ${result.total} ERP user record${result.total === 1 ? "" : "s"} before confirming.`);
  });
  const confirmUsers = () => run("confirm-users", async () => {
    const result = await apiFetch("/erp/import-users/confirm", { method: "POST",
      body: JSON.stringify({ confirmation_token: importPreview.confirmation_token }) });
    setImportPreview(null);
    setMessage(`${result.message}. Students: ${result.role_counts.student || 0}, faculty: ${result.role_counts.faculty || 0}, HODs: ${result.role_counts.hod || 0}.`);
  });
  const dispatch = () => run("dispatch", async () => { const result = await apiFetch("/erp/dispatch", { method: "POST" });
    setMessage(`${result.synced} waiting records synchronized; ${result.pending} remain.`); });
  const retry = id => run(`retry-${id}`, async () => { const result = await apiFetch(`/erp/events/${id}/retry`, { method: "POST" });
    setMessage(result.status === "synced" ? "Record synchronized." : "The ERP still rejected this record."); });

  return <div className="content-stack">
    <section className="card panel-card integration-card">
      <div className="section-title-row"><div><p className="section-eyebrow">Institution connection</p><h2 className="section-title">ERP integration</h2></div><Icon name="department" size={26} /></div>
      <p className="footnote">Student, faculty, and HOD identities can be imported from your institution’s ERP after administrator review. Administrator accounts and conflicting role changes are never imported. Courses and meeting attendance are sent back to the ERP. The API token is encrypted and is never shown again.</p>
      {connection?.last_tested_at && <div className={connection.last_test_success ? "connection-banner" : "error-banner"}><i />{connection.last_test_message} · {formatTime(connection.last_tested_at)}</div>}
      <form className="form-grid erp-form" onSubmit={save}>
        <label className="field-label wide">ERP HTTPS base URL<input className="field" type="url" placeholder="https://erp.yourinstitution.edu" value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} required /></label>
        <label className="field-label">Institution ID in ERP<input className="field" placeholder="Optional external institution code" value={form.external_institution_id} onChange={e => setForm({ ...form, external_institution_id: e.target.value })} /></label>
        <label className="field-label">ERP API token<input className="field" type="password" placeholder={configured ? "Leave blank to keep saved token" : "Required on first setup"} value={form.api_token} onChange={e => setForm({ ...form, api_token: e.target.value })} required={!configured} minLength={16} autoComplete="new-password" /></label>
        <fieldset className="wide erp-options"><legend>Records to synchronize</legend>
          {[['sync_students','Import ERP user directory'],['sync_courses','Send courses to ERP'],['sync_attendance','Send meeting attendance to ERP']].map(([key,label]) => <label key={key}><input type="checkbox" checked={form[key]} onChange={e => setForm({ ...form, [key]: e.target.checked })} /> {label}</label>)}
          <label><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> Enable automatic synchronization</label>
        </fieldset>
        {error && <p className="error-banner wide" role="alert">{error}</p>}{message && <p className="success-banner wide" role="status">{message}</p>}
        <div className="wide hero-actions"><button className="btn btn-primary" disabled={!!busy}>{busy === "save" ? "Saving…" : "Save connection"}</button>
          <button className="btn btn-soft" type="button" onClick={test} disabled={!configured || !!busy}>{busy === "test" ? "Testing…" : "Test connection"}</button>
          <button className="btn btn-soft" type="button" onClick={previewUsers} disabled={!configured || !form.enabled || !form.sync_students || !!busy}>{busy === "preview-users" ? "Reading ERP…" : "Preview ERP users"}</button>
          <button className="btn btn-soft" type="button" onClick={sync} disabled={!configured || !form.enabled || !!busy}>{busy === "sync" ? "Synchronizing…" : "Sync courses & attendance"}</button>
          <button className="btn btn-soft" type="button" onClick={dispatch} disabled={!configured || !form.enabled || !!busy}>Retry waiting</button></div>
      </form>
    </section>
    {importPreview && <ERPUserImportPreview preview={importPreview} busy={busy === "confirm-users"}
      onConfirm={confirmUsers} onCancel={() => setImportPreview(null)} />}
    <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Delivery ledger</p><h2 className="section-title">Recent ERP syncs</h2></div><span className="pill pill-muted">{events.length} events</span></div>
      {!events.length ? <EmptyState>No ERP records have been sent. No sample events are created.</EmptyState> : <div className="ledger-wrap"><table className="ledger"><thead><tr><th>Record</th><th>Type</th><th>Status</th><th>Attempts</th><th>Updated</th><th>Action</th></tr></thead><tbody>{events.map(item => <tr key={item.id}><td className="mono-cell">{item.entity_key}</td><td>{item.event_type}</td><td><span className={`pill ${item.status === 'synced' ? 'pill-ok' : item.status === 'failed' ? 'pill-risk' : 'pill-warning'}`}>{item.status}</span>{item.last_error && <small className="erp-error">{item.last_error}</small>}</td><td>{item.attempts}</td><td>{formatTime(item.updated_at)}</td><td>{item.status !== "synced" ? <button className="btn-text" disabled={!!busy} onClick={() => retry(item.id)}>{busy === `retry-${item.id}` ? "Retrying…" : "Retry"}</button> : "—"}</td></tr>)}</tbody></table></div>}
    </section>
  </div>;
}
