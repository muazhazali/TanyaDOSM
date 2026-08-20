# PRD — AskDOSM

## 1. Product Summary

**Product name:** AskDOSM  
**Working title alternatives:** DOSMChat, StatMY  
**Document type:** Product Requirements Document  
**Version:** 0.1  
**Status:** Draft / MVP Planning

AskDOSM is a conversational data assistant for Malaysia's OpenDOSM public statistics platform.

Users ask questions in natural language, such as:

- "What was Malaysia's population growth from 2020 to 2025?"
- "Which state has the highest population?"
- "Compare unemployment in Selangor and Johor."
- "Show inflation trends for the last five years."
- "Berapa populasi Pulau Pinang pada tahun 2025?"

The system identifies the relevant OpenDOSM dataset, retrieves structured data, performs the required calculation, validates the result, and returns an answer with source attribution and, when useful, a chart or table.

The application uses **LangGraph** for orchestration and state management, while **LangChain** may be used for LLM integration, tool definitions, prompts, structured outputs, and retrieval components.

---

# 2. Problem Statement

OpenDOSM provides valuable official Malaysian statistics, but users often need to:

1. Find the correct dataset.
2. Understand the dataset schema.
3. Identify the correct dimensions and filters.
4. Download or query the data.
5. Perform calculations manually.
6. Create charts or summaries.
7. Interpret the result.

This creates friction for users who know the question they want to answer but do not know which dataset or analytical steps are required.

AskDOSM aims to reduce that friction by converting natural-language questions into transparent, reproducible data queries and analyses.

---

# 3. Product Goal

Build a trustworthy conversational interface that allows users to query selected OpenDOSM datasets using natural language and receive data-grounded answers.

The product should demonstrate that an LLM can orchestrate structured-data analysis rather than answer statistical questions from model memory.

---

# 4. MVP Objective

The MVP should support approximately **10–15 curated OpenDOSM datasets** across several high-value domains.

Recommended initial domains:

### Demography
- Malaysia population
- State population
- District population

### Economy
- GDP
- Consumer Price Index / inflation
- Unemployment
- Labour-force indicators

### Society
- Crime statistics

The MVP must be able to:

1. Understand a natural-language question.
2. Identify a relevant supported dataset.
3. Inspect or retrieve dataset metadata.
4. Convert the question into structured filters and analytical operations.
5. Query the dataset.
6. Perform calculations.
7. Validate the result.
8. Return a concise answer.
9. Display the source dataset.
10. Produce a chart or table when appropriate.

---

# 5. Non-Goals for MVP

The following are explicitly out of scope for the first release:

- Supporting every OpenDOSM dataset.
- Fully autonomous unrestricted Python execution.
- Complex forecasting.
- Causal inference.
- Automatic machine-learning model training.
- User accounts.
- Persistent long-term conversation memory.
- Multi-user collaboration.
- Production-grade enterprise authentication.
- Automatic data ingestion of the entire OpenDOSM catalogue.
- Support for arbitrary third-party data sources.
- Multi-agent architecture unless clearly necessary.
- Advanced GIS analysis.

These may be considered after the core workflow is reliable.

---

# 6. Target Users

## 6.1 General Public

Users who want understandable answers about Malaysian statistics without manually navigating datasets.

Example:

> "Which state has the highest unemployment rate?"

## 6.2 Students and Researchers

Users who need quick exploratory analysis before performing deeper statistical work.

Example:

> "Compare population growth in Johor, Selangor, and Penang from 2015 onward."

## 6.3 Journalists and Analysts

Users who need official statistics with traceable sources.

Example:

> "How has inflation changed over the last five years?"

## 6.4 Developers and Data Practitioners

Users interested in inspecting the underlying dataset, query, filters, and transformations used to produce an answer.

---

# 7. Core Product Principles

## 7.1 Data-Grounded Answers

The LLM must not answer factual statistical questions solely from model memory when the requested data is available through OpenDOSM.

## 7.2 Traceability

Each answer should expose:

- Dataset name
- Source
- Relevant date or period
- Applied filters
- Calculation or aggregation where useful

