"""Streamlit entry point for AskDOSM."""

from __future__ import annotations

import streamlit as st

from askdosm.agent import AskDOSMService
from askdosm.models import OutputKind
from askdosm.visualization import build_figure


st.set_page_config(page_title="AskDOSM", page_icon="📊", layout="wide")
st.title("AskDOSM")
st.caption("Ask questions about Malaysian public statistics · Tanya soalan tentang statistik Malaysia")

EXAMPLES = [
    "What is Malaysia's latest population?",
    "Compare Johor and Selangor population in 2025.",
    "Show unemployment trends in Johor since 2020.",
    "Negeri mana mempunyai penduduk paling ramai pada tahun 2025?",
]


@st.cache_resource
def service() -> AskDOSMService:
    return AskDOSMService()


def render_payload(payload) -> None:
    if payload.error:
        st.warning(payload.answer)
    else:
        st.markdown(payload.answer)
    figure = build_figure(payload.table_rows, payload.visualization)
    if figure is not None:
        st.plotly_chart(figure, width="stretch")
    if payload.table_rows and payload.visualization.kind in {OutputKind.TABLE, OutputKind.NONE}:
        st.dataframe(payload.table_rows, width="stretch", hide_index=True)
    if payload.source:
        st.caption(
            f"Source: [{payload.source.title}]({payload.source.url}) · "
            f"{payload.source.agency} · Period: {payload.source.period or 'not applicable'} · "
            f"Unit: {payload.source.unit}"
        )
    with st.expander("How this answer was derived"):
        trace = payload.trace
        st.write("Intent", trace.intent.model_dump(mode="json") if trace.intent else None)
        st.write("Dataset selection", trace.selection_reason)
        st.write("Filters and operation", trace.query_plan.model_dump(mode="json") if trace.query_plan else None)
        st.write("Calculation", trace.calculation or "Direct retrieval")
        st.write("Rows used", trace.rows_used)
        st.write("Validation", trace.validation.model_dump(mode="json") if trace.validation else None)
        st.write("Retries", trace.retry_count)
        if payload.source:
            st.write("Data cache", payload.source.cache_freshness)
    if st.session_state.get("developer_mode") and payload.trace.query_plan:
        st.code(payload.trace.query_plan.model_dump_json(indent=2), language="json")


with st.sidebar:
    st.subheader("Example questions")
    for example in EXAMPLES:
        st.markdown(f"- {example}")
    st.toggle("Developer query-plan view", key="developer_mode")
    st.info("This MVP supports five curated DOSM datasets and processes each question independently.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            render_payload(message["payload"])
        else:
            st.markdown(message["content"])

if prompt := st.chat_input("Ask a question in English or Bahasa Melayu"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Finding and validating official data…"):
                payload = service().ask(prompt)
            render_payload(payload)
            st.session_state.messages.append({"role": "assistant", "payload": payload})
        except Exception as exc:
            st.error(f"AskDOSM could not complete the request: {exc}")

