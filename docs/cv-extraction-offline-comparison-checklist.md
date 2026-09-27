# CV Extraction Offline Comparison Checklist

Use this checklist for a controlled, manual comparison of a real CV and its API response.
It complements automated tests; it does not turn a second LLM into a production gate.

## Before comparing

1. Record the application version, configured centralized model, and document format.
2. Keep the original document private; store only approved test fixtures in the repository.
3. Capture the normalized source text and document hyperlink annotations in a secure local test record.
4. Do not include API keys, full CV text, or personal contact details in issue reports.

## Source extraction checks

1. Names, headings, project titles, bullets, and multiline text are readable without split-glyph artifacts.
2. Hyperlink annotations are retained and project repository URLs associate with the correct project once.
3. A sentence ending in a word such as `history.` remains in its active section.
4. Content after a page break remains in the active section unless a real heading starts a new one.

## Candidate comparison checks

1. Explicit identity and contact fields are preserved when the source supports them.
2. Every explicit project and experience record is present once.
3. Every clearly named language, framework, library, tool, platform, API, database, model, and technology is represented in `raw_skills` and in the associated record's `technologies` where applicable.
4. Explicit unknown skills appear with `skill_id=null`; taxonomy is not used as a whitelist.
5. Evidence snippets use the correct section and do not claim support from a different section.
6. Project URLs are associated once and do not overwrite profile URLs.
7. Dates preserve source precision: full dates normalize to `YYYY-MM-DD`, month/year dates to `YYYY-MM`, and year-only dates to `YYYY`.
8. `is_current` follows explicit current/ended wording only.
9. `target_roles` contains explicit desired roles or career tracks, not automatically copied experience titles.
10. Missing summary, certificates, languages, or preferences remain null/empty when absent.

## Reporting a discrepancy

For each discrepancy, record only:

- the Candidate JSON path;
- expected source-supported value category;
- actual value category;
- document format and extraction mode;
- whether the failure is source text, structured extraction, deterministic normalization, taxonomy, evidence, or URL association.

Passing mocked tests proves deterministic behavior and prompt delivery. It does not prove that a provider will make a complete semantic extraction for every real CV; real-CV comparisons should therefore be evaluated separately and safely.
