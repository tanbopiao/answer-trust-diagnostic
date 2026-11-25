# Answer Trust Diagnostic Package

Run a health-check on your **AI assistant's answer verifiability** — locally,
read-only. Can the people who receive your assistant's answers verify them
before acting? **No secret values and no file contents ever leave your
machine.** The report contains only filenames, counts, booleans and
recommendations.

## What it checks

- **Citation requirement** — does the system prompt ask the model to cite the
  source document/section for every answer?
- **Source metadata threading** — does the retrieval pipeline pass source
  metadata (document, section, version) alongside the retrieved text?
- **Abstention policy** — what does the assistant say when the knowledge base
  has no answer: an explicit "not found" or a confident guess?
- **Confidence gating** — is there a retrieval-score threshold before the
  model answers?

## Quick start (2 steps)

Requires Python 3.8+. **No dependencies** — standard library only.

1. Point it at the directory where your assistant's code and prompts live:

   ```bash
   python trust_diagnose.py /path/to/your/assistant
   ```

2. Open `trust_diag_reports/trust_diagnostic_report.md`.

## Fix verification: finding IDs and before/after comparison

Every finding carries a stable ID (e.g. `TRUST-NO-CITATION-PROMPT`,
`TRUST-SOURCE-NOT-PASSED`, `TRUST-NO-ABSTAIN`) and a rough self-fix effort
estimate in person-hours. After fixing, re-run with
`--compare trust_diag_reports/trust_diagnostic_report.json`: the report lists
**resolved**, **new**, **severity changes** and **persisting** findings. Use
"high N→0" as the acceptance criterion instead of a gut feeling.

## Sharing the report

Send `trust_diagnostic_report.md` (or the `.json` file) to
**195162494@qq.com** — individuals and companies welcome. We will return a
written assessment of what your setup needs and how we would fix it.

## License

MIT — see [LICENSE](LICENSE).
