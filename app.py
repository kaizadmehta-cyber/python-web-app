import json
import os
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------
# Load Data (reuse your existing logic)
# ---------------------------------------
@st.cache_data
def load_data():
    # 👉 Replace this with your Jira fetch logic
    df = pd.read_csv("sample.csv") if os.path.exists("sample.csv") else pd.DataFrame([
        {"Key": "DEF-1", "Summary": "Login fails", "Status": "Open", "Severity": "High", "Assignee": "John"},
        {"Key": "DEF-2", "Summary": "UI issue", "Status": "Closed", "Severity": "Low", "Assignee": "Unassigned"}
    ])

    return df

df = load_data()

payload = {
    "total": len(df),
    "open": len(df[df["Status"] == "Open"]),
    "closed": len(df[df["Status"] == "Closed"]),
    "unassigned": len(df[df["Assignee"] == "Unassigned"]),
    "byStatus": df["Status"].value_counts().to_dict(),
    "bySeverity": df["Severity"].value_counts().to_dict(),
    "rows": df.to_dict(orient="records")
}

# ---------------------------------------
# Serve HTML
# ---------------------------------------
st.set_page_config(layout="wide")

if "data" not in st.session_state:
    st.session_state["data"] = payload

# Fake API endpoint for HTML
st.markdown(
    f"""
    <script>
      window.fetch = (orig => (...args) => {{
        if (args[0].endsWith('/data')) {{
          return Promise.resolve(
            new Response(JSON.stringify({json.dumps(payload)}))
          );
        }}
        return orig(...args);
      }})(window.fetch);
    </script>
    """,
    unsafe_allow_html=True
)

with open("index.html", "r", encoding="utf-8") as f:
    html = f.read()

components.html(html, height=1200, scrolling=True)
