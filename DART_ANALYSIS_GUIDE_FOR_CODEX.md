# DART Analysis Guide for Codex

## Purpose
This document defines the practical analysis methodology for a DART-based disclosure analysis service.

The goal is **not** to generate vague AI summaries. The goal is to build a system that:
- collects DART disclosures reliably,
- extracts structured facts,
- evaluates them with explicit rules,
- produces evidence-based reports for human review.

This guide should be treated as the implementation reference before writing analysis code.

---

## Non-Negotiable Principles

1. **Do not fabricate facts.**
   - Never invent filing content, company conditions, risk levels, financial trends, or repository state.
   - If a value is unavailable or not yet parsed, mark it as unknown.

2. **Evidence first, wording second.**
   - Every conclusion must be backed by parsed fields, numeric values, or directly cited filing sections.
   - Report generation is downstream of structured extraction.

3. **Rule-based judgment first, LLM-style wording last.**
   - The core system should work even without a language model.
   - Narrative phrasing is optional; factual extraction and scoring are mandatory.

4. **Keep the pipeline maintainable.**
   - Separate collection, normalization, signal extraction, evaluation, and reporting.
   - Avoid coupling raw API response handling directly to final report text.

5. **User-facing outputs must be in Korean.**
   - Internal reasoning, code comments, and implementation planning may be in English.
   - Any progress report, explanation, summary, or final report shown to the user must be in Korean.

---

## Target Service Scope

The service should eventually support:
- search by company name, stock code, or corp code,
- retrieval of recent DART disclosures,
- disclosure type classification,
- extraction of key signals,
- rule-based risk evaluation,
- structured Korean reports with evidence.

The service should **not** start with investment recommendations such as “buy” or “sell.”
The first stable goal is **disclosure reading assistance and risk detection**.

---

## Analysis Pipeline

Implement the system in the following stages.

### 1. Collection Layer
Responsibilities:
- call DART API using `DART_API_KEY`,
- fetch company metadata if needed,
- fetch disclosure lists,
- store raw responses safely,
- handle API errors and retries,
- preserve source identifiers and timestamps.

Expected outputs:
- raw disclosure metadata,
- normalized disclosure list entries,
- request/response trace information for debugging.

### 2. Normalization Layer
Responsibilities:
- normalize field names,
- standardize dates, company identifiers, and disclosure type labels,
- deduplicate the same disclosure across repeated fetches,
- map raw filing names into internal categories.

Expected outputs:
- a consistent filing schema,
- canonical disclosure type,
- minimal normalized document metadata.

### 3. Extraction Layer
Responsibilities:
- extract structured signals from disclosures,
- identify numeric and event-based information,
- preserve evidence references such as section name, source field, filing title, filing date.

Expected outputs:
- event signals,
- financial signals,
- governance signals,
- legal or risk signals,
- evidence snippets or source references.

### 4. Evaluation Layer
Responsibilities:
- turn extracted signals into interpretable judgments,
- compute risk flags or scores,
- explain why a signal matters.

Expected outputs:
- risk flags,
- category-level evaluations,
- scoring rationale.

### 5. Reporting Layer
Responsibilities:
- generate a readable Korean report,
- show findings in a structured format,
- attach evidence and reasons,
- clearly separate fact from interpretation.

Expected outputs:
- concise summary,
- key positives and negatives,
- risk checklist,
- evidence-backed reasoning.

---

## Recommended Internal Data Model

The exact schema may evolve, but the service should conceptually support the following entities.

### Company
- company_name
- stock_code
- corp_code
- market_type

### Filing
- filing_id or receipt_no
- company identifier
- filing_title
- filing_date
- filing_type_raw
- filing_type_normalized
- source_url or source reference
- raw_payload

### Signal
- company identifier
- filing identifier
- signal_category
- signal_type
- signal_value
- signal_unit
- signal_direction if applicable
- evidence_text or evidence_reference
- confidence or extraction_status

