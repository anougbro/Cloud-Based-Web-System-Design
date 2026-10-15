import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ApiError, CURRENCY, api, money } from "./api.js";

const PERIODS = [
  { value: "all", label: "All time" },
  { value: "month", label: "This month" },
  { value: "year", label: "This year" },
];

const PAGE_SIZE = 25;

// Categories offered as suggestions. The input stays free text so an
// unexpected category is never blocked; the list only shortens the common case.
const CATEGORIES = [
  "courses", "transport", "loisirs", "sante", "energie", "telecom", "courses",
  "salaire", "loyer", "freelance", "nourriture",
].filter((v, i, a) => a.indexOf(v) === i);

const HINT_KEY = "pocketwise.roundupHintSeen";

export default function Dashboard({ token, onLogout, onUnauthorized }) {
  const [period, setPeriod] = useState("all");
  const [offset, setOffset] = useState(0);
  const [summary, setSummary] = useState(null);
  const [page, setPage] = useState({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
  const [goals, setGoals] = useState([]);
  const [tx, setTx] = useState({ kind: "expense", category: "", amount: "" });
  const [goal, setGoal] = useState({ name: "", target: "" });
  const [error, setError] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [goalsLoading, setGoalsLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [hintSeen, setHintSeen] = useState(() => {
    try {
      return window.localStorage.getItem(HINT_KEY) === "1";
    } catch {
      return false;
    }
  });
  const seq = useRef(0);
  const goalSeq = useRef(0);
  const confirmRef = useRef(null);
  const uid = useId();

  const periodId = `${uid}-period`;
  const txKindId = `${uid}-kind`;
  const txCategoryId = `${uid}-category`;
  const txAmountId = `${uid}-amount`;
  const goalNameId = `${uid}-goal-name`;
  const goalTargetId = `${uid}-goal-target`;
  const confirmId = `${uid}-confirm`;
  const toastId = `${uid}-toast`;
  const categoriesId = `${uid}-categories`;

  // Polite announcement: a toast is a confirmation, not an interruption, so
  // it must not steal focus or interrupt a screen reader mid-sentence.
  const notify = useCallback((message) => {
    setToast(message);
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const t = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const dismissHint = useCallback(() => {
    setHintSeen(true);
    try {
      window.localStorage.setItem(HINT_KEY, "1");
    } catch {
      /* private mode: the hint simply returns on the next load */
    }
  }, []);

  const handleError = useCallback((err) => {
    if (err instanceof ApiError && err.status === 401) {
      onUnauthorized();
      return;
    }
    setError({
      status: err instanceof ApiError ? err.status : null,
      message: err instanceof ApiError ? err.message : "Unexpected error, please try again.",
    });
  }, [onUnauthorized]);

  const loadData = useCallback(async () => {
    const id = seq.current + 1;
    seq.current = id;
    setLoading(true);
    try {
      const [s, t] = await Promise.all([
        api(`/summary?period=${period}`, { token }),
        api(`/transactions?period=${period}&limit=${PAGE_SIZE}&offset=${offset}`, { token }),
      ]);
      if (seq.current !== id) return;
      setSummary(s);
      setPage(t);
      setError(null);
    } catch (err) {
      if (seq.current !== id) return;
      handleError(err);
    } finally {
      if (seq.current === id) setLoading(false);
    }
  }, [handleError, offset, period, token]);

  const loadGoals = useCallback(async () => {
    const id = goalSeq.current + 1;
    goalSeq.current = id;
    setGoalsLoading(true);
    try {
      const g = await api("/goals", { token });
      if (goalSeq.current !== id) return;
      setGoals(g);
    } catch (err) {
      if (goalSeq.current !== id) return;
      handleError(err);
    } finally {
      if (goalSeq.current === id) setGoalsLoading(false);
    }
  }, [handleError, token]);

  const reload = useCallback(() => Promise.all([loadData(), loadGoals()]), [loadData, loadGoals]);

  // Both loads are async and guarded by a sequence number, so the synchronous
  // part of each call only flips a loading flag before awaiting the network.
  // The rule targets setState used to *derive* state; here it reflects a real
  // external transition (a fetch started by a dependency change), and the
  // alternative -- a data layer -- is a dependency ADR-008 declines on purpose.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => { loadGoals(); }, [loadGoals]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (confirm && confirmRef.current) confirmRef.current.focus();
  }, [confirm]);

  async function run(key, fn, onSuccess) {
    setError(null);
    setBusy(key);
    try {
      await fn();
      await reload();
      if (onSuccess) notify(onSuccess);
    } catch (err) {
      handleError(err);
    } finally {
      setBusy("");
    }
  }

  function changePeriod(next) {
    setPeriod(next);
    setOffset(0);
  }

  async function addTx(e) {
    e.preventDefault();
    const cents = Math.round(parseFloat(tx.amount) * 100);
    if (!Number.isFinite(cents) || cents <= 0) {
      setError({ status: null, message: "Enter an amount greater than 0." });
      return;
    }
    let added = null;
    await run("add-tx", async () => {
      added = await api("/transactions", {
        method: "POST",
        token,
        body: { kind: tx.kind, category: tx.category.trim(), amount_cents: cents },
      });
      setTx({ kind: tx.kind, category: "", amount: "" });
    }, () => {
      dismissHint();
      // The server owns the round-up arithmetic; echoing its value keeps the
      // confirmation honest instead of re-deriving it here.
      if (tx.kind === "expense" && added && added.roundup_cents > 0) {
        return `${money(added.amount_cents + added.roundup_cents)} recorded — ${money(added.roundup_cents)} added to round-up savings.`;
      }
      return `${tx.kind === "income" ? "Income" : "Expense"} of ${money(cents)} recorded.`;
    });
  }

  async function addGoal(e) {
    e.preventDefault();
    const cents = Math.round(parseFloat(goal.target) * 100);
    if (!Number.isFinite(cents) || cents <= 0) {
      setError({ status: null, message: "Enter a target greater than 0." });
      return;
    }
    await run("add-goal", async () => {
      await api("/goals", {
        method: "POST",
        token,
        body: { name: goal.name.trim(), target_cents: cents },
      });
      setGoal({ name: "", target: "" });
    }, () => `Goal "${goal.name.trim()}" created.`);
  }

  function askDeleteTx(t) {
    setConfirm({
      label: "Delete this transaction?",
      text: `${t.occurred_on} · ${t.category} · ${t.kind === "income" ? "+" : "-"}${money(t.amount_cents)}. This cannot be undone.`,
      action: () => run(`tx-${t.id}`, async () => {
        await api(`/transactions/${t.id}`, { method: "DELETE", token });
        if (page.items.length <= 1 && offset > 0) setOffset(Math.max(0, offset - PAGE_SIZE));
      }, () => "Transaction deleted."),
    });
  }

  function askDeleteGoal(g) {
    setConfirm({
      label: "Delete this goal?",
      text: `"${g.name}" and its saved progress of ${money(g.saved_cents)} out of ${money(g.target_cents)} will be lost. This cannot be undone.`,
      action: () => run(`goal-${g.id}`, () => api(`/goals/${g.id}`, { method: "DELETE", token }), () => `Goal "${g.name}" deleted.`),
    });
  }

  const total = page.total || 0;
  const firstRow = total === 0 ? 0 : (page.offset || 0) + 1;
  const lastRow = (page.offset || 0) + page.items.length;
  const pageIndex = Math.floor((page.offset || 0) / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main>
      <header>
        <h1>PocketWise</h1>
        <button className="link" onClick={onLogout}>Log out</button>
      </header>

      <fieldset className="period" id={periodId}>
        <legend>Period</legend>
        {PERIODS.map((p) => (
          <label key={p.value} className="chip">
            <input
              type="radio"
              name={`${uid}-period`}
              value={p.value}
              checked={period === p.value}
              onChange={() => changePeriod(p.value)}
            />
            <span>{p.label}</span>
          </label>
        ))}
      </fieldset>

      <div className="toast-slot" role="status" aria-live="polite" aria-atomic="true">
        {toast && <p className="toast" key={toastId}>{toast}</p>}
      </div>

      {error && (
        <p role="alert" className="error">
          {error.status ? <span className="badge">HTTP {error.status}</span> : null}
          {error.message}
        </p>
      )}

      <section className="stats" aria-label="Summary" aria-busy={loading}>
        <div className="card">
          <span>Balance</span>
          <strong>{summary ? money(summary.balance_cents) : "—"}</strong>
        </div>
        <div className="card">
          <span>Income</span>
          <strong>{summary ? money(summary.income_cents) : "—"}</strong>
        </div>
        <div className="card">
          <span>Spent (incl. round-ups)</span>
          <strong>{summary ? money(summary.expense_cents) : "—"}</strong>
        </div>
        <div className="card accent">
          <span>Round-up savings</span>
          <strong>{summary ? money(summary.roundup_savings_cents) : "—"}</strong>
        </div>
        {summary && summary.unallocated_savings_cents > 0 && (
          <div className="card accent-soft">
            <span>Not yet allocated</span>
            <strong>{money(summary.unallocated_savings_cents)}</strong>
            <span className="hint">Available to allocate to a goal.</span>
          </div>
        )}
      </section>

      {/* The round-up rule is explained once, then it gets out of the way.
          It used to live permanently inside the "Spent" tile, competing with
          the number it was meant to illustrate. */}
      {!hintSeen && (
        <aside className="teach" aria-label="How round-up savings work">
          <p className="teach-body">
            Every expense is charged to the next whole {CURRENCY}1. A {money(1250)} purchase
            is recorded as {money(1300)}, and the {money(50)} difference is set aside.
          </p>
          <button type="button" className="link" onClick={dismissHint}>Got it</button>
        </aside>
      )}

      <section className="grid">
        <div className="card">
          <h2>Add transaction</h2>
          <form onSubmit={addTx}>
            <label htmlFor={txKindId}>Type</label>
            <select id={txKindId} value={tx.kind} onChange={(e) => setTx({ ...tx, kind: e.target.value })}>
              <option value="expense">Expense</option>
              <option value="income">Income</option>
            </select>
            <label htmlFor={txCategoryId}>Category</label>
            <input
              id={txCategoryId}
              name="category"
              list={categoriesId}
              placeholder="food, rent…"
              autoComplete="off"
              required
              value={tx.category}
              onChange={(e) => setTx({ ...tx, category: e.target.value })}
            />
            <datalist id={categoriesId}>
              {CATEGORIES.map((c) => <option key={c} value={c} />)}
            </datalist>
            <label htmlFor={txAmountId}>Amount</label>
            <div className="field">
              <span className="cur" aria-hidden="true">{CURRENCY}</span>
              <input
                id={txAmountId}
                name="amount"
                type="number"
                step="0.01"
                min="0.01"
                inputMode="decimal"
                placeholder="0.00"
                required
                value={tx.amount}
                onChange={(e) => setTx({ ...tx, amount: e.target.value })}
              />
            </div>
            <button type="submit" disabled={busy === "add-tx"}>{busy === "add-tx" ? "Adding…" : "Add"}</button>
          </form>
        </div>

        <div className="card" aria-busy={goalsLoading}>
          <h2>Savings goals</h2>
          <form onSubmit={addGoal}>
            <label htmlFor={goalNameId}>Goal name</label>
            <input id={goalNameId} name="goal" placeholder="New laptop" required value={goal.name} onChange={(e) => setGoal({ ...goal, name: e.target.value })} />
            <label htmlFor={goalTargetId}>Target</label>
            <div className="field">
              <span className="cur" aria-hidden="true">{CURRENCY}</span>
              <input
                id={goalTargetId}
                name="target"
                type="number"
                step="0.01"
                min="0.01"
                inputMode="decimal"
                placeholder="0.00"
                required
                value={goal.target}
                onChange={(e) => setGoal({ ...goal, target: e.target.value })}
              />
            </div>
            <button type="submit" disabled={busy === "add-goal"}>{busy === "add-goal" ? "Adding…" : "Add goal"}</button>
          </form>
          {goalsLoading && <p className="state" role="status">Loading goals…</p>}
          {!goalsLoading && goals.length === 0 && <p className="state">No goal yet. Create one to start tracking your savings.</p>}
          <ul className="goals">
            {goals.map((g) => (
              <li key={g.id} className="goal">
                <div className="goal-head">
                  <span>{g.name}: {money(g.saved_cents)} / {money(g.target_cents)}</span>
                  <span className="goal-pct">{Math.round(g.progress_pct)}%</span>
                  <button
                    type="button"
                    className="link danger"
                    disabled={busy === `goal-${g.id}`}
                    aria-label={`Delete goal ${g.name}`}
                    onClick={() => askDeleteGoal(g)}
                  >
                    Delete
                  </button>
                </div>
                <progress max="100" value={g.progress_pct} aria-label={`${g.name} progress`} />
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="card" aria-busy={loading}>
        <h2>Transactions</h2>

        {confirm && (
          <div className="confirm" role="alertdialog" aria-labelledby={confirmId}>
            <p id={confirmId} className="confirm-title">{confirm.label}</p>
            <p className="muted">{confirm.text}</p>
            <div className="confirm-actions">
              <button
                type="button"
                ref={confirmRef}
                className="danger-btn"
                disabled={Boolean(busy)}
                onClick={() => { const action = confirm.action; setConfirm(null); action(); }}
              >
                Yes, delete permanently
              </button>
              <button type="button" className="link" onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        )}

        {loading && <p className="state" role="status">Loading transactions…</p>}
        {!loading && total === 0 && <p className="state">No transaction for this period.</p>}

        {!loading && total > 0 && (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Category</th>
                    <th scope="col">Amount</th>
                    <th scope="col">Round-up</th>
                    <th scope="col"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((t) => (
                    <tr key={t.id}>
                      <td>{t.occurred_on}</td>
                      <td>{t.category}</td>
                      <td className={t.kind}>{t.kind === "income" ? "+" : "-"}{money(t.amount_cents)}</td>
                      <td>{t.roundup_cents ? money(t.roundup_cents) : ""}</td>
                      <td className="actions">
                        <button
                          type="button"
                          className="link danger"
                          disabled={busy === `tx-${t.id}`}
                          aria-label={`Delete transaction ${t.category} of ${money(t.amount_cents)} on ${t.occurred_on}`}
                          onClick={() => askDeleteTx(t)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="pagination">
              <span className="muted">{total} transaction{total > 1 ? "s" : ""} · showing {firstRow}–{lastRow}</span>
              <div className="pager">
                <button type="button" className="link" disabled={page.offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
                <span className="muted">Page {pageIndex} / {pageCount}</span>
                <button type="button" className="link" disabled={lastRow >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
              </div>
            </div>
          </>
        )}
      </section>
    </main>
  );
}