import json
import uuid
import os
from threading import Thread

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils.dateformat import DateFormat

import google.generativeai as genai
from sentence_transformers import SentenceTransformer
import faiss

from .models import Document, Clause, Query, Decision
from .utils import extract_and_store_clauses

# ------------------- FAISS Semantic Search -------------------
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
faiss_index = None
clause_texts = []


def build_faiss_index():
    """Rebuild FAISS index from DB clauses."""
    global faiss_index, clause_texts
    clauses = Clause.objects.all()
    clause_texts = [c.clause_text for c in clauses]

    if not clause_texts:
        faiss_index = None
        return None

    embeddings = embedding_model.encode(clause_texts, convert_to_numpy=True)
    dim = embeddings.shape[1]
    faiss_index = faiss.IndexFlatL2(dim)
    faiss_index.add(embeddings)
    return faiss_index


def semantic_search(query_text, top_k=3):
    """Return top-k relevant clauses."""
    global faiss_index, clause_texts
    if faiss_index is None:
        build_faiss_index()

    if faiss_index is None or len(clause_texts) == 0:
        return []

    query_vec = embedding_model.encode([query_text], convert_to_numpy=True)
    distances, indices = faiss_index.search(query_vec, top_k)

    results = []
    for idx in indices[0]:
        if idx < len(clause_texts):
            results.append(clause_texts[idx])
    return results


# ------------------- Views -------------------

def home(request):
    """Render home.html with latest 5 documents."""
    latest_docs = Document.objects.order_by('-upload_date')[:5]
    return render(request, "home.html", {"latest_docs": latest_docs})


@csrf_exempt
def upload_document(request):
    """Upload and extract clauses with progress tracking + duplicate check."""
    if request.method == "POST":
        file_obj = request.FILES['document']

        # Duplicate check by name
        if Document.objects.filter(name=file_obj.name).exists():
            return JsonResponse({
                "error": f"⚠️ File '{file_obj.name}' already uploaded. Please use it from the list."
            }, status=400)

        task_id = str(uuid.uuid4())
        cache.set(f"progress_{task_id}", 0, timeout=600)

        # Run extraction + FAISS rebuild in background thread
        def process_file():
            extract_and_store_clauses(file_obj, task_id)
            build_faiss_index()

        Thread(target=process_file).start()

        # Return latest docs (with formatted dates)
        latest_docs_qs = Document.objects.order_by('-upload_date')[:5]
        latest_docs = [
            {
                "id": doc.id,
                "name": doc.name,
                "upload_date": DateFormat(doc.upload_date).format('d M Y, H:i')
            }
            for doc in latest_docs_qs
        ]

        return JsonResponse({"task_id": task_id, "latest_docs": latest_docs})

    return JsonResponse({"error": "Invalid request"}, status=400)


def get_progress(request, task_id):
    """Return progress for upload task (for progress bar)."""
    progress = cache.get(f"progress_{task_id}", 0)
    return JsonResponse({"progress": progress})


@csrf_exempt
def delete_document(request, doc_id):
    """Delete a document and its clauses."""
    doc = get_object_or_404(Document, id=doc_id)
    doc.delete()
    build_faiss_index()

    # Return updated list after deletion
    latest_docs_qs = Document.objects.order_by('-upload_date')[:5]
    latest_docs = [
        {
            "id": d.id,
            "name": d.name,
            "upload_date": DateFormat(d.upload_date).format('d M Y, H:i')
        }
        for d in latest_docs_qs
    ]
    return JsonResponse({"message": "Document deleted", "latest_docs": latest_docs})


@csrf_exempt


def use_existing_document(request, doc_id):
    try:
        document = Document.objects.get(pk=doc_id)
        request.session['selected_doc_id'] = doc_id
        return JsonResponse({'success': True})
    except Document.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Document not found'}, status=404)



# ------------------- Query Processing -------------------

@csrf_exempt
def process_query(request):
    """Handle user query with Gemini + semantic search."""
    if request.method == "POST":
        data = json.loads(request.body)
        query_text = data.get('query')

        # Save query in DB
        q = Query.objects.create(query_text=query_text)

        # Configure Gemini client
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

        try:
            # -------- Parse Query --------
            parse_prompt = f"""
            Extract key attributes from this insurance query:
            "{query_text}"
            Return valid JSON with: age, gender, procedure, location, policy_duration
            """
            parsed_res = model.generate_content(parse_prompt).text.strip()
            if parsed_res.startswith("```"):
                parsed_res = parsed_res.replace("```json", "").replace("```", "").strip()

            try:
                parsed_data = json.loads(parsed_res)
            except json.JSONDecodeError:
                parsed_data = {}

            q.parsed_data = parsed_data
            q.save()

            # -------- Semantic Search with full clause context --------
            matched_clauses_snippets = semantic_search(query_text, top_k=5)

            matched_clauses_texts = []
            for snippet in matched_clauses_snippets:
                clause_obj = Clause.objects.filter(clause_text__icontains=snippet).first()
                if clause_obj:
                    matched_clauses_texts.append(clause_obj.clause_text)

            if not matched_clauses_texts:
                matched_clauses_texts = matched_clauses_snippets

            # -------- Decision Engine --------
            decision_prompt = f"""
            You are an Insurance Policy Decision AI.

            Question: "{query_text}"
            Relevant Clauses: {matched_clauses_texts}

            Analyze carefully:
            1. Use the most relevant clause(s).
            2. If waiting period or eligibility is clear, return it.
            3. If information is missing, mark "Needs Review".

            Return ONLY JSON:
            {{
              "decision": "Approved"/"Rejected"/"Needs Review",
              "amount": number/null,
              "justification": "short explanation",
              "referenced_clauses": ["..."]
            }}
            """

            decision_res = model.generate_content(decision_prompt).text.strip()
            if decision_res.startswith("```"):
                decision_res = decision_res.replace("```json", "").replace("```", "").strip()

            try:
                decision_data = json.loads(decision_res)
            except json.JSONDecodeError:
                decision_data = {
                    "decision": "Needs Review",
                    "amount": None,
                    "justification": "Gemini returned invalid output.",
                    "referenced_clauses": matched_clauses_texts
                }

            # Ensure keys
            if "decision" not in decision_data:
                decision_data["decision"] = "Needs Review"
                decision_data["amount"] = None
                decision_data["justification"] = "Insufficient data to decide."
                decision_data["referenced_clauses"] = matched_clauses_texts

            # Save decision in DB
            Decision.objects.create(
                query=q,
                decision_status=decision_data["decision"],
                amount=decision_data.get("amount"),
                justification=decision_data["justification"],
                referenced_clauses=decision_data.get("referenced_clauses", matched_clauses_texts)
            )

            return JsonResponse(decision_data)

        except Exception as e:
            return JsonResponse({
                "decision": "Needs Review",
                "amount": None,
                "justification": f"❌ Error: {str(e)}",
                "referenced_clauses": []
            }, status=500)

    return JsonResponse({"error": "Invalid request"}, status=400)
