import os
import json
import requests
import streamlit as st
import pandas as pd
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# --------------------------------------------------
# Environment & Config
# --------------------------------------------------
load_dotenv()

st.set_page_config(page_title="Defect Analysis Dashboard", layout="wide")

@st.cache_data(show_spinner=False)
def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

CONFIG = load_config()

JIRA_USER = os.getenv("JIRA_USERNAME")
JIRA_PASS = os.getenv("JIRA_API_TOKEN")
JIRA_URL = CONFIG["jira_url"]

STANDARD_FIELDS = [
    "summary", "reporter", "assignee", "status", "labels",
    "created", "resolution", "resolutiondate",
    "issuetype", "project", "priority"
]

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def get_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def resolve_jira_value(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(resolve_jira_value(x) for x in v if x)
    if isinstance(v, dict):
        return (
            v.get("value")
            or v.get("name")
            or v.get("displayName")
            or v.get("key")
            or ""
        )
    return str(v)

@st.cache_data(show_spinner=True)
def get_field_map():
    url = f"{JIRA_URL}/rest/api/2/field"
    r = requests.get(url, auth=HTTPBasicAuth(JIRA_USER, JIRA_PASS), headers=get_headers())
    r.raise_for_status()
    fields = r.json()
    return {f["name"].lower(): f["id"] for f in fields}

@st.cache_data(show_spinner=True)
def fetch_issues():
    name_map = get_field_map()
    resolved_map = {}

    for k, v in CONFIG["field_mapping"].items():
        if v.startswith("customfield_") or v in STANDARD_FIELDS:
            resolved_map[k] = v
        else:
            resolved_map[k] = name_map.get(v.lower(), "")

    fields = list(set(STANDARD_FIELDS + list(resolved_map.values())))
    fields_param = ",".join(fields)

    issues = []
    start = 0

    while True:
        r = requests.get(
            f"{JIRA_URL}/rest/api/2/search",
            params={
                "jql": CONFIG["jql"],
                "startAt": start,
                "maxResults": 50,
                "fields": fields_param,
            },
            auth=HTTPBasicAuth(JIRA_USER, JIRA_PASS),
            headers=get_headers(),
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        if len(batch) < 50:
            break
        start += 50

    rows = []
    for i in issues:
        f = i["fields"]
        rows.append({
            "Key": i["key"],
            "Summary": f.get("summary"),
            "Status": resolve_jira_value(f.get("status")),
            "Severity": resolve_jira_value(f.get(resolved_map.get("Severity"))),
            "Assignee": resolve_jira_value(f.get("assignee")) or "Unassigned",
            "Product / Module": resolve_jira_value(f.get(resolved_map.get("Product / Module"))),
            "Submodule": resolve_jira_value(f.get(resolved_map.get("Submodule"))),
            "Issue Category": resolve_jira_value(f.get(resolved_map.get("Issue Category"))),
            "Benzene": resolve_jira_value(f.get(resolved_map.get("Benzene"))),
            "Labels": ", ".join(f.get("labels", [])),
            "Created": f.get("created"),
            "Resolution": resolve_jira_value(f.get("resolution")),
            "URL": f"{JIRA_URL}/browse/{i['key']}",
        })

    return pd.DataFrame(rows)

# --------------------------------------------------
# UI
# --------------------------------------------------
st.title(CONFIG["dashboard_meta"]["title"])
st.caption(
    f"Project: {CONFIG['dashboard_meta']['project']} | "
    f"Manager: {CONFIG['dashboard_meta']['manager']} | "
    f"Lead: {CONFIG['dashboard_meta']['lead']}"
)

if st.button("🔄 Load Jira Data"):
    with st.spinner("Fetching defects from Jira..."):
        df = fetch_issues()
        st.success(f"Loaded {len(df)} defects")
        st.dataframe(df, use_container_width=True)

        st.download_button(
            "⬇️ Download CSV",
            df.to_csv(index=False),
            "jira_defects.csv",
            "text/csv"
        )