### Evaluation
- company identifier
- evaluation_date
- category
- score or flag
- reason
- linked_signals

### Report
- company identifier
- report_date
- summary_ko
- positives_ko
- negatives_ko
- risks_ko
- evidence_links

---

## Disclosure Categories to Normalize First

Start with a practical subset. The system does not need to support every possible filing category on day one.

### Core Periodic Filings
- business report
- quarterly report
- semiannual report

### Capital / Dilution Events
- rights offering
- convertible bond
- bond with warrant
- third-party allotment
- treasury stock related event if relevant later

### Ownership / Governance Events
- major shareholder change
- largest shareholder change
- insider purchase or sale if available through linked disclosures or datasets later
- executive or board-related changes if material

### Business / Contract Events
- major supply contract
- investment / facility expansion
- acquisition / disposal
- new business entry if material

### Risk / Legal Events
- litigation
- embezzlement / breach of trust
- trading suspension related event if linked in disclosures later
- audit opinion related issue if available from filings

Do not try to normalize everything at once. Start with the categories that materially affect risk assessment.

---

## Signal Types to Extract First

### A. Financial Signals
Extract when available from periodic reports or structured financial disclosures.

Examples:
- revenue
- operating profit
- net income
- operating cash flow
- total debt or borrowings if available
- equity changes if material

Derived signals:
- revenue growth or decline
- repeated operating losses
- profit turnaround or reversal
- cash flow mismatch vs accounting profit

### B. Dilution Signals
Examples:
- existence of convertible bond issuance
- existence of bond with warrant issuance
- rights offering occurrence
- repeated capital raising within a defined time window

Derived signals:
- dilution risk present
- repeated fundraising pattern
- capital structure stress indicator

### C. Ownership / Governance Signals
Examples:
- largest shareholder change
- repeated control-related changes
- management instability indicators

Derived signals:
- control instability risk
- governance uncertainty

### D. Legal / Operational Risk Signals
Examples:
- litigation filing
- embezzlement or breach of trust notice
- audit-related warning if available
- material operational disruption indicator if disclosed

Derived signals:
- legal risk
- trust / governance risk
- operational disruption risk

### E. Contract / Business Momentum Signals
Examples:
- large supply contract
- facility investment
- disposal/acquisition event

Derived signals:
- potential business expansion
- event significance requiring later verification

Important: a contract filing alone is **not automatically positive**. The report should note that execution and later financial reflection still need verification.

---

## Evidence Requirements

Every extracted signal should retain evidence.

Preferred evidence structure:
- filing title,
- filing date,
- filing identifier,
- source section or source field,
- original extracted value,
- short evidence text or reference.

Examples:
- “전환사채 발행 결정” filing dated YYYY-MM-DD
- periodic filing showing operating loss for N consecutive quarters
- largest shareholder change filing with explicit event date

If evidence cannot be attached, the signal should be considered incomplete.

---

## Recommended Evaluation Logic

Do not start with a black-box score. Start with explicit rule-based flags and then optionally aggregate them.

### Example Rule Areas

#### 1. Profitability Deterioration
Possible rule examples:
- operating loss in 3 or more of the last 4 quarters
- revenue decline with loss expansion

#### 2. Cash Flow Weakness
Possible rule examples:
- operating cash flow negative while accounting profit is positive
- repeated negative operating cash flow

#### 3. Dilution Risk
Possible rule examples:
- convertible bond issuance within the last 12 months
- bond with warrant issuance within the last 12 months
- rights offering within the last 12 months
- multiple fundraising events in a short window

#### 4. Governance Instability
Possible rule examples:
- largest shareholder change within the last 12 months
- repeated shareholder control changes

#### 5. Legal / Trust Risk
Possible rule examples:
- litigation present
- embezzlement / breach of trust filing present
- audit warning if later supported

### Output Style for Evaluation
The system should produce explainable evaluation objects like:
- `flag`: true / false
- `severity`: low / medium / high
- `reason`: explicit Korean text
- `evidence`: linked filing references

