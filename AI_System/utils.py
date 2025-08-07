import fitz  # PyMuPDF

def extract_and_store_clauses(file_obj, task_id=None):
    from .models import Document, Clause
    from django.core.cache import cache

    # Save document in DB
    doc = Document.objects.create(name=file_obj.name, file_path=file_obj.name)

    # Read PDF
    pdf = fitz.open(stream=file_obj.read(), filetype="pdf")
    text_buffer = []
    for page in pdf:
        text_buffer.append(page.get_text("text"))
    full_text = "\n".join(text_buffer)

    # Split into paragraphs (keep large chunks intact)
    raw_clauses = [p.strip() for p in full_text.split("\n") if p.strip()]
    clauses = []
    buffer = ""

    for line in raw_clauses:
        if len(line) < 40:  # too short, merge with previous
            buffer += " " + line
        else:
            if buffer:
                clauses.append(buffer.strip())
                buffer = ""
            clauses.append(line)

    if buffer:
        clauses.append(buffer.strip())

    # Save clauses
    for i, clause in enumerate(clauses):
        Clause.objects.create(document=doc, clause_text=clause)
        if task_id:
            progress = int((i + 1) / len(clauses) * 100)
            cache.set(f"progress_{task_id}", progress, timeout=600)

    return doc, len(clauses)
