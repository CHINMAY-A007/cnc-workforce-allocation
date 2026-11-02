# Presenter guide - CNC Workforce Allocation demo

Audience: client walkthrough, about 5 minutes. Keep the role switcher on Production Manager. All people, customers and orders are fictional ("Sample CNC Works, Bangalore"). The ERP is a local simulation.

The app has a built-in script: on the Home screen the six guided steps tick off as you go, and **Demo script** (top right) shows what to say on each screen.

## Fast path
Home -> **Prepare a ready schedule for me**. It creates a schedule and approves it as the manager. Then jump to Schedule Chart, or run the full path below.

## Full path
| Step | Click | Say |
|---|---|---|
| 1 Orders | Orders and Tasks | "Five released orders from the ERP. Each already has jobs from its routing." |
| 2 Add an urgent order | Fill the demo example -> Create order | "A note like 'certified inspector only' becomes a rule on the right job. Phrases the reader does not know are shown, not guessed." |
| 3 Who is allowed | Workforce and Skills, or Who can do this? on a job | "Every exclusion has a reason: skill level, expired certificate, leave." |
| 4 AI proposal | AI Allocation Proposal -> Generate schedule | "Person, machine and time for every job, and a reason for each. If no plan exists it says why and what would help." |
| 5 You decide | Approval and Changes: change a person (reason needed), lock a job, Approve | "Nothing is final until a manager approves. Locked jobs never move silently." |
| 6 Surprise | Live Progress and Alerts: Simulate absence | "Only the affected jobs are replanned. Unrelated jobs keep their person, machine and time. You see what changed and approve or discard." |
| Extra | Run the impossible case | "If nobody qualified is available, the app refuses to invent a plan and explains." |
| Evidence | How it works / Requirements -> Run the self-test | "A scratch-copy run of the whole workflow checks each of the 15 requirements." |

## Honest limits to mention if asked
- The solver (Google OR-Tools CP-SAT) is free and runs on the server. The note reader uses keywords only, with no outside AI service, unless the owner turns it on.
- The role switcher shows permissions. It is not a login.
- On a free Render instance the database resets when the service restarts. Use "Download a backup" first if you need the data.