Example:
- flag: true
- severity: high
- reason: “최근 12개월 내 전환사채 및 유상증자 관련 자금조달 공시가 반복 확인되었습니다.”
- evidence: [filing A, filing B]

---

## Korean Report Structure

The user-facing report should stay structured and practical.

### Recommended Sections

#### 1. 한 줄 요약
A one-line Korean summary that does not overclaim.

Examples:
- “실적보다 자금조달 리스크 확인이 우선인 종목입니다.”
- “흑자 전환 여부보다 현금흐름 지속성을 더 확인해야 합니다.”

#### 2. 핵심 포인트
- recent periodic filing observations,
- major event filings,
- changes in capital or governance,
- notable risks.

#### 3. 위험 신호
List concrete flags such as:
- 희석 위험,
- 수익성 악화,
- 현금흐름 불안,
- 지배구조 변동,
- 법률 리스크.

#### 4. 근거 공시
For each major claim, list the supporting disclosure(s).

#### 5. 해석상 유의사항
Clearly separate fact from inference.
Examples:
- “공급계약 공시는 확인되지만 실제 매출 반영 여부는 후속 분기 실적 확인이 필요합니다.”
- “현재 추출 범위 내 기준이며, 일부 세부 수치는 후속 파싱 고도화 시 보완될 수 있습니다.”

---

## What the System Must Avoid

1. **No investment recommendation language** in the initial version.
   - Avoid “buy,” “sell,” “target price,” or certainty language.

2. **No unsupported optimism.**
   - A single contract or investment filing is not enough to conclude strong improvement.

3. **No unsupported pessimism.**
   - A single negative event without context should not define the entire company.

4. **No hidden judgment.**
   - If a score is shown, the reason and evidence must also be shown.

5. **No mixing unavailable values with inferred values without labels.**
   - Unknown stays unknown.
   - Derived interpretation must be labeled as interpretation.

---

## Suggested MVP Order

Build in this order.

### Phase 1: Minimal Vertical Slice
- Django project scaffold
- basic app
- DART client using `DART_API_KEY`
- endpoint that accepts company identifier input
- fetch or validate minimal DART metadata
- return structured JSON

### Phase 2: Filing List + Category Normalization
- recent filing retrieval
- normalized filing categories
- storage or in-memory normalized objects

### Phase 3: Core Signal Extraction
- dilution-related events
- largest shareholder change
- repeated losses from periodic data if accessible

### Phase 4: Rule-Based Evaluation
- initial risk flags
- explainable Korean reasons

### Phase 5: Korean Report Generation
- evidence-linked structured report
- HTML or JSON response format

### Phase 6: Persistence / History / Tests
- DB models
- caching
- retry policy
- unit tests and sample fixtures

---

## Suggested Folder Direction

Use this only as a directional guideline, not a rigid requirement.

- `project/` or Django project config
- `apps/disclosures/`
- `apps/analysis/`
- `apps/reports/`
- `clients/dart_client.py`
- `services/normalizers/`
- `services/extractors/`
- `services/evaluators/`
- `services/reporting/`
- `tests/`

Main point: keep API client, extraction logic, evaluation logic, and report formatting separate.

---

## Minimum Quality Standard for Codex Work

When implementing based on this guide, Codex should:
- inspect existing files before changing them,
- report findings in Korean,
- identify modified and newly created files clearly,
- explain why each major implementation step was chosen,
- avoid pretending unimplemented analysis already works,
- mark TODOs honestly where parsing depth is not yet complete.

---

## Final Instruction

This repository should be developed as a **fact-first disclosure analysis system**.

Priority order:
1. data collection reliability,
2. normalized schema,
3. evidence-preserving extraction,
4. explainable evaluation,
5. readable Korean reporting.

If there is any conflict between “fast demo output” and “trustworthy evidence-based output,” choose the trustworthy path.
