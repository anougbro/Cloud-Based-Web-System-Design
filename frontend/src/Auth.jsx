import { useId, useState } from "react";
import { ApiError, api } from "./api.js";

export default function Auth({ onToken }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const uid = useId();
  const emailId = `${uid}-email`;
  const passwordId = `${uid}-password`;
  const hintId = `${uid}-hint`;

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const data = await api(path, { method: "POST", body: { email, password } });
      onToken(data.access_token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unexpected error, please try again.");
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(mode === "login" ? "register" : "login");
    setError("");
  }

  return (
    <form className="card auth" onSubmit={submit}>
      <h1>PocketWise</h1>
      <p className="muted">Budget smarter. Save your spare change.</p>
      <label htmlFor={emailId}>Email</label>
      <input
        id={emailId}
        name="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <label htmlFor={passwordId}>Password</label>
      <input
        id={passwordId}
        name="password"
        type="password"
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        required
        minLength={8}
        aria-describedby={hintId}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <p className="hint" id={hintId}>At least 8 characters.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}</button>
      <button type="button" className="link" onClick={switchMode} disabled={busy}>
        {mode === "login" ? "Need an account? Register" : "Have an account? Log in"}
      </button>
    </form>
  );
}