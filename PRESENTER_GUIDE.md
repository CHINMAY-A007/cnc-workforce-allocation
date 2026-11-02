# Presenter Guide — CNC Workforce Allocation Demo (8-step script)

Audience: client / stakeholder walkthrough. Total time: ~2 minutes.
Prerequisite: the app is running (http://localhost:8000 or your live URL). Role selector = Production Manager.

## Before you start

1. Open the app.
2. On the home page, click **"Start the 2-minute demo"**. This resets clean seeded data and highlights Step 1 of the guided bar.
3. Keep the **Presenter notes** panel (collapsible, on the home page) open — it gives the exact click + one-line talking point for each step.
4. Everything shown is labeled **"Demo data — Sample CNC Works, Bangalore"**; the "ERP" is a local SQLite simulation.

## The 8-step demo

| Step | Exact clicks | One-line talking point |
|------|--------------|------------------------|
| 1. Open Home / Start demo | Home → click **"Start the 2-minute demo"** (resets data, highlights Step 1) | "Every order, employee and order here is fictional demo data for Sample CNC Works." |
| 2. Add / view orders | Step 1 → **Open** (Orders and Tasks) → review released orders ORD-1001…ORD-1005 | "We start with released production orders; each carries a product, quantity, priority and due date." |
| 3. Generate tasks / jobs | Step 2 → **Open** (Orders and Tasks) → view the Tasks table | "Each order auto-breaks into jobs — cutting, turning, 5-axis, VMC, deburring, CMM, packing — with skills, levels and dependencies." |
| 4. Get the AI proposal | Step 3 → **Open** (AI Allocation Proposal) → **Generate Schedule** | "The solver assigns every job to an eligible worker within shift, certification and capacity rules — solved in seconds." |
| 5. Explain an assignment | In Proposal → open **"Why this person?"** for a task | "We can show exactly why this worker was picked: skill level, availability, continuity and workload." |
| 6. Review, override & approve | Step 4 → **Open** (Approval and Reassignment) → reassign one task (type a reason) → lock two tasks → **Approve version** | "The production manager reviews, overrides only with a reason, locks critical assignments, then approves the schedule." |
| 7. Handle a surprise | Step 5 → **Open** (Live Progress and Alerts) → Simulate **absence** (pick E07 or E08, the 5-axis staff) → **Approve revised plan** | "When someone is absent, we replan in seconds — locked tasks stay put and everything else moves around them." |
| 8. Verify evidence | **Reports** → utilization / bottleneck / planned vs actual → **Audit and Settings** → audit log | "Every reassignment, lock and approval is logged; reports show utilization, bottlenecks and on-time performance." |

## Talking points (cheat sheet)

- "Sample CNC Works, Bangalore" — all companies, employees, customers and orders are fictional demo data; simulated ERP = local SQLite, no real ERP integration.
- Solver: Google OR-Tools CP-SAT (free, Apache 2.0).
- Role switcher is a demo simulation, not real authentication.
- Reset anytime: **"Start the 2-minute demo"** restores clean seeded data.

## If something goes wrong

- No schedule yet? Generate one on AI Allocation Proposal first (Step 4).
- Replan reports "locked conflicts"? Unlock the conflicting task (Production Manager only) or don't lock it before simulating.
- Zero-eligibility tasks in the "impossible case"? Expected — all certified 5-axis staff are absent; no assignment is invented. Options: extend due date, overtime within caps, reschedule maintenance.
