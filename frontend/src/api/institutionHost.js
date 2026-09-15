// The address bar selects the portal, never a query parameter or editable form.
export function institutionHost(hostname = globalThis.window?.location?.hostname || "") {
  const host = hostname.toLowerCase();
  // Vercel addresses are platform entry points, not institution-owned domains.
  if (host.endsWith(".vercel.app")) return null;
  return host.startsWith("ekeekrta.") ? host : null;
}

export function institutionHeaders() {
  const host = institutionHost();
  return host ? { "X-Institution-Host": host } : {};
}
