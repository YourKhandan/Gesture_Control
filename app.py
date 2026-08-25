"""
app.py — HandDeck (Streamlit frontend)
----------------------------------------
Ties together:
  - upload_converter.py  (pptx/pdf -> slide images)
  - gesture_control.py   (browser webcam -> gesture actions, via streamlit-webrtc)

"""

import time

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_webrtc import RTCConfiguration, WebRtcMode, webrtc_streamer

from gesture_control import GestureProcessor
from upload_converter import ConversionError, libreoffice_available, process_uploaded_file

st.set_page_config(page_title="HandDeck", page_icon="🖐️", layout="wide")

# ---------- Minimal HUD-style theming ----------
st.markdown(
    """
    <style>
    .stApp { background-color: #0a0d0b; color: #e8f0ea; }
    .status-box {
        font-family: monospace; padding: 10px 14px; border: 1px solid #22302a;
        border-radius: 4px; background: #10151a; margin-bottom: 10px;
    }
    .status-ok { color: #39ff7a; }
    .status-muted { color: #7e8e85; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🖐️ HandDeck — Gesture Slide Control")
st.caption("Upload a PPTX or PDF, allow camera access, and page through it with hand gestures.")

#  Session state 
if "slides" not in st.session_state:
    st.session_state.slides = []       # list of image paths
if "current" not in st.session_state:
    st.session_state.current = 0
if "last_gesture_action_ts" not in st.session_state:
    st.session_state.last_gesture_action_ts = 0.0

#  1. Upload & convert
st.subheader("1. Upload your deck")

if not libreoffice_available():
    st.warning(
        "LibreOffice isn't detected on this server, so **.pptx/.ppt uploads will fail** "
        "at the conversion step. **PDF uploads still work fine** — export your deck as "
        "PDF from PowerPoint for now, or see README.md to fix LibreOffice.",
        icon="⚠️",
    )

uploaded_file = st.file_uploader("PPTX, PPT, or PDF", type=["pptx", "ppt", "pdf"])

if uploaded_file is not None and st.session_state.get("_last_upload_name") != uploaded_file.name:
    progress_box = st.empty()

    def report(msg):
        progress_box.info(msg)

    try:
        images = process_uploaded_file(uploaded_file, progress_callback=report)
        st.session_state.slides = images
        st.session_state.current = 0
        st.session_state._last_upload_name = uploaded_file.name
        progress_box.success(f"Loaded {len(images)} slide(s).")
    except ConversionError as e:
        progress_box.error(str(e))

#2. Slide viewer

st.subheader("2. Deck")
deck_container = st.container()

# 3. Gesture control 
st.subheader("3. Gesture control")
st.markdown(
    "✊ **Fist** → previous slide &nbsp;&nbsp;|&nbsp;&nbsp; "
    "✋ **Open palm** → next slide &nbsp;&nbsp;|&nbsp;&nbsp; "
    "☝ **One finger** → jump to first slide (start)"
)

# Public STUN server so WebRTC can establish a connection from the visitor's
# browser to this server when deployed (needed on most cloud hosts).
RTC_CONFIGURATION = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)

ctx = webrtc_streamer(
    key="handdeck-gesture",
    mode=WebRtcMode.SENDRECV,
    rtc_configuration=RTC_CONFIGURATION,
    video_processor_factory=GestureProcessor,
    media_stream_constraints={"video": True, "audio": False},
    async_processing=True,
)

status_placeholder = st.empty()

# Poll the processor for new gesture actions a few times a second and apply
# them to the slide deck. st_autorefresh triggers a script rerun on an
# interval so we pick up results produced on the WebRTC worker thread.
if ctx.state.playing:
    st_autorefresh(interval=300, key="gesture_poll")

    if ctx.video_processor:
        action = ctx.video_processor.get_action()
        status_text, fingers = ctx.video_processor.get_status()

        if action == "prev" and st.session_state.slides:
            st.session_state.current = max(0, st.session_state.current - 1)
        elif action == "next" and st.session_state.slides:
            st.session_state.current = min(
                len(st.session_state.slides) - 1, st.session_state.current + 1
            )
        elif action == "start" and st.session_state.slides:
            st.session_state.current = 0

        status_placeholder.markdown(
            f"<div class='status-box'>STATUS: <span class='status-ok'>{status_text}</span> "
            f"&nbsp;|&nbsp; fingers detected: {fingers if fingers >= 0 else '—'}</div>",
            unsafe_allow_html=True,
        )
else:
    status_placeholder.markdown(
        "<div class='status-box status-muted'>Camera not started — click Start above and allow camera access.</div>",
        unsafe_allow_html=True,
    )


with deck_container:
    if st.session_state.slides:
        col_prev, col_view, col_next = st.columns([1, 6, 1])
        with col_prev:
            if st.button("← Prev"):
                st.session_state.current = max(0, st.session_state.current - 1)
        with col_next:
            if st.button("Next →"):
                st.session_state.current = min(
                    len(st.session_state.slides) - 1, st.session_state.current + 1
                )
        with col_view:
            st.image(
                st.session_state.slides[st.session_state.current],
                use_container_width=True,
                caption=f"Slide {st.session_state.current + 1} / {len(st.session_state.slides)}",
            )
    else:
        st.info("Upload a file above to see slides here.")

st.divider()
with st.expander("How this works / limitations"):
    st.markdown(
        """
- Your webcam frames are sent from your browser to this app's server via WebRTC (after you grant permission) —
  they are **not** stored, just processed frame-by-frame and discarded.
- Because this runs on a server rather than your own PC, it **cannot** press keys inside a native PowerPoint
  window on your computer (that's what the original `pyautogui` version did, only locally). Instead, gestures
  drive the slide viewer built into this page.
- If your camera doesn't connect after clicking Start, it's usually a restrictive network blocking the WebRTC
  connection — try a different network, or a TURN server would be needed for that case.
        """
    )
