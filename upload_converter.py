"""
upload_converter.py
--------------------
Handles turning an uploaded file (.pptx / .ppt / .pdf) into a list of
slide image paths that the frontend can display and page through.

Pipeline:
    .pptx / .ppt  -> LibreOffice headless -> .pdf -> PyMuPDF -> images
    .pdf          ->                                PyMuPDF -> images   (conversion step skipped)

Notes for deployment (Streamlit Community Cloud):
- LibreOffice ("soffice") is a system binary, not a pip package. Add a
  `packages.txt` file (already included) with the line `libreoffice` so
  Streamlit Cloud installs it via apt before your app starts.
- PDF -> image rendering uses PyMuPDF (`fitz`), which is pure pip-installable
  and needs no system binary, so it works the same locally and in the cloud.
"""

import os
import shutil
import subprocess
import tempfile
import uuid

import fitz  # PyMuPDF

SUPPORTED_SLIDE_TYPES = {".pptx", ".ppt"}
SUPPORTED_PDF_TYPES = {".pdf"}

# Different OSes / installs expose the LibreOffice CLI under different names.
_LIBREOFFICE_BINARIES = ["soffice", "libreoffice"]


class ConversionError(Exception):
    """Raised when a file can't be converted or rendered."""


def find_libreoffice_binary() -> str | None:
    """Return the first available LibreOffice CLI binary name, or None if not installed."""
    for name in _LIBREOFFICE_BINARIES:
        if shutil.which(name):
            return name
    return None


def libreoffice_available() -> bool:
    return find_libreoffice_binary() is not None


def _save_upload_to_temp(uploaded_file, workdir: str) -> str:
    """Persist a Streamlit UploadedFile to disk so external tools (soffice, fitz) can read it."""
    suffix = os.path.splitext(uploaded_file.name)[1].lower()
    path = os.path.join(workdir, f"input_{uuid.uuid4().hex}{suffix}")
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path


def convert_pptx_to_pdf(pptx_path: str, output_dir: str) -> str:
    """Convert a .pptx/.ppt file to .pdf using headless LibreOffice."""
    binary = find_libreoffice_binary()
    if binary is None:
        raise ConversionError(
            "LibreOffice was not found on this server.\n\n"
            "- Running locally? Install it yourself (brew install libreoffice / "
            "sudo apt install libreoffice / the Windows installer) — packages.txt "
            "has no effect on your own machine.\n"
            "- Deployed on Streamlit Cloud? Confirm packages.txt is at the repo root "
            "with the line 'libreoffice', then use Manage app -> Reboot app "
            "(adding it after first deploy needs a reboot to take effect)."
        )

    cmd = [
        binary,
        "--headless",
        "--norestore",
        "--convert-to", "pdf",
        "--outdir", output_dir,
        pptx_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=180, capture_output=True)
    except FileNotFoundError:
        raise ConversionError(
            f"LibreOffice binary '{binary}' was detected but failed to launch. "
            "Try rebooting the app or reinstalling LibreOffice."
        )
    except subprocess.CalledProcessError as e:
        raise ConversionError(f"LibreOffice failed to convert the file: {e.stderr.decode(errors='ignore')}")
    except subprocess.TimeoutExpired:
        raise ConversionError("Conversion timed out — the file may be too large or complex.")

    expected_pdf = os.path.join(
        output_dir, os.path.splitext(os.path.basename(pptx_path))[0] + ".pdf"
    )
    if not os.path.exists(expected_pdf):
        raise ConversionError("Conversion finished but no PDF was produced.")
    return expected_pdf


def pdf_to_images(pdf_path: str, output_dir: str, zoom: float = 2.0) -> list[str]:
    """Render every page of a PDF to a PNG, sized up by `zoom` for a crisp fullscreen view."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise ConversionError(f"Could not open PDF: {e}")

    matrix = fitz.Matrix(zoom, zoom)
    image_paths = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=matrix)
        out_path = os.path.join(output_dir, f"slide_{i + 1:03d}.png")
        pix.save(out_path)
        image_paths.append(out_path)
    doc.close()

    if not image_paths:
        raise ConversionError("PDF had no pages to render.")
    return image_paths


def process_uploaded_file(uploaded_file, progress_callback=None) -> list[str]:
    """
    Main entry point. Takes a Streamlit UploadedFile (.pptx/.ppt/.pdf) and
    returns a list of PNG file paths, one per slide, in order.

    progress_callback: optional callable(str) for status updates (e.g. st.write).
    """
    def report(msg):
        if progress_callback:
            progress_callback(msg)

    workdir = tempfile.mkdtemp(prefix="handdeck_")
    ext = os.path.splitext(uploaded_file.name)[1].lower()

    saved_path = _save_upload_to_temp(uploaded_file, workdir)

    if ext in SUPPORTED_SLIDE_TYPES:
        report("Converting PowerPoint to PDF…")
        pdf_path = convert_pptx_to_pdf(saved_path, workdir)
    elif ext in SUPPORTED_PDF_TYPES:
        report("PDF supplied directly — skipping PowerPoint conversion.")
        pdf_path = saved_path
    else:
        raise ConversionError(f"Unsupported file type: {ext}. Please upload .pptx, .ppt, or .pdf.")

    report("Rendering pages to images…")
    images = pdf_to_images(pdf_path, workdir)
    report(f"Done — {len(images)} slide(s) ready.")
    return images