## 7.3 Reproducibility

The system should internally represent the analytical request in a structured format that can be reproduced.

## 7.4 Conservative Failure

If the system cannot confidently identify or query the required dataset, it should state that the result could not be determined instead of inventing an answer.

## 7.5 Minimal Agent Complexity

Use LangGraph only where branching, validation, retries, state, or tool orchestration provide clear value.

---

# 8. Example User Experience

## Example 1 — Direct Lookup

**User**

> What was Selangor's population in 2025?

**System process**

1. Detect domain: population.
2. Select state-population dataset.
3. Resolve entity: Selangor.
4. Resolve year: 2025.
5. Query matching row.
6. Validate units and date.
7. Return result.

**Response structure**

> Selangor's population in 2025 was approximately X million.
>
> Source: Department of Statistics Malaysia  
> Dataset: [dataset name]  
> Period: 2025

---

## Example 2 — Comparison

**User**

> Compare unemployment between Johor and Selangor from 2020 to 2025.

**System process**

1. Identify unemployment dataset.
2. Filter states: Johor, Selangor.
3. Filter date range: 2020–2025.
4. Aggregate to yearly values if required.
5. Calculate differences.
6. Generate line chart.
7. Summarize the trend.

---

## Example 3 — Ranking

**User**

> Which state had the largest population increase between 2020 and 2025?

**System process**

1. Load state population dataset.
2. Retrieve 2020 and 2025 values.
3. Calculate:

```text
absolute_change = population_2025 - population_2020
percentage_change = absolute_change / population_2020 * 100
```

4. Rank states.
5. Validate missing values.
6. Return top result and optional top-five table.

---

## Example 4 — Malay Query

**User**

> Negeri mana mempunyai jumlah penduduk tertinggi pada tahun 2025?

The system should understand the request and execute the same structured workflow as the equivalent English query.

---

# 9. User Stories

## Dataset Discovery

- As a user, I want to ask a question without knowing the dataset name.
- As a user, I want the system to identify the most relevant supported dataset.
- As a user, I want to know which dataset was used.

## Querying

- As a user, I want to filter data by state, district, date, category, or other supported dimensions.
- As a user, I want to compare multiple regions or periods.

## Analysis

- As a user, I want the system to calculate totals, averages, differences, growth rates, rankings, and percentages.
- As a user, I want the system to explain calculations in understandable language.

## Visualization

- As a user, I want a chart when the question involves a trend or comparison.
- As a user, I want a table when several values are being compared.

## Trust

- As a user, I want answers to cite the underlying dataset.
- As a user, I want the system to state when information cannot be reliably determined.
- As a user, I want to inspect the data filters used to answer my question.

---

# 10. Functional Requirements

## FR-01 Natural-Language Input

The system must accept free-form questions in English.

The MVP should also support common Malay statistical queries.

---

## FR-02 Intent Extraction

The system must identify:

- metric
- geography
- time period
- comparison entities
- requested operation
- desired visualization where explicitly requested

Example structured representation:

```json
{
  "domain": "population",
  "metric": "population",
  "geography_level": "state",
  "entities": ["Selangor", "Johor"],
  "start_year": 2020,
  "end_year": 2025,
  "operation": "compare"
}
```

---

## FR-03 Dataset Discovery

The system must map the user question to one or more supported datasets.

For MVP, dataset discovery may use a curated catalogue containing:

- dataset ID
- title
- description
- dimensions
- measures
- date range
- source URL
- tags
- known aliases

Semantic retrieval may be used to rank candidate datasets.

---

## FR-04 Dataset Metadata Inspection

The agent must be able to retrieve metadata including:

- dataset description
- available columns
- data types
- units
- date coverage
- geographic coverage
- update frequency where available

---

## FR-05 Structured Query Planning

The system must create a structured query plan before retrieving or analysing data.

Example:

```json
{
  "dataset_id": "population_state",
  "filters": {
    "state": ["Selangor", "Johor"],
    "year": {
      "gte": 2020,
      "lte": 2025
    }
  },
  "group_by": ["state", "year"],
  "metric": "population",
  "operation": "compare"
}
```

