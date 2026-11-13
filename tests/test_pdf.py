from hiretrack.pdf_utils import detect_skills, extract_pdf_text


def _make_pdf(lines):
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 20
    c.save()
    return buf.getvalue()


def test_extract_text_from_real_pdf():
    pdf = _make_pdf(["Python Developer - Bengaluru", "Must have: Python, FastAPI, SQL", "Nice to have: Docker"])
    text, pages, warn = extract_pdf_text(pdf)
    assert pages == 1 and warn is None and "FastAPI" in text
    assert {"Python", "FastAPI", "SQL", "Docker"} <= set(detect_skills(text))


def test_bad_and_empty_pdfs_do_not_crash():
    text, pages, warn = extract_pdf_text(b"this is not a pdf")
    assert text == "" and warn
    blank = _make_pdf([])
    text, pages, warn = extract_pdf_text(blank)
    assert text == "" and "scanned" in warn
