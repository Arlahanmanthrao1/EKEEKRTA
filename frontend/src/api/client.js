import { institutionHeaders } from "./institutionHost";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function getToken() {
  return localStorage.getItem("lms_token");
}

export async function apiFetch(path, options = {}) {
  const token = getToken();
  const multipart = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = {
    ...(!multipart ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
    ...institutionHeaders(),
  };

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(". ") : detail || `Request failed (${res.status})`);
  }

  if (res.status === 204) return null;
  return res.json();
}

export async function login(email, password) {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", ...institutionHeaders() },
    body,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Unable to sign in");
  }
  return res.json();
}

export async function createStudent(payload) {
  return createAccount("/auth/register", payload);
}

export async function createFaculty(payload) {
  return createAccount("/auth/register-faculty", payload);
}

export async function createHod(payload) {
  return createAccount("/auth/register-hod", payload);
}

async function createAccount(path, payload) {
  const token = getToken();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...institutionHeaders() },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const details = body?.detail;
    const message = Array.isArray(details)
      ? details.map((item) => item.msg?.replace(/^Value error, /, "") || "Invalid registration details").join(". ")
      : details || "Registration failed";
    throw new Error(message);
  }
  return res.json();
}