---

## FR-06 Data Retrieval

The system must retrieve data from a supported OpenDOSM source.

Preferred approaches:

1. OpenDOSM / data.gov.my API where appropriate.
2. Parquet files.
3. CSV files as fallback.

---

## FR-07 Analytical Operations

The MVP should support:

- Filter
- Sort
- Sum
- Count
- Mean
- Median
- Minimum
- Maximum
- Difference
- Percentage difference
- Year-over-year change
- Percentage growth
- CAGR
- Ranking
- Grouped aggregation

Optional later:

- Correlation
- Rolling averages
- Index normalization

---

## FR-08 Validation

Before generating the final response, the system must validate:

- dataset returned rows
- required columns exist
- requested entities exist
- requested dates exist
- result is not empty
- numeric values are parseable
- units are known where relevant

The validator may send the workflow back to dataset discovery or query planning if the result is invalid.

---

## FR-09 Natural-Language Response

Answers should contain:

1. Direct answer
2. Important supporting values
3. Brief interpretation
4. Dataset source

The answer should distinguish:

- retrieved fact
- calculated result
- interpretation

---

## FR-10 Chart Generation

The system should generate charts when appropriate.

Initial supported chart types:

- Line chart
- Bar chart
- Horizontal ranking bar chart

The system should avoid generating charts for simple single-value queries.

---

## FR-11 Table Generation

The system should render tables for:

- rankings
- comparisons
- multi-period data
- multi-region results

---

## FR-12 Error Handling

If a question cannot be answered using supported data, the system should explain why.

Example:

> I could not find a supported OpenDOSM dataset containing district-level household income for the requested period.

The system must not fabricate values.

---

# 11. LangGraph Workflow

## 11.1 High-Level Graph

```text
START
  |
  v
Understand Question
  |
  v
Search Dataset Catalogue
  |
  v
Select Dataset
  |
  v
Inspect Metadata
  |
  v
Build Query Plan
  |
  v
Fetch Data
  |
  v
Run Analysis
  |
  v
Validate Result
  |
  +---------------------------+
  |                           |
 valid                      invalid
  |                           |
  v                           v
Generate Answer        Replan / Retry
  |                           |
  v                           |
Generate Visualization <------+
  |
  v
END
```

---

# 12. Recommended Graph Nodes

## Node 1 — `parse_question`

Responsibilities:

- detect language
- extract intent
- identify metrics
- extract geographic entities
- extract dates
- identify requested operation

Output:

```python
QuestionIntent
```

---

## Node 2 — `search_catalogue`

Responsibilities:

- retrieve candidate datasets
- rank candidates by relevance

Output:

```python
list[DatasetCandidate]
```

---

## Node 3 — `select_dataset`

Responsibilities:

- choose the best candidate
- determine whether one or multiple datasets are required

Output:

```python
selected_dataset_ids
```

---

## Node 4 — `inspect_schema`

Responsibilities:

- retrieve columns
- inspect data types
- inspect categories
- verify geography and date availability

---

## Node 5 — `build_query_plan`

Responsibilities:

Convert intent into an executable structured plan.

The LLM should not directly generate unrestricted Python code.

---

## Node 6 — `execute_query`

Responsibilities:

- retrieve data
- apply deterministic filters
- perform safe transformations

Recommended engine:

- DuckDB for Parquet
- Pandas for smaller in-memory results

---

## Node 7 — `analyze_result`

Responsibilities:

Perform requested calculations using deterministic Python or SQL.

The LLM should decide **what analysis to run**, while Python or SQL should perform the numeric calculation.

---

## Node 8 — `validate_result`

Responsibilities:

Check:

- empty result
- invalid entities
- invalid periods
- missing values
- aggregation errors
- unexpected duplicate rows
- unit consistency

Possible transitions:

```text
valid -> answer
invalid_query -> build_query_plan
wrong_dataset -> search_catalogue
unsupported -> graceful_failure
```

---

## Node 9 — `generate_response`

Responsibilities:

