from __future__ import annotations

import os
import uuid

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")
TOKEN = os.getenv("API_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

st.set_page_config(page_title="Agentic Data Analyst", page_icon="📊", layout="wide")


def api(method: str, path: str, **kw):
    r = requests.request(method, f"{API}{path}", headers=HEADERS, timeout=300, **kw)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(detail)
    return r


ss = st.session_state
ss.setdefault("session_id", uuid.uuid4().hex)
ss.setdefault("messages", [])
ss.setdefault("pending", None)
ss.setdefault("report_bytes", {})


def render_response(resp: dict, key: str) -> None:
    st.markdown(resp["answer"])
    for w in resp.get("warnings", []):
        st.warning(w, icon="⚠️")
    if resp.get("kpis"):
        cols = st.columns(len(resp["kpis"]))
        for c, k in zip(cols, resp["kpis"]):
            v = k["value"]
            c.metric(k["label"], f"{v:,.2f}" if isinstance(v, float) else v, f"{k['delta_pct']:+.1f}%" if k.get("delta_pct") is not None else None)
    for i, ch in enumerate(resp.get("charts", [])):
        st.plotly_chart(go.Figure(ch["figure"]), use_container_width=True, key=f"{key}-c{i}")
    if resp.get("table"):
        with st.expander(f"Table ({len(resp['table'])} rows shown)", expanded=not resp.get("charts")):
            st.dataframe(pd.DataFrame(resp["table"]), use_container_width=True)
    if resp.get("insights"):
        st.markdown("**Key insights**\n" + "\n".join(f"- {x}" for x in resp["insights"]))
    if resp.get("sql"):
        with st.expander("SQL (validated, read-only)"):
            st.code(resp["sql"], language="sql")
    if resp.get("notes"):
        st.caption(" · ".join(resp["notes"]))
    if resp.get("run_id") and (resp.get("charts") or resp.get("kpis")):
        if st.button("➕ Add to dashboard", key=f"{key}-add"):
            try:
                api("POST", "/dashboard/from-run", json={"source_type": ss.source["type"], "source_id": ss.source["id"], "run_id": resp["run_id"]})
                st.success("Added to dashboard")
            except RuntimeError as e:
                st.error(str(e))
    for j, q in enumerate(resp.get("follow_ups", [])):
        if st.button(q, key=f"{key}-f{j}"):
            ss.pending = q
            st.rerun()


# ---------------- sidebar: sources ----------------
with st.sidebar:
    st.title("📊 Data sources")
    up = st.file_uploader("Upload CSV / Excel / JSON / Parquet", type=["csv", "tsv", "xlsx", "xls", "json", "parquet"])
    if up and st.button("Analyse file", type="primary"):
        with st.spinner("Uploading and profiling..."):
            try:
                d = api("POST", "/datasets", files={"file": (up.name, up.getvalue())}).json()
                ss.source = {"type": "dataset", "id": d["id"], "name": d["name"]}
                ss.messages = []
                st.success(f"Loaded {d['rows']:,} rows")
            except RuntimeError as e:
                st.error(str(e))

    with st.expander("Connect PostgreSQL"):
        with st.form("conn"):
            name = st.text_input("Name", "analytics")
            host = st.text_input("Host", "db")
            port = st.number_input("Port", value=5432)
            dbname = st.text_input("Database", "analytics")
            user = st.text_input("Read-only user", "bi_readonly")
            pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Connect"):
                try:
                    c = api("POST", "/connections", json={"name": name, "dialect": "postgres", "host": host, "port": int(port),
                                                          "database": dbname, "username": user, "password": pwd}).json()
                    ss.source = {"type": "connection", "id": c["id"], "name": c["name"]}
                    ss.messages = []
                    st.success("Connected")
                except RuntimeError as e:
                    st.error(str(e))

    st.divider()
    try:
        opts = {f"📄 {d['name']} (#{d['id']})": ("dataset", d["id"], d["name"]) for d in api("GET", "/datasets").json()}
        opts |= {f"🛢️ {c['name']} (#{c['id']})": ("connection", c["id"], c["name"]) for c in api("GET", "/connections").json()}
    except Exception:
        opts = {}
        st.error("API unreachable")
    if opts:
        labels = list(opts)
        cur = next((i for i, l in enumerate(labels) if ss.get("source") and opts[l][:2] == (ss.source["type"], ss.source["id"])), 0)
        pick = st.selectbox("Active source", labels, index=cur)
        t, i, n = opts[pick]
        if ss.get("source", {}).get("id") != i or ss.get("source", {}).get("type") != t:
            ss.source = {"type": t, "id": i, "name": n}
            ss.messages = []
    if st.button("New conversation"):
        ss.session_id, ss.messages = uuid.uuid4().hex, []

if not ss.get("source"):
    st.info("Upload a file or connect a database to get started.")
    st.stop()

src = ss.source
st.header(f"{src['name']}")
tab_chat, tab_profile, tab_dash, tab_reports = st.tabs(["💬 Ask", "🔍 Profile", "📈 Dashboard", "📥 Reports"])

# ---------------- chat ----------------
with tab_chat:
    for n, m in enumerate(ss.messages):
        with st.chat_message(m["role"]):
            render_response(m["resp"], f"m{n}") if m["role"] == "assistant" else st.markdown(m["text"])
    prompt = st.chat_input("e.g. Show the top 10 products · Why did sales decrease? · Create a chart for this · Add this chart to my dashboard")
    prompt = prompt or ss.pending
    ss.pending = None
    if prompt:
        ss.messages.append({"role": "user", "text": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    resp = api("POST", "/chat", json={"session_id": ss.session_id, "message": prompt,
                                                      "source_type": src["type"], "source_id": src["id"]}).json()
                except RuntimeError as e:
                    resp = {"answer": f"Error: {e}"}
            ss.messages.append({"role": "assistant", "resp": resp})
            render_response(resp, f"m{len(ss.messages) - 1}")

# ---------------- profile ----------------
with tab_profile:
    if src["type"] == "dataset":
        p = api("GET", f"/datasets/{src['id']}/profile").json()
        cols = st.columns(min(len(p["kpis"]), 5) or 1)
        for c, k in zip(cols, p["kpis"][:5]):
            v = k["value"]
            c.metric(k["label"], f"{v:,.2f}" if isinstance(v, float) else v, f"{k['delta_pct']:+.1f}%" if k.get("delta_pct") is not None else None)
        st.caption(f"{p['rows']:,} rows × {p['cols']} cols · {p['duplicate_rows']:,} duplicates ({p['duplicate_pct']}%)")
        st.subheader("Data-quality issues")
        st.dataframe(pd.DataFrame(p["quality"]) if p["quality"] else pd.DataFrame({"status": ["No issues detected"]}), use_container_width=True)
        st.subheader("Columns")
        st.dataframe(pd.DataFrame([{k: v for k, v in c.items() if k not in ("stats", "top_values")} | c["stats"] for c in p["columns"]]), use_container_width=True)
        for t in p["trends"]:
            fig = go.Figure(go.Scatter(x=[s["period"] for s in t["series"]], y=[s["value"] for s in t["series"]], mode="lines+markers"))
            fig.update_layout(title=f"{t['metric']} per {t['freq']} - trend {t['direction']}", template="plotly_white", height=300)
            st.plotly_chart(fig, use_container_width=True, key=f"trend-{t['metric']}")
        if p["correlations"]:
            st.subheader("Strong correlations")
            st.dataframe(pd.DataFrame(p["correlations"]), use_container_width=True)
        if p["outliers"]:
            st.subheader("Outliers (IQR)")
            st.dataframe(pd.DataFrame(p["outliers"]), use_container_width=True)
    else:
        schema = api("GET", f"/connections/{src['id']}/schema").json()
        for tname, t in schema["tables"].items():
            with st.expander(tname):
                st.dataframe(pd.DataFrame(t["columns"]), use_container_width=True)

# ---------------- dashboard ----------------
with tab_dash:
    items = api("GET", "/dashboard", params={"source_type": src["type"], "source_id": src["id"]}).json()
    if not items:
        st.info("Your dashboard is empty. Ask for a chart in the chat, then click “Add to dashboard”.")
    ncols = st.radio("Columns", [1, 2, 3], index=1, horizontal=True)
    grid = st.columns(ncols)
    for n, it in enumerate(items):
        with grid[n % ncols]:
            with st.container(border=True):
                st.markdown(f"**{it['title']}**")
                pl = it["payload"]
                if it["kind"] == "chart":
                    st.plotly_chart(go.Figure(pl["figure"]), use_container_width=True, key=f"d{it['id']}")
                elif it["kind"] == "kpi":
                    k = pl["kpi"]
                    st.metric(k["label"], f"{k['value']:,.2f}" if isinstance(k["value"], float) else k["value"])
                else:
                    st.dataframe(pd.DataFrame(pl["rows"]), use_container_width=True)
                if st.button("Remove", key=f"rm{it['id']}"):
                    api("DELETE", f"/dashboard/items/{it['id']}")
                    st.rerun()

# ---------------- reports ----------------
with tab_reports:
    st.write("Reports include the profile, insights from this source and everything pinned to the dashboard.")
    for fmt, label, mime in [("html", "HTML", "text/html"), ("pdf", "PDF", "application/pdf"),
                             ("xlsx", "Excel summary", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]:
        c1, c2 = st.columns([1, 3])
        if c1.button(f"Generate {label}", key=f"gen{fmt}"):
            try:
                ss.report_bytes[fmt] = api("GET", f"/reports/{fmt}", params={"source_type": src["type"], "source_id": src["id"]}).content
            except RuntimeError as e:
                st.error(str(e))
        if fmt in ss.report_bytes:
            c2.download_button(f"⬇️ Download {label}", ss.report_bytes[fmt], file_name=f"report.{fmt}", mime=mime, key=f"dl{fmt}")
