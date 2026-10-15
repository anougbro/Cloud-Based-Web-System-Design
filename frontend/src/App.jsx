import { Component, useCallback, useState } from "react";
import Auth from "./Auth.jsx";
import Dashboard from "./Dashboard.jsx";
import { ApiError, api } from "./api.js";

export class ApiErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    if (error instanceof ApiError && error.status === 401) {
      this.setState({ error: null });
      this.props.onUnauthorized();
    }
  }

  render() {
    const { error } = this.state;
    if (error && !(error instanceof ApiError && error.status === 401)) {
      return (
        <main>
          <div className="card state error" role="alert">
            <h2>The application stopped unexpectedly</h2>
            <p>{error.message}</p>
            <button onClick={() => this.setState({ error: null })}>Try again</button>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem("token"));

  const save = useCallback((t) => {
    sessionStorage.setItem("token", t);
    setToken(t);
  }, []);

  const logout = useCallback(() => {
    const active = sessionStorage.getItem("token");
    sessionStorage.removeItem("token");
    setToken(null);
    if (!active) return;
    api("/auth/logout", { method: "POST", token: active }).catch(() => {});
  }, []);

  const onUnauthorized = useCallback(() => {
    logout();
  }, [logout]);

  return (
    <ApiErrorBoundary onUnauthorized={onUnauthorized}>
      {token ? <Dashboard token={token} onLogout={logout} onUnauthorized={onUnauthorized} /> : <Auth onToken={save} />}
    </ApiErrorBoundary>
  );
}