# PocketWise — 10-Minute Presentation Script

**Format:** 7 min slides + 3 min live demo. Timings are cumulative targets, not hard cuts.
**Slide count:** 8. Do not read the slides — they carry keywords only.

---

## Timing Map

| Time | Section | Mode |
|---|---|---|
| 0:00–0:45 | Problem | Slide 1 |
| 0:45–2:30 | Evidence & literature | Slide 2 |
| 2:30–4:15 | Architecture & key decisions | Slides 3–4 |
| 4:15–7:15 | **Live demo** | Live app |
| 7:15–8:45 | Security, testing, deployment | Slides 5–6 |
| 8:45–9:30 | Limitations | Slide 7 |
| 9:30–10:00 | Conclusion & questions | Slide 8 |

**Rehearsal rule:** if you are over 8 minutes when you start the demo, cut Slide 4 (key decisions) to the two decisions named below and move on. The demo is worth more than the slides.

---

## Slide 1 — The Problem (0:00–0:45)

**On screen:** `18% of students score low on financial literacy. 80% think they're good at it.`

> Most money advice is information. Students are told to budget and save. That advice is sound, and it largely doesn't work.
>
> The reason isn't knowledge — it's that budgets are intentions, and intentions are fragile. A spreadsheet is a recurring task. Recurring tasks get abandoned.

**Do:** pause after the 18%/80% contrast. It is the single most memorable number in the presentation.

---

## Slide 2 — Why Automation, Not Education (0:45–2:30)

**On screen:** `Knowledge decays. Defaults don't compete for willpower.`

> Two findings shaped the design.
>
> **First:** knowledge interventions work, then fade. A systematic review of 44 studies on young college students finds measurable but decaying effects. One study tracked cohorts for three years — gains held, but softened.
>
> **Second:** automatic saving works. Choi et al. analysed nine natural experiments and found automatic enrolment lifts steady-state saving by about 0.6% of income.
>
> Their title is "Smaller Than We Thought?" — and I've adopted that as an honesty constraint. It works, but modestly.

**Then the pivot:**

> So I didn't build a better budget. I removed the decision.
>
> Every expense is charged to the next whole euro. The difference goes to savings. A €12.50 purchase becomes €13.00, and €0.50 is redirected. You never perform a saving action — the system saves on your behalf, and the cost is about one euro.

**Anticipated challenge:** *"One euro isn't much."* → Agree immediately. "You're right, and I'll come back to exactly how small this is, in the limitations. The mechanism is an initiator, not a wealth strategy. What it does is establish the habit at near-zero cost and make the pot visible."

---

## Slide 3 — Architecture (2:30–3:15)

**On screen:** the flowchart from `README.md`.

> Three tiers. React SPA on a CDN, FastAPI in a Docker container, managed PostgreSQL.
>
> The browser talks directly to the API — no proxy through the static site — so the API scales independently.
>
> Two deployables, both declared in a `render.yaml` blueprint, so the infrastructure is reproducible from the repository.

**Do not** read the diagram. Point at it, describe the three tiers in one sentence, move on.

---

## Slide 4 — Two Decisions That Shaped Everything (3:15–4:15)

**On screen:** `Integer cents, end to end` / `Savings are derived, not stored`

> Two decisions do most of the work.
>
> **One: money is integer cents everywhere.** No float touches a monetary path. This matters more than usual here, because the product's entire value is a rounding calculation performed thousands of times — and floating-point errors accumulate.
>
> **Two: savings are computed, never stored.** No savings balance is persisted. It's recalculated from transactions on every read. That costs an aggregation per read — but it means deleting an expense automatically reduces goal progress, with no compensating logic to get wrong.

**If cutting for time:** say only these two sentences and move to the demo.

---

## Demo (4:15–7:15)

**Open the live URL before you start presenting. Log in. Clear any stale state.**

| # | Action | Say this | Why |
|---|---|---|---|
| 1 | Point at balance, income, spent | "One user, three months of real transactions." | Shows it works, not a mockup |
| 2 | **Enter €12.50, groceries, expense → Add** | "Watch the round-up column." | The core mechanic, live |
| 3 | Point at new row + round-up savings | "€0.50 moved. The transaction still reads €12.50 — that's the user's amount." | Shows the split |
| 4 | **Delete it** | "Now watch the goals." | Proves the derived-state decision |
| 5 | Point at goal progress dropping back | "No compensation code exists. It can't be inconsistent because it isn't stored." | Best moment in the demo |
| 6 | Show goals, add one | "Savings fill goals oldest-first." | Ties to the literature |

**Total demo budget: 3 minutes.** If you're running long, cut rows 6 and do 1–5 only.

**If anything breaks:** say so. "That's actually the audit log — deletion is a financial event and gets logged." Then move on. Do not debug live.

---

## Slide 5 — Security (7:15–8:00)

**On screen:** `Fail-closed by design`

