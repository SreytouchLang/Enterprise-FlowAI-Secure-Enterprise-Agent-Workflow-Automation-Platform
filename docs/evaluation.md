# Evaluation methodology

Run `make eval` after `make setup`. The evaluator runs synthetic cases and calculates its output from executed results. See `IMPLEMENTATION_STATUS.md` for the exact verified command and result from this implementation session. Do not substitute expected scores for measured results.

## Scope

Use separate fictional fixtures for invoice arithmetic/field extraction, HR retrieval/citations, legal structured review, property normalization/conflict handling, workflow completion and unauthorized-access attempts. Deterministic domain tests and a test-only model adapter measure orchestration correctness; they do not establish the quality of a live OpenAI or Anthropic model.

| Dimension | Definition |
|---|---|
| Extraction field accuracy | Correct expected fields divided by evaluated fields |
| Retrieval precision | Relevant retrieved chunks divided by retrieved chunks |
| Retrieval recall | Relevant retrieved chunks divided by known relevant chunks |
| Citation correctness | Supported authorized citations divided by returned citations |
| Unsupported answers | Answers without sufficient source support divided by answered cases |
| Workflow completion | Runs reaching the expected terminal state divided by attempted runs |
| Tool errors | Tool executions failing schema, authorization or runtime checks |
| Isolation violations | Unauthorized resources returned or acted on; expected count is zero |
| Latency | Measured wall-clock duration of executed cases |
| Usage/cost | Recorded provider tokens and configured rate estimates when a provider was actually invoked |

A metric with no applicable cases should be omitted or labeled unavailable; zero tokens in a deterministic run is not evidence of inexpensive real-model performance. Synthetic seeded history is explicitly marked and should not be reported as live operational success.

## Live-provider campaign

For a real-model assessment, record provider, model version, prompt version, retrieval settings, dataset hash, repeat count and date. Run the same permitted fixtures with real keys in an isolated environment. Report confidence intervals or per-case outputs, inspect unsupported claims manually, and account for API spend. Keep model-quality conclusions separate from security invariants: unauthorized retrieval must remain impossible regardless of model behavior.

CI runs offline repeatable checks. External provider evaluation is intentionally a controlled, explicitly configured operation because it transmits inputs and incurs costs. No live-model score is claimed merely because an SDK adapter exists.
