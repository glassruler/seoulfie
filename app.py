import io
import time
import ssl
import streamlit as st
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Drive Gallery", layout="wide")


# ----------------------------
# Google Drive Client
# ----------------------------
@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gdrive"],
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


drive = get_drive_service()
ROOT_FOLDER_IDS = st.secrets["roots"]["folder_ids"]


# ----------------------------
# Helpers
# ----------------------------
@st.cache_data(show_spinner=False, ttl=300)
def get_folder_name(folder_id: str) -> str:
    meta = drive.files().get(fileId=folder_id, fields="name").execute()
    return meta["name"]


@st.cache_data(show_spinner=False, ttl=300)
def list_folders(parent_id: str):
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(
        q=q,
        fields="files(id, name)",
        orderBy="name",
        pageSize=1000,
    ).execute()
    return results.get("files", [])


@st.cache_data(show_spinner=False, ttl=300)
def list_images(parent_id: str):
    q = f"'{parent_id}' in parents and (mimeType contains 'image/') and trashed=false"
    results = drive.files().list(
        q=q,
        fields="files(id, name, mimeType)",
        orderBy="name",
        pageSize=1000,
    ).execute()
    return results.get("files", [])


@st.cache_data(show_spinner=False)
def download_image_bytes(file_id: str) -> bytes:
    """
    Download bytes from Google Drive with retry to reduce random SSL/connection errors.
    """
    last_error = None

    for attempt in range(3):
        try:
            request = drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            return fh.getvalue()

        except ssl.SSLError as e:
            last_error = e
            time.sleep(0.8)  # small cooldown helps stability
        except Exception as e:
            last_error = e
            time.sleep(0.5)

    raise last_error


def render_gallery(images, cols=4, max_size=(2000, 2000)):
    """
    Render images as a grid. Each image download is isolated so one failure won't crash the app.
    """
    columns = st.columns(cols)

    for i, img in enumerate(images):
        with columns[i % cols]:
            try:
                img_bytes = download_image_bytes(img["id"])
                pil_img = Image.open(io.BytesIO(img_bytes))

                # Reduce memory pressure for huge DSLR images
                pil_img.thumbnail(max_size)

                st.image(pil_img, caption=img["name"], use_container_width=True)

            except Exception as e:
                st.error(f"Failed to load: {img['name']}")
                st.caption(str(e))


# ----------------------------
# UI
# ----------------------------
st.title("📸 Seoulfie Photo Gallery")

if st.sidebar.button("🔄 Refresh Drive Data"):
    st.cache_data.clear()
    st.rerun()

#st.caption("Private gallery: images are fetched securely via Google Drive API (Service Account).")

# Root selection
root_map = {get_folder_name(fid): fid for fid in ROOT_FOLDER_IDS}
root_names = sorted(root_map.keys())

selected_root_name = st.sidebar.selectbox("🏠 Select Studio", root_names)
selected_root_id = root_map[selected_root_name]

# Session selection (subfolders)
sessions = list_folders(selected_root_id)

if not sessions:
    st.warning("No session folders found in this Studio folder.")
    st.stop()

# Sort newest first by folder name (works well with date-based naming)
sessions = sorted(sessions, key=lambda x: x["name"], reverse=True)

# Optional: search filter for sessions
search = st.sidebar.text_input("🔎 Search session", "").strip().lower()
if search:
    sessions = [s for s in sessions if search in s["name"].lower()]

if not sessions:
    st.warning("No sessions match your search.")
    st.stop()

session_names = [s["name"] for s in sessions]
selected_session_name = st.sidebar.selectbox("🗂️ Select Session", session_names)
selected_session = next(s for s in sessions if s["name"] == selected_session_name)

st.subheader(f"Studio: {selected_root_name}")
st.subheader(f"Session: {selected_session_name}")

# Image list
images = list_images(selected_session["id"])

if not images:
    st.warning("No images found in this session folder.")
    st.stop()

# Sidebar controls
cols = st.sidebar.slider("🧱 Gallery Columns", 2, 6, 4)
page_size = st.sidebar.slider("📄 Images per page", 10, 100, 30)

# Pagination
total = len(images)
total_pages = max(1, (total + page_size - 1) // page_size)

page = st.sidebar.number_input("📌 Page", min_value=1, max_value=total_pages, value=1)

start = (page - 1) * page_size
end = min(start + page_size, total)
images_page = images[start:end]

st.caption(f"Showing images {start + 1}-{end} of {total} (Page {page}/{total_pages})")

# Render
render_gallery(images_page, cols=cols)
