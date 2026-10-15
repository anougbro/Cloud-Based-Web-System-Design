const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(message, status = 0, extra = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    Object.assign(this, extra);
  }
}

function fromDetail(detail, fallback) {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first.msg === "string" && first.msg) return first.msg;
    if (typeof first === "string" && first) return first;
  }
  return fallback;
}

export async function api(path, { method = "GET", body, token, signal } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError(`Network error (HTTP 0). The API at ${BASE} is unreachable.`, 0);
  }

  if (res.status === 204) return null;

  const data = await res.json().catch(() => null);
  if (res.ok) return data;

  const detail = data ? data.detail : undefined;

  if (res.status === 401) {
    throw new ApiError(fromDetail(detail, "Session expired. Please log in again."), 401);
  }

  if (res.status === 422) {
    throw new ApiError(fromDetail(detail, "Please check the submitted fields."), 422);
  }

  if (res.status === 429) {
    const retryAfter = res.headers.get("Retry-After") || (data ? data["Retry-After"] : null);
    const suffix = retryAfter ? ` Retry in ${retryAfter}s.` : "";
    throw new ApiError(fromDetail(detail, "Too many requests.") + suffix, 429, { retryAfter });
  }

  if (res.status === 409) {
    throw new ApiError(fromDetail(detail, "This record already exists."), 409);
  }

  const detailText = fromDetail(detail, "");
  throw new ApiError(
    `Server error (HTTP ${res.status}).${detailText ? ` ${detailText}` : ""}`,
    res.status,
  );
}

export const CURRENCY = "€";

export const money = (cents) =>
  `${CURRENCY}${((cents || 0) / 100).toFixed(2).replace(".", ",")}`;