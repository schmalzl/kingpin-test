let csrf = "";
let auto = false;
/** Runs fn with all GET requests flagged as automatic refreshes (they do not keep the session alive). */
export async function withAuto(fn) { auto = true; try { return await fn(); } finally { auto = false; } }
export const setCsrf = (t) => { csrf = t; };

export async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrf;
  else if (auto) headers["X-Auto-Refresh"] = "1";
  let res;
  try {
    res = await fetch(path, { method, headers, credentials: "same-origin",
      body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw Object.assign(new Error("Network error. Is the server running?"), { status: 0 });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || "Request failed."), { status: res.status, code: data.code, data });
  return data;
}