- explain result
- provide source
- describe important calculations
- avoid unsupported claims

---

## Node 10 — `generate_visualization`

Responsibilities:

Determine whether visualization is useful.

Possible outputs:

```text
none
line
bar
ranking_bar
table
```

---

# 13. Agent State

Example:

```python
from typing import TypedDict


class AgentState(TypedDict):
    question: str
    language: str

    intent: dict | None

    dataset_candidates: list
    selected_datasets: list

    metadata: dict

    query_plan: dict | None
    query_result: list | None

    analysis_result: dict | None

    validation_status: str | None
    validation_errors: list

    visualization_spec: dict | None

    final_answer: str | None

    retry_count: int
```

---

# 14. Tool Design

## `search_catalogue`

```python
search_catalogue(query: str) -> list[DatasetCandidate]
```

Purpose:

Find OpenDOSM datasets relevant to the question.

---

## `get_dataset_metadata`

```python
get_dataset_metadata(dataset_id: str) -> DatasetMetadata
```

Returns:

- title
- description
- dimensions
- measures
- date range
- units
- URLs

---

## `query_dataset`

```python
query_dataset(
    dataset_id: str,
    filters: dict,
    columns: list[str] | None = None
) -> DataFrame
```

---

## `aggregate_dataset`

```python
aggregate_dataset(
    dataframe,
    group_by: list[str],
    metric: str,
    operation: str
)
```

---

## `calculate_growth`

```python
calculate_growth(
    start_value: float,
    end_value: float
) -> dict
```

---

## `rank_values`

```python
rank_values(
    dataframe,
    metric: str,
    ascending: bool = False
)
```

---

# 15. Dataset Registry

For MVP, maintain a curated local metadata registry.

Example:

```json
{
  "dataset_id": "population_state",
  "title": "Population by State",
  "description": "Population estimates by Malaysian state and year.",
  "domain": "demography",
  "dimensions": [
    "state",
    "date"
  ],
  "measures": [
    "population"
  ],
  "aliases": [
    "state population",
    "population by state",
    "penduduk negeri",
    "populasi negeri"
  ],
  "source_type": "parquet"
}
```

This allows reliable dataset selection before attempting fully dynamic catalogue discovery.

---

# 16. Retrieval Strategy

Do not embed every statistical row into a vector database.

Use embeddings only for **dataset metadata discovery**.

Recommended flow:

```text
Question
   |
   v
Semantic search over dataset metadata
   |
   v
Dataset selected
   |
   v
Structured data query
   |
   v
DuckDB / Pandas calculation
```

Potential vector stores:

- FAISS
- Chroma
- Qdrant
- pgvector

For MVP, FAISS or Chroma is sufficient.

---

# 17. Proposed Architecture

```text
+-------------------------+
|       Streamlit UI      |
|     Chat + Charts       |
+------------+------------+
             |
             v
+-------------------------+
|        LangGraph        |
|  Workflow Orchestration |
+------------+------------+
             |
       +-----+-------------------------+
       |               |              |
       v               v              v
+-------------+ +-------------+ +-------------+
| Catalogue   | | Data Query  | | Analysis    |
| Retrieval   | | Tool        | | Tools       |
+------+------+ +------+------+ +------+------+
       |               |               |
       v               v               v
 Vector Store     OpenDOSM API     DuckDB/Pandas
 Metadata         CSV / Parquet
       |
       +-------------------------------+
                       |
                       v
                 +-----------+
                 |    LLM    |
                 +-----------+
```

---

# 18. Recommended Technology Stack

## Application

- Python 3.11+
- Streamlit

## Agent Framework

- LangGraph
- LangChain

## LLM

Any tool-capable LLM provider.

The application should abstract the LLM interface so providers can be swapped.

## Data

- DuckDB
- Pandas
- PyArrow

## Retrieval

MVP:

- Chroma or FAISS

Optional later:

- Qdrant
- PostgreSQL + pgvector

## Visualization

- Plotly

## Validation

- Pydantic

## Testing

- pytest

## Observability

Optional:

- LangSmith