> Passwords use PBKDF2 at 600,000 iterations, constant-time comparison. Login returns identical errors for unknown accounts and wrong passwords.
>
> Two things worth calling out:
>
> **JWTs are stateless, so they can't be revoked** — which means logout would be a lie without a denylist. I built one, indexed on token ID, self-pruning on expiry.
>
> **Validation errors are rebuilt from an allow-list.** FastAPI echoes Pydantic's payload by default, and that payload contains `input` — the plaintext password. Left alone, it lands in browser history and proxy logs.

**Do not** recite the full threat model. Say: "The full model and the residual risks are in `docs/security.md`."

---

## Slide 6 — Engineering and Deployment (8:00–8:45)

**On screen:** `72 tests · 93.3% coverage · clean lint & types · deployed`

> 72 tests at 93.3% coverage, with coverage enforced as a hard CI gate — below threshold fails the build rather than producing a report nobody reads.
>
> Clean on ruff and mypy strict, with exact dependency pins.
>
> Deployed on Render via a Blueprint, with Alembic managing schema changes. That last one matters: `create_all` can't alter an existing table, so it would silently freeze the schema at first boot and fail weeks later with no error.

**Then the strongest point in the whole presentation:**

> The layering paid for itself. Isolating pure business rules made the valuable logic testable without a database or HTTP — and that directly exposed a production bug. Two modules had imported the audit *function* while calling `audit.audit(...)`, an attribute access on a function object. Logout and rate-limiting were returning HTTP 500 in production. Three tests caught it.
>
> That's the argument for the architecture, not just for the tests.

---

## Slide 7 — Limitations (8:45–9:30)

**On screen:** `Not a behavioural study. Honest about it.`

> The biggest thing this project does **not** show: that round-up saving changes behaviour for students. I validated engineering correctness and deployability. I ran no user study.
>
> And the arithmetic is genuinely small. Spending €400 a month with a €0.30 average round-up is about €10 a month, roughly €130 a year. Meaningful against a €600 emergency fund. Not meaningful against a laptop.
>
> So it's an initiator mechanism, and I've labelled it as one.
>
> Two engineering limits too: the rate limiter is in-process memory, so horizontal scaling doubles the effective limit — Redis behind the same interface is the fix. And there's no password-change or account-deletion endpoint, both of which a real deployment needs.

**Deliver this section confidently.** Naming your limits is the mark of a professional assessment, and the examiner will have found them anyway. Finding them first is the better position.

---

## Slide 8 — Conclusion (9:30–10:00)

**On screen:** `Remove the decision, not improve the advice.`

> To summarise: student saving behaviour fails at the moment of decision, not at the moment of understanding. So I removed the decision, and attached the result to concrete goals.
>
> Deployed, tested, documented, and honest about where it stops working.
>
> Questions.

---

## Likely Questions — Prepare These

**"How is this different from Acorns?"**
> Mechanically similar. Differences: Acorns sweeps accumulated change into investments; I keep it as cash against named goals, because a student's problem is a €600 emergency fund, not a portfolio. No brokerage, no market risk, no KYC — which also means no regulated-entity dependency for a student project.

**"Why not just save a fixed percentage of income?"**
> Because it requires a recurring decision, and income is irregular for students — freelance work, scholarships, part-time hours. The round-up keys off spending, which happens continuously, and the amount is too small to require a decision at all.

**"Isn't €0.50 per transaction meaningless?"**
> Yes, individually, and I've said so. The design claim is about removing friction, not about the size of the sum. The evidence base I drew on is about automation and defaults generally, not round-ups specifically — Choi et al.'s own framing is that the effect is smaller than assumed.

**"How would you scale this?"**
> In order: shared rate-limit store (Redis, same interface, algorithm ports unchanged via atomic Lua); a daily aggregate table if per-user history grows; then horizontal scaling. The derived-savings design is already scale-friendly — it moves no state between instances, so there's no session affinity requirement.

**"How do you prevent users seeing each other's data?"**
> Every query is scoped by the authenticated user ID resolved from the JWT — there's no endpoint that accepts a user ID from the client. Deletion cascades at the database level.

**"What would you do differently?"**
> Start with the deployment earlier. I treated it as the last milestone; it's the only deliverable with external dependency and external latency, so it should have been validated in the first hour. I'd also have written tests for logout specifically — it was the exact bug that shipped broken.

**"Why FastAPI over Django/Flask?"**
> Django brings a template system, admin and ORM conventions I don't need for a JSON API consumed by a hand-written SPA. FastAPI derives validation from Pydantic schemas and response docs from return types for free, and `Depends` makes auth and session injection readable. The honest counterweight: Django would have given me the admin interface and migrations for free, and I wrote both by hand.

---

## Pre-presentation Checklist

- [ ] Live URL opens and login works **before** you present
- [ ] Slides render (not a text editor — export to PDF or open in a real viewer)
- [ ] `pytest`, `ruff`, `mypy` all green, in case it's asked live
- [ ] Demo data present — not an empty account
- [ ] Browser zoom 100%, devtools closed, notifications off
- [ ] Timing rehearsed at least twice with a stopwatch
- [ ] `REPORT.md` submitted, `docs/` pushed, public repo link ready to share
