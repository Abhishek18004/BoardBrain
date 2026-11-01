import os
import re
import shutil
from pathlib import Path

import pymupdf
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
VECTOR_DIR = BASE_DIR / "vector_db"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 180

MIN_INDEX_CHUNK_CHARS = 100

EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL",
    "gemini-embedding-001"
)

FONT_CODE_PATTERN = re.compile(r"/K[0-9A-Fa-f]{2}")
FONT_CODE_SEQUENCE_PATTERN = re.compile(
    r"(?:/K[0-9A-Fa-f]{2}){4,}"
)


# ---------------------------------------------------------
# 1. TEXT CLEANING
# ---------------------------------------------------------

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\x00", "")
    text = text.replace("\u00ad", "")
    text = text.replace("\r", "\n")
    text = text.replace("\xa0", " ")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def check_extraction_quality(documents):
    """
    Detect an obvious PDF font-decoding problem.

    This check is deliberately conservative. It catches the
    /K68/K61-style sequences seen in the current Catan samples.
    """

    problematic_pages = []

    for document in documents:
        text = document.page_content

        code_count = len(FONT_CODE_PATTERN.findall(text))
        has_sequence = bool(
            FONT_CODE_SEQUENCE_PATTERN.search(text)
        )

        if has_sequence or code_count >= 8:
            problematic_pages.append({
                "page": document.metadata["page_number"],
                "font_code_count": code_count
            })

    if problematic_pages:
        details = ", ".join(
            f"page {item['page']} ({item['font_code_count']} tokens)"
            for item in problematic_pages
        )

        raise ValueError(
            "PDF extraction contains suspicious font-code sequences. "
            f"Problematic pages: {details}. "
            "Inspect the PDF extraction before indexing."
        )


# ---------------------------------------------------------
# 2. PDF EXTRACTION
# ---------------------------------------------------------

def load_rulebook(pdf_path):
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"Rulebook not found: {pdf_path}"
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported.")

    documents = []

    with pymupdf.open(pdf_path) as pdf:

        for page_index, page in enumerate(pdf):

            page_text = page.get_text(
                "text",
                sort=True
            )

            page_text = clean_text(page_text)

            if not page_text:
                continue

            metadata = {
                "filename": pdf_path.name,
                "page_number": page_index + 1
            }

            documents.append(
                Document(
                    page_content=page_text,
                    metadata=metadata
                )
            )

    if not documents:
        raise ValueError(
            "No usable text could be extracted from this PDF."
        )

    check_extraction_quality(documents)

    return documents


# ---------------------------------------------------------
# 3. DOCUMENT CHUNKING
# ---------------------------------------------------------

def split_documents(documents):

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            ""
        ]
    )

    chunks = splitter.split_documents(documents)

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index

    return chunks


# ---------------------------------------------------------
# 4. GAME-SPECIFIC INDEX PATH
# ---------------------------------------------------------

def get_game_index_path(game_id):

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", game_id):
        raise ValueError("Invalid game ID.")

    return VECTOR_DIR / game_id


# ---------------------------------------------------------
# 5. GEMINI RETRIEVAL EMBEDDINGS
# ---------------------------------------------------------

class BoardBrainEmbeddings(Embeddings):
    """
    Uses the same Gemini embedding model for both sides of retrieval,
    but the correct task type for each operation.
    """

    def __init__(self):

        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY is missing from .env"
            )

        self.document_embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=api_key,
            task_type="RETRIEVAL_DOCUMENT"
        )

        self.query_embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=api_key,
            task_type="RETRIEVAL_QUERY"
        )

    def embed_documents(self, texts):
        return self.document_embeddings.embed_documents(texts)

    def embed_query(self, text):
        return self.query_embeddings.embed_query(text)


def get_embeddings():
    return BoardBrainEmbeddings()


# ---------------------------------------------------------
# 6. ATOMIC INDEX SAVING
# ---------------------------------------------------------

def save_index_safely(vector_store, index_path):

    index_path = Path(index_path)

    building_path = index_path.parent / (
        index_path.name + "_building"
    )

    backup_path = index_path.parent / (
        index_path.name + "_backup"
    )

    if building_path.exists():
        shutil.rmtree(building_path)

    if backup_path.exists():
        shutil.rmtree(backup_path)

    building_path.mkdir(
        parents=True,
        exist_ok=True
    )

    try:

        vector_store.save_local(str(building_path))

        # Keep the old index until the new one has been saved.
        if index_path.exists():
            os.replace(index_path, backup_path)

        os.replace(building_path, index_path)

        if backup_path.exists():
            shutil.rmtree(backup_path)

    except Exception:

        if building_path.exists():
            shutil.rmtree(building_path)

        # Restore the old index if replacement failed.
        if backup_path.exists() and not index_path.exists():
            os.replace(backup_path, index_path)

        raise


# ---------------------------------------------------------
# 7. CREATE A GAME INDEX
# ---------------------------------------------------------

def create_game_index(pdf_path, game_id, game_name):

    pages = load_rulebook(pdf_path)

    for page in pages:
        page.metadata["game_id"] = game_id
        page.metadata["game_name"] = game_name

    chunks = split_documents(pages)

    # Skip tiny, non-informative cover/title chunks.
    usable_chunks = [
        chunk
        for chunk in chunks
        if len(chunk.page_content.strip()) >= MIN_INDEX_CHUNK_CHARS
    ]

    if not usable_chunks:
        raise ValueError(
            "No sufficiently useful text chunks were generated."
        )

    for index, chunk in enumerate(usable_chunks):
        chunk.metadata["chunk_index"] = index

    embeddings = get_embeddings()

    vector_store = FAISS.from_documents(
        documents=usable_chunks,
        embedding=embeddings
    )

    index_path = get_game_index_path(game_id)

    VECTOR_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    save_index_safely(
        vector_store,
        index_path
    )

    return {
        "game_id": game_id,
        "game_name": game_name,
        "total_pages": len(pages),
        "total_chunks": len(usable_chunks),
        "index_path": str(index_path)
    }


# ---------------------------------------------------------
# 8. LOAD AN EXISTING GAME INDEX
# ---------------------------------------------------------

def load_game_index(game_id):

    index_path = get_game_index_path(game_id)

    if not (index_path / "index.faiss").exists():
        raise FileNotFoundError(
            f"No FAISS index exists for game: {game_id}"
        )

    embeddings = get_embeddings()

    # Only load indexes generated and stored by this application.
    # Never accept arbitrary user-supplied FAISS pickle files.
    return FAISS.load_local(
        str(index_path),
        embeddings,
        allow_dangerous_deserialization=True
    )


# ---------------------------------------------------------
# 9. RETRIEVE RULES
# ---------------------------------------------------------

def retrieve_rules(game_id, question, k=5):

    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    if k < 1:
        raise ValueError("k must be at least 1.")

    vector_store = load_game_index(game_id)

    total_vectors = len(vector_store.index_to_docstore_id)

    if total_vectors == 0:
        return []

    results = vector_store.similarity_search_with_score(
        question.strip(),
        k=min(k, total_vectors)
    )

    retrieved = []

    for document, distance in results:

        metadata = document.metadata

        # Defensive check: never return another game's content.
        if metadata.get("game_id") != game_id:
            continue

        retrieved.append({
            "content": document.page_content,
            "page_number": metadata.get("page_number", 1),
            "filename": metadata.get("filename", "Unknown"),
            "game_id": metadata.get("game_id", game_id),
            "game_name": metadata.get("game_name", "Unknown"),
            "chunk_index": metadata.get("chunk_index", -1),
            "relevance_distance": float(distance)
        })

    return retrieved