## Deployment

- Docker

---

# 19. UI Requirements

## Main Chat Interface

The page should contain:

### Header

```text
AskDOSM
Ask questions about Malaysian public statistics
```

### Example prompts

- What is Malaysia's latest population?
- Compare Johor and Selangor population.
- Show unemployment trends since 2020.
- Negeri mana mempunyai penduduk paling ramai?

### Chat message

Each answer should support:

- answer
- chart
- table
- dataset reference
- expandable analysis details

---

# 20. Explainability Panel

An optional expandable section should show:

```text
Dataset:
Population by State

Filters:
State: Selangor
Year: 2025

Operation:
Retrieve population value

Rows used:
1
```

For calculated queries:

```text
Calculation:
2025 population - 2020 population

Data points used:
2020: X
2025: Y
```

This feature is important for portfolio demonstration because it shows that the answer is based on deterministic data operations.

---

# 21. Safety and Reliability Requirements

## SR-01

The LLM must not invent statistical values.

## SR-02

Numeric calculations should be executed with Python, DuckDB, or another deterministic computation engine.

## SR-03

Dataset IDs must come from the supported dataset registry or catalogue search results.

## SR-04

The application must limit graph retries.

Recommended:

```text
maximum retries = 2
```

## SR-05

The system must clearly indicate unavailable or unsupported requests.

## SR-06

The system should treat retrieved dataset contents as data, not executable instructions.

---

# 22. Performance Requirements

For common MVP queries:

- Target response time: under 10 seconds where practical.
- Dataset metadata should be cached.
- Frequently accessed Parquet datasets may be cached locally.
- Results of identical deterministic queries may be cached.

Performance optimization is secondary to correctness during MVP development.

---

# 23. Evaluation Strategy

The chatbot should not be evaluated only by whether the final answer "sounds correct."

Create a fixed test set.

Recommended initial evaluation set:

```text
50 questions
```

Categories:

| Category | Questions |
|---|---:|
| Direct lookup | 10 |
| Filtering | 10 |
| Comparison | 10 |
| Trend | 8 |
| Ranking | 5 |
| Calculation | 5 |
| Unsupported / ambiguous | 2 |

---

# 24. Evaluation Metrics

## Dataset Selection Accuracy

```text
correct dataset selected / total questions
```

Target:

```text
>= 90%
```

for supported MVP questions.

---

## Query Plan Accuracy

Evaluate whether the agent correctly identifies:

- metric
- geography
- dates
- grouping
- aggregation

Target:

```text
>= 90%
```

---

## Numeric Answer Accuracy

For deterministic benchmark questions:

```text
correct numeric answers / answerable questions
```

Target:

```text
100%
```

Any incorrect numeric answer should be treated as a significant failure.

---

## Citation Accuracy

The cited dataset must be the dataset actually used for the analysis.

Target:

```text
100%
```

---

## Hallucination Rate

Count responses containing unsupported statistical claims.

Target:

```text
0%
```

for benchmark questions.

---

# 25. MVP Acceptance Criteria

The MVP is complete when:

- [ ] User can submit a natural-language question.
- [ ] At least 10 OpenDOSM datasets are supported.
- [ ] Dataset discovery works without requiring the dataset name.
- [ ] The system can query by year.
- [ ] The system can query by state.
- [ ] The system can compare multiple states.
- [ ] The system can calculate differences.
- [ ] The system can calculate percentage growth.
- [ ] The system can rank entities.
- [ ] The system can generate a line chart.
- [ ] The system can generate a bar chart.
- [ ] Every statistical answer displays its dataset source.
- [ ] Numeric calculations are performed outside the LLM.
- [ ] Invalid queries fail gracefully.
- [ ] LangGraph validation/retry routing is implemented.
- [ ] Automated evaluation contains at least 50 benchmark questions.
- [ ] README documents architecture and example queries.
- [ ] Application can run locally using documented setup instructions.

---

# 26. Development Phases

## Phase 1 — Dataset Exploration

Objectives:

- select 10–15 datasets
- inspect schemas
- document dimensions and measures
- identify API / CSV / Parquet access

