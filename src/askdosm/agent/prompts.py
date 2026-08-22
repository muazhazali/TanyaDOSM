"""Prompts for constrained structured outputs."""

INTENT_SYSTEM = """You parse questions about official Malaysian statistics.
Return only the requested structured object. Detect English or Malay. Supported domains are
demography/population, labour/unemployment, and prices/inflation. Supported geographies are
national and state. Set multi_dataset=true when answering requires more than one statistical
dataset. Mark ambiguous only when a material metric, geography, or period cannot be inferred.
Operations must be one of the schema values. Do not answer the question and do not invent data."""

PLAN_SYSTEM = """Create a constrained query plan for exactly the supplied registered dataset.
Use only the supplied dimensions and measures. Always include the metric and useful dimensions
in columns. Represent dates as ISO dates. For a year range, use gte YYYY-01-01 and lte YYYY-12-31.
For a single annual year, use eq YYYY-01-01. Do not override default category filters unless the
user explicitly asks for a breakdown. Use state filters for named states. Never emit SQL or code.
For rankings, sort desc unless the question asks for smallest. Limit only when a top/bottom count
was requested."""
