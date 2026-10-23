import base64
import json
import math
import os
import time

import pandas as pd
import requests
import streamlit as st


# =========================================================
# 1. CONFIGURATION & STYLING
# =========================================================
def get_browser_host():
    try:
        return st.context.headers.get("Host", "localhost").split(":")[0]
    except Exception:
        return "localhost"


HOST_NAME = get_browser_host()

# Sanitize trailing slashes to prevent route duplication
SERVER_URL = os.getenv("UPLOAD_SERVER_URL", f"http://{HOST_NAME}/dicomserver").rstrip("/")
INTERNAL_SERVER_URL = os.getenv("UPLOAD_SERVER_URL_INTERNAL", SERVER_URL).rstrip("/")
VIEWER_URL = os.getenv("VIEWER_URL", f"http://{HOST_NAME}/dicomviewer").rstrip("/")
VIABILITY_FILE = os.getenv("QC_FILE", "/qc_data/study_qc.json")


def hide_header_and_toolbar():
    st.markdown(
        """
        <style>
        [data-testid="stHeader"] { display: none !important; height: 0px !important; }
        [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stAppViewContainer"] { padding-top: 0rem !important; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        </style>
        """,
        unsafe_allow_html=True
    )


def maximize_viewport():
    st.markdown(
        """
        <style>
        [data-testid="stHeader"], .stAppHeader { display: none !important; height: 0px !important; }
        [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stMainBlockContainer"], .block-container { padding-top: 0rem !important; margin-top: 0rem !important; }
        [data-testid="stAppViewContainer"], section.stMain { padding-top: 0rem !important; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        </style>
        """,
        unsafe_allow_html=True
    )


st.set_page_config(page_title="IGHD DICOM Study Upload Client", layout="wide")
hide_header_and_toolbar()
maximize_viewport()

st.title("📡 IGHD DICOM Study Upload Client")