Deliverable:

```text
datasets.json
```

---

## Phase 2 — Deterministic Data Layer

Build functions for:

- loading datasets
- filtering
- grouping
- aggregating
- ranking
- growth calculation

Do this before adding an LLM.

Deliverable:

```text
src/data/
```

---

## Phase 3 — Dataset Registry

Create dataset metadata registry.

Deliverable:

```text
data/catalogue.json
```

---

## Phase 4 — LangChain Tools

Expose deterministic functions as tools.

Deliverables:

```text
search_catalogue
get_dataset_metadata
query_dataset
analyze_dataset
```

---

## Phase 5 — LangGraph MVP

Implement:

```text
parse
  ->
discover
  ->
plan
  ->
execute
  ->
validate
  ->
answer
```

---

## Phase 6 — Streamlit Interface

Implement:

- chat
- tables
- charts
- data source display
- expandable execution details

---

## Phase 7 — Evaluation

Create benchmark questions and ground-truth answers.

Measure:

- dataset selection
- query-plan correctness
- numeric accuracy
- source accuracy

---

## Phase 8 — Deployment

Containerize the application.

Optional hosting targets:

- VPS
- cloud VM
- container hosting platform

---

# 27. V2 Features

After the MVP is stable:

## Dynamic Catalogue Discovery

Allow the agent to discover datasets outside the curated registry.

---

## Multi-Dataset Queries

Example:

> Compare unemployment and population growth across Malaysian states.

Workflow:

```text
question
   |
   +--> unemployment dataset
   |
   +--> population dataset
   |
   v
normalize dimensions
   |
   v
join datasets
   |
   v
analysis
```

---

## More Advanced Statistical Analysis

Possible tools:

- correlation
- regression
- rolling averages
- moving growth rates
- standardized indexes

The system must clearly distinguish descriptive relationships from causal claims.

---

## Follow-Up Conversation

Example:

```text
User:
Show population growth by state.

Assistant:
[result]

User:
Only show the top five.

Assistant:
[uses previous query context]
```

LangGraph state can retain the selected dataset, filters, and previous result.

---

## Data Download

Allow the user to download the filtered dataset underlying the answer.

Formats:

- CSV
- JSON

---

## Query Transparency

Advanced mode may show:

- generated DuckDB SQL
- API request
- selected columns
- transformation pipeline

---

## Data Freshness

Display:

```text
Dataset last updated:
YYYY-MM-DD
```

where available.

---

# 28. Potential V3 Features

- Full OpenDOSM catalogue support
- Multi-dataset planning
- Scheduled statistical monitoring
- Saved conversations
- Shareable analyses
- REST API
- Geographic maps
- Statistical anomaly detection
- Report generation
- Natural-language dashboard creation
- Local LLM support
- External Malaysian government datasets

---

# 29. Suggested Repository Structure

```text
askdosm/
|
+-- app.py
+-- README.md
+-- prd.md
+-- pyproject.toml
+-- Dockerfile
+-- .env.example
|
+-- data/
|   +-- catalogue.json
|
+-- src/
|   +-- __init__.py
|   |
|   +-- agent/
|   |   +-- graph.py
|   |   +-- state.py
|   |   +-- nodes.py
|   |   +-- routing.py
|   |
|   +-- catalogue/
|   |   +-- search.py
|   |   +-- metadata.py
|   |
|   +-- data/
|   |   +-- loader.py
|   |   +-- query.py
|   |   +-- cache.py
|   |
|   +-- analysis/
|   |   +-- aggregation.py
|   |   +-- growth.py
|   |   +-- ranking.py
|   |
|   +-- tools/
|   |   +-- catalogue_tools.py
|   |   +-- data_tools.py
|   |   +-- analysis_tools.py
|   |
|   +-- visualization/
|   |   +-- charts.py
|   |
|   +-- models/
|       +-- schemas.py
|
+-- tests/
|   +-- test_catalogue.py
|   +-- test_queries.py
|   +-- test_analysis.py
|   +-- test_agent.py
|
+-- evals/
    +-- questions.json
    +-- evaluate.py
```

