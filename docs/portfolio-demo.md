# Portfolio demonstration

Use only bundled fictional records. Start with `make dev` and `make seed`; configure a real provider for model-generated output. Without a provider key, demonstrate the explicit unavailable state. Point to `IMPLEMENTATION_STATUS.md` for verification evidence and remaining integration limits.

1. **Identity and isolation:** sign in as `finance.employee`. Show the current department and real stored activity. Attempt to open an HR document ID; demonstrate backend denial, then sign in as `hr.employee` to show that the authorized path works. Do not infer isolation from hidden navigation alone.
2. **Finance:** upload a synthetic invoice, observe durable ingestion status and review Decimal-based totals, duplicate/date/currency checks and exceptions. Submit a high-value invoice for approval. Sign in separately as `finance.manager`, inspect the evidence, and approve or reject. Show the decision history; no payment is executed.
3. **HR:** ask a policy question answered by an accessible source. Open the source citation. Ask an unsupported question and show the insufficient-evidence result. Create an onboarding checklist, complete tasks and inspect manager review.
4. **Legal:** upload a fictional agreement, inspect structured parties/dates/clauses and review flags, and send it for legal review. Compare two versions if available. Explain that the application cannot execute binding agreements.
5. **Operations:** import conflicting fictional property sources. Show field-level provenance, missing data and contradictory bedroom counts retained for review; the workflow must not silently choose a source as truth.
6. **Workflow builder:** assemble supported nodes, save/publish the definition and run it. Inspect persisted step status, an approval pause and the resumed run. Show a validation error for an invalid or unauthorized step.
7. **Administration:** `platform.admin` changes agent configuration without automatic access to HR source files. Show the distinction between platform permissions and confidential business memberships.
8. **Monitoring:** inspect stored executions, token usage/cost estimates, processing failures, audit IDs and approval decisions. Clearly separate seeded history from new live actions. Disconnect a provider or omit its key to demonstrate a visible failure instead of fabricated success.

For a restart demonstration, pause a workflow at approval, restart the worker, approve, and inspect the continued stored run. Record the actual outcome; persistence code and unit tests alone do not prove a successful deployed restart exercise.