def load_qc_summary():
    """Reads QC JSON file directly from persistent storage."""
    if not os.path.exists(VIABILITY_FILE):
        return {}
    try:
        with open(VIABILITY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    summary = {}
    for record in data.values():
        pid = record.get("details", {}).get("case_no", "")
        vid = record.get("details", {}).get("date", "").replace("-", "")
        if not pid:
            continue
        s = summary.setdefault(pid + vid, {"v": 0, "g": 0, "a": 0})
        if "Viability" in record: s["v"] += 1
        if "Growth" in record: s["g"] += 1
        if "Anomaly" in record: s["a"] += 1
    return summary


@st.cache_data(ttl=5)
def check_server_health():
    for target in [INTERNAL_SERVER_URL, SERVER_URL]:
        try:
            r = requests.get(f"{target}/health", timeout=(5, 10))
            if r.ok:
                return r.json()
        except requests.exceptions.RequestException:
            continue
    return None


@st.cache_data(ttl=15)
def fetch_studies():
    st.session_state["fetch_debug_info"] = []

    targets = list(dict.fromkeys([INTERNAL_SERVER_URL, SERVER_URL]))

    for target in targets:
        url = f"{target}/studies"
        try:
            r = requests.get(url, timeout=(5, 60))
            if r.ok:
                data = r.json()
                if isinstance(data, dict):
                    return data.get("studies", data.get("data", []))
                elif isinstance(data, list):
                    return data
            else:
                st.session_state["fetch_debug_info"].append(
                    f"❌ {url} returned HTTP {r.status_code}: {r.text[:150]}"
                )
        except requests.exceptions.Timeout:
            st.session_state["fetch_debug_info"].append(
                f"⌛ {url} timed out (>60s). Fast API is still scanning raw DICOM files."
            )
        except requests.exceptions.RequestException as e:
            st.session_state["fetch_debug_info"].append(f"⚠️ Failed to reach {url}: {e}")
            continue

    return []


def delete_study_on_server(patient_id, study_uid):
    """Sends a DELETE request to backend to completely remove unverified study."""
    targets = list(dict.fromkeys([INTERNAL_SERVER_URL, SERVER_URL]))
    for target in targets:
        try:
            url = f"{target}/studies/{patient_id}/{study_uid}"
            r = requests.delete(url, timeout=(5, 30))
            if r.ok:
                return True, f"Successfully deleted study {study_uid} for Patient {patient_id}."

            url_alt = f"{target}/studies?patient_id={patient_id}&study_uid={study_uid}"
            r_alt = requests.delete(url_alt, timeout=(5, 30))
            if r_alt.ok:
                return True, f"Successfully deleted study {study_uid} for Patient {patient_id}."

            return False, f"HTTP {r.status_code}: {r.text[:150]}"
        except requests.exceptions.RequestException:
            continue
    return False, "Failed to connect to backend server for deletion."


# =========================================================
# 2. UPLOAD HTML COMPONENT
# =========================================================
# Standard string (NO 'f' prefix) -> eliminates f-string curly-brace parsing errors
UPLOAD_COMPONENT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
<style>
  * { box-sizing: border-box; font-family: sans-serif; margin: 0; padding: 0; }
  body { background: transparent; padding: 12px; color: #eee; }
  #drop-zone {
    border: 2px dashed #555; border-radius: 10px; padding: 25px;
    text-align: center; color: #888; cursor: pointer; transition: 0.3s;
  }
  #drop-zone:hover { border-color: #ff4b4b; background: rgba(255, 75, 75, 0.05); }
  .btn { padding: 10px 20px; border-radius: 8px; border: none; font-weight: 600; cursor: pointer; margin-top: 10px; width: 100%; }
  .btn-primary { background: #ff4b4b; color: #fff; }
  .btn-primary:disabled { background: #444; color: #777; cursor: not-allowed; }

  #progress-wrap { display: none; margin-top: 15px; }
  #progress-bar-bg { background: #333; height: 12px; border-radius: 6px; overflow: hidden; }
  #progress-bar { height: 100%; background: #4bff4b; width: 0%; transition: 0.3s; }

  .error-text { color: #ff4b4b; font-weight: bold; font-size: 11px; }
  .warning-text { color: #ff9800; font-weight: bold; font-size: 11px; }

  .stats-row { display: flex; justify-content: space-between; font-size: 11px; margin-top: 8px; color: #aaa; }
  .processing-anim { color: #ff9800; font-weight: bold; animation: blink 1s infinite; }
  @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
</style>
</head>
<body>

<div id="drop-zone" onclick="document.getElementById('file-input').click()">
  📁 <strong>Select Participant Folder</strong>
  <p style="font-size: 11px; margin-top: 5px;">Structure required: <code>Participant / Study_Subfolder / *.dcm</code></p>
  <input type="file" id="file-input" webkitdirectory multiple onchange="onFiles(this.files)" style="display:none"/>
</div>

<div id="summary" style="font-size: 12px; margin: 10px 0;"></div>
<button class="btn btn-primary" id="up-btn" disabled onclick="startBundleAndUpload()">🚀 Start Fast Upload</button>

<div id="progress-wrap">
  <div id="progress-bar-bg"><div id="progress-bar"></div></div>
  <div class="stats-row">
    <span id="prog-label">Ready</span>
    <span id="prog-pct">0%</span>
  </div>
  <div class="stats-row" style="background: rgba(255,255,255,0.05); padding: 5px; border-radius: 4px;">
    <span>Status: <strong id="up-speed">Idle</strong></span>
    <span>Remaining: <strong id="time-rem">--</strong></span>
  </div>
</div>

<script>
const SERVER = "__SERVER_URL__".replace(/\/$/, "");
let selectedFiles = [];

function generateUUID() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

function onFiles(list) {
  const allFiles = Array.from(list);
  const summaryEl = document.getElementById('summary');
  const upBtn = document.getElementById('up-btn');

  if (allFiles.length === 0) {
    summaryEl.innerHTML = '<span class="error-text">❌ No files selected.</span>';
    upBtn.disabled = true;
    return;
  }

  let directFilesCount = 0;
  let studyFolders = new Set();

  allFiles.forEach(f => {
    const parts = f.webkitRelativePath.split('/');
    if (parts.length === 2) {
      directFilesCount++;
    } else if (parts.length >= 3) {
      studyFolders.add(parts[1]);
    }
  });

  if (directFilesCount > 0) {
    summaryEl.innerHTML = `<span class="error-text">❌ Invalid Structure! Found ${directFilesCount} file(s) instead of study sub-folder. Please put all files inside a study subfolder.</span>`;
    upBtn.disabled = true;
    return;
  }

  if (studyFolders.size === 0) {
    summaryEl.innerHTML = '<span class="error-text">❌ Invalid Structure! Selected folder must contain at least one study subfolder inside it.</span>';
    upBtn.disabled = true;
    return;
  }

  selectedFiles = allFiles.filter(f => 
    f.name.toLowerCase().endsWith('.dcm') || !f.name.includes('.')
  );

  if (selectedFiles.length === 0) {
    summaryEl.innerHTML = '<span class="error-text">❌ No DICOM files found inside the study subfolders.</span>';
    upBtn.disabled = true;
    return;
  }

  summaryEl.innerHTML = `<span style="color: #4bff4b; font-weight: bold;">✅ Valid Structure!</span> Identified ${studyFolders.size} study folder(s) with ${selectedFiles.length} DICOM files.`;
  upBtn.disabled = false;
}

async function startBundleAndUpload() {
  const upBtn = document.getElementById('up-btn');
  const zip = new JSZip();
  const progBar = document.getElementById('progress-bar');
  const progPct = document.getElementById('prog-pct');
  const progLab = document.getElementById('prog-label');

  upBtn.disabled = true;
  document.getElementById('progress-wrap').style.display = 'block';

  progLab.textContent = "📦 Processing Patient/Follow-up paths...";

  selectedFiles.forEach((file) => {
    const parts = file.webkitRelativePath.split('/');
    const L = parts.length;

    let newPath;
    if (L >= 3) {
      newPath = parts[L-3] + "/" + parts[L-2] + "/" + parts[L-1];
    } else if (L === 2) {
      newPath = parts[L-2] + "/" + parts[L-1];
    } else {
      newPath = file.name;
    }

    zip.file(newPath, file);
  });

  const zipBlob = await zip.generateAsync({
    type: "blob",
    compression: "STORE"
  }, (meta) => {
    const p = Math.round(meta.percent * 0.3);
    progBar.style.width = p + '%';
    progPct.textContent = p + '%';
  });

  progLab.textContent = "📤 Uploading Bundle...";
  const startTime = Date.now();
  const fd = new FormData();

  const mySessionId = generateUUID();
  fd.append('file', zipBlob, 'study_bundle.zip');
  fd.append('session_id', mySessionId);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", SERVER + "/upload", true);

  let pollInterval = null;

  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const upPct = (e.loaded / e.total) * 100;
      const totalPct = Math.round(30 + (upPct * 0.6)); 

      if (!pollInterval) {
          progBar.style.width = totalPct + '%';
          progPct.textContent = totalPct + '%';
      }

      if (upPct >= 100 && !pollInterval) {
         progLab.innerHTML = '<span class="processing-anim">⚙️ Server-side Decompressing...</span>';
         document.getElementById('up-speed').textContent = "Upload Finished";
         document.getElementById('time-rem').textContent = "Extracting...";

         pollInterval = setInterval(async () => {
             try {
                 const res = await fetch(SERVER + "/upload-progress/" + mySessionId);
                 const data = await res.json();

                 if (data.total > 0) {
                     const extPct = (data.done / data.total) * 100;
                     const overallPct = Math.round(90 + (extPct * 0.1));

                     progBar.style.width = overallPct + '%';
                     progPct.textContent = overallPct + '%';
                     progLab.textContent = "⚙️ Extracting: " + data.done + " / " + data.total + " files";
                 }

                 if (data.status === "completed" || data.status === "completed_with_errors" || data.status.startsWith("failed")) {
                     clearInterval(pollInterval);
                     progBar.style.width = '100%';
                     progPct.textContent = '100%';

                     if (data.status === "completed") {
                         progLab.innerHTML = "✅ Complete! Table updates automatically";
                     } else if (data.status === "completed_with_errors") {
                         progLab.innerHTML = "<span class='warning-text'>⚠️ Completed with warnings.</span>";
                     } else {
                         progLab.innerHTML = "<span class='error-text'>❌ Extraction Failed: " + data.status + "</span>";
                     }

                     document.getElementById('time-rem').textContent = "Done";
                     upBtn.disabled = false;
                 }
             } catch (err) {
                 console.error("Polling error", err);
             }
         }, 500);

      } else if (upPct < 100) {
         const elapsed = (Date.now() - startTime) / 1000;
         const speedKbs = (e.loaded / 1024) / elapsed;
         document.getElementById('up-speed').textContent = speedKbs.toFixed(1) + " KB/s";
         const remSecs = (e.total - e.loaded) / (e.loaded / elapsed);
         document.getElementById('time-rem').textContent = Math.round(remSecs) + "s";
      }
    }
  };

  xhr.onerror = () => {
    if (pollInterval) clearInterval(pollInterval);
    progLab.innerHTML = "<span class='error-text'>❌ Connection Error: Cannot reach " + SERVER + "</span>";
    upBtn.disabled = false;
  };

  xhr.onload = () => {
    if (xhr.status !== 200) {
      if (pollInterval) clearInterval(pollInterval);
      progLab.innerHTML = "<span class='error-text'>❌ Server HTTP Error: " + xhr.status + "</span>";
      upBtn.disabled = false;
    }
  };

  xhr.send(fd);
}

if (window.Streamlit) Streamlit.setFrameHeight(560);
</script>
</body>
</html>
"""

# Inject SERVER_URL dynamically into the HTML template string
UPLOAD_COMPONENT_HTML = UPLOAD_COMPONENT_HTML_TEMPLATE.replace("__SERVER_URL__", SERVER_URL)


@st.fragment(run_every=60)
def ping_server_health():
    check_server_health.clear()
    health = check_server_health()

    if health:
        st.success("**✅ Backend Online**")
        with st.expander("Server Details"):
            st.write(f"**Target Host:** `{SERVER_URL}`")
            st.write(f"**Root Directory:** `{health.get('dicom_root')}`")
        st.caption(f"Last ping: {time.strftime('%H:%M:%S')}")
    else:
        st.error("**❌ Backend Offline**")
        st.info(f"Checking: `{SERVER_URL}`")
        st.caption(f"Last failed ping: {time.strftime('%H:%M:%S')}")


# =========================================================
# 3. INVENTORY TABLE COMPONENT
# =========================================================
@st.fragment(run_every=90)
def render_inventory_table():
    st.subheader("📂 Server Inventory")

    if "rows_per_page" not in st.session_state:
        st.session_state.rows_per_page = 25
    if "current_page" not in st.session_state:
        st.session_state.current_page = 1

    def on_rows_per_page_change():
        st.session_state.current_page = 1

    def reset_page():
        st.session_state.current_page = 1

    col1, col2, col3 = st.columns([1.2, 1.8, 3])
    with col1:
        if st.button("🔄 Refresh List"):
            fetch_studies.clear()
            check_server_health.clear()
            st.rerun()

    is_healthy = check_server_health()

    if is_healthy:
        studies = fetch_studies()
        if studies:
            df = pd.DataFrame(studies)
            qc_summary = load_qc_summary()

            def process_qc_status(row):
                imgs = row.get("images_count", 0)
                vids = row.get("videos_count", 0)
                reps = row.get("reports_count", 0)
                tot = row.get("total_files", 0)

                parts = []
                if imgs > 0: parts.append(f"🖼️ {imgs}")
                if vids > 0: parts.append(f"🎥 {vids}")
                if reps > 0: parts.append(f"📄 {reps}")

                breakout_str = " • ".join(parts) if parts else str(tot)

                qc = qc_summary.get((str(row["patient_id"]).rstrip("__") + str(row["study_uid"])[:8]), {})
                v, g, a = qc.get("v", 0), qc.get("g", 0), qc.get("a", 0)

                has_qc = (v > 0 or g > 0 or a > 0)
                if has_qc:
                    breakout_str += f" | (QC: V={v}, G={g}, A={a})"
                    status = "⛔ Protected (Has QC)"
                else:
                    status = "🗑️ Eligible for Delete"

                return pd.Series([breakout_str, status, has_qc])

            df[["Asset Breakout", "QC Status", "Has QC"]] = df.apply(process_qc_status, axis=1)

            df["Action"] = df.apply(
                lambda row: f"{VIEWER_URL}/?StudyDate={row['study_uid'][0:8]}&PatientID={row['patient_id']}",
                axis=1
            )

            deletable_df = df[~df["Has QC"]]
            with col2:
                if not deletable_df.empty:
                    with st.popover("🗑️ Delete Study"):
                        st.markdown("**Delete Unverified Study**")
                        st.caption("Only studies with **0 QC entries** (V=0, G=0, A=0) can be deleted.")

                        options = {
                            f"{row['patient_id']} | {row['study_uid']}": (row['patient_id'], row['study_uid'])
                            for _, row in deletable_df.iterrows()
                        }

                        selected_option = st.selectbox(
                            "Select study to delete:",
                            options=list(options.keys()),
                            key="delete_study_selector"
                        )

                        if selected_option:
                            pid, suid = options[selected_option]
                            if st.button("⚠️ Confirm Delete", type="primary", key="confirm_del_btn"):
                                success, msg = delete_study_on_server(pid, suid)
                                if success:
                                    st.toast(f"✅ {msg}", icon="🗑️")
                                    fetch_studies.clear()
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"❌ Deletion failed: {msg}")
                else:
                    st.caption("🔒 All studies have active QC data.")

            with col3:
                st.caption(f"Auto-updating every 90s • Last checked: {time.strftime('%H:%M:%S')}")

            display_df = df[["patient_id", "study_uid", "Asset Breakout", "QC Status", "Action"]].copy()
            display_df.columns = [
                "Patient ID",
                "Study UID",
                "Assets (Images / Videos / Reports)",
                "Status",
                "Action"
            ]

            search_query = st.text_input(
                "🔍 Search Inventory",
                placeholder="Type Patient ID or Study...",
                on_change=reset_page
            )
            if search_query:
                mask = display_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)
                display_df = display_df[mask]
                st.caption(f"Found {len(display_df)} results.")

            col_size, col_page, col_info = st.columns([2, 2, 3])

            with col_size:
                rows_per_page = st.selectbox(
                    "Rows per page",
                    options=[10, 25, 50, 100],
                    key="rows_per_page",
                    on_change=on_rows_per_page_change
                )

            total_rows = len(display_df)
            total_pages = max(1, math.ceil(total_rows / rows_per_page))

            if st.session_state.current_page > total_pages:
                st.session_state.current_page = total_pages

            with col_page:
                current_page = st.number_input(
                    "Page",
                    min_value=1,
                    max_value=total_pages,
                    key="current_page",
                    step=1
                )

            start_idx = (current_page - 1) * rows_per_page
            end_idx = start_idx + rows_per_page
            paginated_df = display_df.iloc[start_idx:end_idx]

            with col_info:
                st.caption(
                    f"Showing **{start_idx + 1 if total_rows > 0 else 0}** to "
                    f"**{min(end_idx, total_rows)}** of **{total_rows}** entries"
                )

            calculated_height = (len(paginated_df) + 1) * 35 + 3

            st.dataframe(
                paginated_df,
                width='stretch',
                height=calculated_height,
                hide_index=True,
                column_config={
                    "Patient ID": st.column_config.TextColumn("Patient ID"),
                    "Study UID": st.column_config.TextColumn("Study UID"),
                    "Assets (Images / Videos / Reports)": st.column_config.TextColumn(
                        "Assets (Images / Videos / Reports)"),
                    "Status": st.column_config.TextColumn("QC Status"),
                    "Action": st.column_config.LinkColumn("Open Study", display_text="👁️ Open Viewer")
                }
            )
        else:
            st.info("No studies found on server. Start an upload to see data here.")
    else:
        st.error(f"Cannot reach server at {SERVER_URL}")


# =========================================================
# 4. MAIN LAYOUT EXECUTION
# =========================================================
with st.sidebar:
    st.header("⚙️ System Status")
    ping_server_health()
    st.divider()

    st.subheader("📤 DICOM Upload")

    # Dynamically inject SERVER_URL into the HTML string before Base64 encoding
    final_html = UPLOAD_COMPONENT_HTML_TEMPLATE.replace("__SERVER_URL__", SERVER_URL)
    b64_html = base64.b64encode(final_html.encode("utf-8")).decode("utf-8")

    iframe_code = f"""
        <iframe 
            src="data:text/html;base64,{b64_html}" 
            width="100%" 
            height="560" 
            style="border:none; overflow:hidden; background-color: transparent;">
        </iframe>
    """
    st.markdown(iframe_code, unsafe_allow_html=True)

render_inventory_table()