---

# 30. Example Structured Schemas

## Intent

```python
from pydantic import BaseModel


class QuestionIntent(BaseModel):
    domain: str | None
    metric: str | None
    geography_level: str | None
    entities: list[str]
    start_year: int | None
    end_year: int | None
    operation: str
```

---

## Query Plan

```python
class QueryPlan(BaseModel):
    dataset_id: str
    filters: dict
    columns: list[str]
    group_by: list[str]
    metric: str
    operation: str
```

---

## Validation Result

```python
class ValidationResult(BaseModel):
    valid: bool
    reason: str | None
    retry_action: str | None
```

---

# 31. Example Graph Routing

```python
def route_validation(state):
    if state["validation_status"] == "valid":
        return "generate_response"

    if state["retry_count"] >= 2:
        return "graceful_failure"

    if "dataset" in state["validation_errors"]:
        return "search_catalogue"

    return "build_query_plan"
```

This demonstrates a genuine use of LangGraph rather than wrapping a single LLM call inside a graph.

---

# 32. Example Benchmark Questions

## Direct Retrieval

1. What is Malaysia's population in 2025?
2. What is Selangor's population in 2025?
3. What was the unemployment rate in Malaysia in 2024?

## Comparison

4. Compare Johor and Selangor population in 2025.
5. Which has a larger population, Sabah or Sarawak?
6. Compare unemployment in Penang and Johor from 2020 to 2025.

## Trend

7. Show Malaysia's population from 2010 to 2025.
8. How has inflation changed since 2020?
9. Plot unemployment over the last five years.

## Ranking

10. Rank Malaysian states by population.
11. Which five states have the largest population?
12. Which state experienced the largest population increase between 2020 and 2025?

## Derived Calculation

13. What percentage did Selangor's population grow between 2020 and 2025?
14. What is the population difference between Johor and Penang?
15. Calculate Malaysia's average unemployment rate between 2020 and 2025.

## Malay

16. Berapa jumlah penduduk Malaysia pada tahun 2025?
17. Negeri mana mempunyai populasi tertinggi?
18. Bandingkan jumlah penduduk Johor dan Selangor.

---

# 33. Key Technical Decisions

## Decision 1

**Do not use vector search for statistical rows.**

Reason:

Structured data should be queried using structured operations.

---

## Decision 2

**Use vector search only for dataset discovery.**

Reason:

The user's wording may differ from official dataset names.

---

## Decision 3

**Use deterministic computation for numerical analysis.**

Reason:

LLMs should not be trusted to perform critical arithmetic.

---

## Decision 4

**Begin with a curated dataset list.**

Reason:

It makes evaluation and reliability manageable.

---

## Decision 5

**Use LangGraph for orchestration rather than making every step an autonomous agent.**

Reason:

A predictable graph is easier to test, explain, and debug.

---

# 34. Portfolio Demonstration Goals

The finished project should clearly demonstrate:

- LangGraph state management
- conditional routing
- tool calling
- structured LLM outputs
- semantic dataset discovery
- API / Parquet integration
- DuckDB or Pandas analytics
- deterministic numerical computation
- chart generation
- validation loops
- bilingual natural-language interaction
- automated LLM application evaluation
- Docker deployment

The project should not be positioned simply as:

> Chatbot for OpenDOSM.

A stronger description is:

> A stateful natural-language analytics agent for Malaysian public statistics that discovers relevant OpenDOSM datasets, builds structured query plans, executes deterministic data analysis, validates results, and returns source-grounded answers and visualizations.

---

# 35. Definition of Done

AskDOSM MVP is considered complete when a new user can:

1. Open the application.
2. Ask a statistical question without knowing a dataset name.
3. Receive a correct answer based on an OpenDOSM dataset.
4. See the relevant source.
5. Ask for a comparison or trend.
6. Receive an accurate chart or table.
7. Ask the same type of question in Malay.
8. Inspect how the result was derived.
9. Receive a safe failure message for unsupported questions.
10. Reproduce the project locally using the README.

