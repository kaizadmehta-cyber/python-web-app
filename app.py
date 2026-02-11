import os
import json
import requests
from flask import Flask, render_template, jsonify, request
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__, template_folder='templates')

# Configuration
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

JIRA_USER = os.getenv('JIRA_USERNAME')
JIRA_PASS = os.getenv('JIRA_API_TOKEN')
JIRA_URL = CONFIG['jira_url']

# Standard fields always fetched
STANDARD_FIELDS = [
    "summary", "reporter", "assignee", "status", "labels", 
    "created", "resolution", "resolutiondate", "issuetype", "project", "priority"
]

def get_jira_headers():
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    # headers["Authorization"] = f"Bearer {JIRA_PASS}" # Uncomment if using PAT
    return headers

def get_field_map_from_jira():
    """Auto-detects Field IDs from Jira"""
    print("--> Auto-detecting Field IDs from Jira...")
    try:
        url = f"{JIRA_URL}/rest/api/2/field"
        response = requests.get(url, auth=HTTPBasicAuth(JIRA_USER, JIRA_PASS), headers=get_jira_headers())
        response.raise_for_status()
        all_fields = response.json()
        
        name_to_id = {f['name']: f['id'] for f in all_fields}
        name_to_id_lower = {f['name'].lower(): f['id'] for f in all_fields}
        
        return name_to_id, name_to_id_lower
    except Exception as e:
        print(f"!!! Error fetching field map: {e}")
        return {}, {}

def resolve_jira_value(v):
    if v is None: return ""
    if isinstance(v, list): return ", ".join([resolve_jira_value(x) for x in v if x])
    if isinstance(v, dict):
        if 'child' in v:
            parent = v.get('value') or v.get('name') or ""
            child = resolve_jira_value(v.get('child'))
            return f"{parent} - {child}" if (parent and child) else (parent or child)
        return v.get('value') or v.get('name') or v.get('displayName') or v.get('key') or ""
    return str(v).strip()

def fetch_and_process_issues():
    issues = []
    start_at = 0
    total = 1
    page_size = 50
    
    # 1. Map Fields
    name_map, name_map_lower = get_field_map_from_jira()
    resolved_map = {}
    user_mapping = CONFIG['field_mapping']
    
    for key, value_in_config in user_mapping.items():
        if value_in_config.startswith("customfield_") or value_in_config in STANDARD_FIELDS:
             resolved_map[key] = value_in_config
        else:
            found_id = name_map.get(key) or name_map_lower.get(key.lower())
            if not found_id:
                found_id = name_map.get(value_in_config) or name_map_lower.get(value_in_config.lower())
            resolved_map[key] = found_id if found_id else ""
            if found_id:
                print(f"    Mapped '{key}' -> {found_id}")
            else:
                print(f"!!! WARNING: Could not find field ID for '{key}'")

    fields_to_fetch = list(STANDARD_FIELDS) + [v for v in resolved_map.values() if v]
    fields_param = ",".join(list(set(fields_to_fetch)))

    print(f"--> Fetching data using JQL: {CONFIG['jql']}")

    # 2. Fetch Issues
    while len(issues) < total:
        url = f"{JIRA_URL}/rest/api/2/search"
        params = {
            "jql": CONFIG['jql'],
            "startAt": start_at,
            "maxResults": page_size,
            "fields": fields_param
        }
        
        try:
            response = requests.get(url, params=params, auth=HTTPBasicAuth(JIRA_USER, JIRA_PASS), headers=get_jira_headers())
            response.raise_for_status()
            data = response.json()
            total = data.get('total', 0)
            fetched = data.get('issues', [])
            issues.extend(fetched)
            start_at += len(fetched)
            print(f"    Fetched {len(fetched)} issues... (Total: {len(issues)}/{total})")
            if not fetched: break
        except Exception as e:
            print(f"!!! Error: {e}")
            break

    # 3. Process
    rows = []
    for i in issues:
        f = i.get('fields', {})
        row = {
            "Key": i.get('key'),
            "Summary": f.get('summary', ''),
            "Status": f.get('status', {}).get('name', '') if f.get('status') else "",
            "Severity": resolve_jira_value(f.get(resolved_map.get("Severity"))),
            "Assignee": f.get('assignee', {}).get('displayName', 'Unassigned') if f.get('assignee') else "Unassigned",
            "Product / Module": resolve_jira_value(f.get(resolved_map.get("Product / Module"))),
            "Submodule": resolve_jira_value(f.get(resolved_map.get("Submodule"))),
            "Issue Category": resolve_jira_value(f.get(resolved_map.get("Issue Category"))),
            
            # --- NEW FIELD ---
            "Benzene": resolve_jira_value(f.get(resolved_map.get("Benzene"))),
            
            "Labels": ", ".join(f.get('labels', [])),
            "Environments": resolve_jira_value(f.get(resolved_map.get("Environments"))),
            "Created": f.get('created', ''),
            "Reporter": f.get('reporter', {}).get('displayName', '') if f.get('reporter') else "",
            "Product Pillar": resolve_jira_value(f.get(resolved_map.get("Product Pillar"))),
            "Resolution notes": resolve_jira_value(f.get(resolved_map.get("Resolution notes"))),
            "URL": f"{JIRA_URL}/browse/{i.get('key')}",
            "Resolution Date": f.get('resolutiondate', ''),
            "Resolution": f.get('resolution', {}).get('name', '') if f.get('resolution') else ""
        }
        rows.append(row)
    
    return rows

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    try:
        processed_rows = fetch_and_process_issues()
        # FILTER OUT DISABLED PIVOTS
        active_pivots = [p for p in CONFIG['pivots'] if p.get('enabled', True) is not False]
        
        return jsonify({
            "ok": True,
            "config": CONFIG['dashboard_meta'],
            "pivots": active_pivots,
            "rows": processed_rows
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/diagnose')
def diagnose():
    key = request.args.get('key')
    if not key: return "Missing key", 400
    try:
        response = requests.get(f"{JIRA_URL}/rest/api/2/issue/{key}?expand=names", auth=HTTPBasicAuth(JIRA_USER, JIRA_PASS), headers=get_jira_headers())
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    print("Starting Dashboard on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)