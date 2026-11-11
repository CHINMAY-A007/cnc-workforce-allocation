# Assumptions
- Working week Monday to Saturday, Sunday off. Shift A 06:00-14:00, Shift B 14:00-22:00. Overtime up to 2 hours per day. Changeable in Audit and Settings.
- Job time in the demo = routing minutes x 4 x lots of 10 pieces + setup. Jobs over 8 hours are split into chunks.
- A job needs the listed skill level and, for the quality gate, a valid certificate on the day it runs.
- The ERP is a local SQLite database with fictional data. Nothing controls a machine.
- Roles are a demo of permissions, not authentication.
- Planning window is one week from the next working day (14 days is offered as a what-if when a week is not enough).
- Raw-material stock is illustrative demo data (units per piece by product; one material is deliberately short so the shortage flow is visible). Material "reservations" are written on schedule approval and released when a schedule is superseded; they are advisory, not a real ERP posting.
- Resource analysis "required" figures are the peak simultaneous demand if every job started as early as possible; the weekly capacity check then distinguishes a true deficit from a timing peak.
