import os
import json
import re

from typing import TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI

from schemas import AgentResponse, RuleReference
from rag import retrieve_rules


load_dotenv()

CHAT_MODEL = os.getenv(
    "GEMINI_CHAT_MODEL",
    "gemini-3.8-flash"
)

MAX_REPAIR_ATTEMPTS = int(
    os.getenv("MAX_REPAIR_ATTEMPTS", "2")
)

TOP_K = 5

_llm = None
_graph = None


# ---------------------------------------------------------
# 1. GRAPH STATE
# ---------------------------------------------------------

class BoardBrainState(TypedDict, total=False):

    game_id: str
    game_name: str
    question: str

    history: list

    retrieved_documents: list

    answer: str
    candidate_answer: str

    references: list

    verified: bool
    verification_feedback: str

    retry_count: int
    needs_clarification: bool


# ---------------------------------------------------------
# 2. GEMINI MODEL
# ---------------------------------------------------------

def get_llm():

    global _llm

    if _llm is None:

        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY is missing from .env"
            )

        _llm = ChatGoogleGenerativeAI(
            model=CHAT_MODEL,
            api_key=api_key,
            temperature=0.2,
            max_retries=2
        )

    return _llm


def get_response_text(response):

    content = response.content

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):

        text_parts = []

        for item in content:

            if isinstance(item, dict):
                text_parts.append(item.get("text", ""))

            elif isinstance(item, str):
                text_parts.append(item)

        return "\n".join(text_parts).strip()

    return str(content).strip()


# ---------------------------------------------------------
# 3. JSON PARSING FOR VERIFICATION
# ---------------------------------------------------------

def extract_json(text):

    text = text.strip()

    # Remove Markdown code fences if present.
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            "Gemini did not return valid JSON."
        )

    return json.loads(text[start:end + 1])


# ---------------------------------------------------------
# 4. PREPARE THE RETRIEVED CONTEXT
# ---------------------------------------------------------

def build_context(documents):

    if not documents:
        return ""

    context_parts = []

    for index, document in enumerate(documents, start=1):

        content = document["content"]

        context_parts.append(
            f"""
SOURCE {index}
Game: {document["game_name"]}
Filename: {document["filename"]}
Page: {document["page_number"]}
Chunk: {document["chunk_index"]}

CONTENT:
{content}
""".strip()
        )

    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(
        context_parts
    )


def format_history(history):

    if not history:
        return "No previous conversation."

    lines = []

    # Only retain the most recent messages.
    for message in history[-8:]:

        if not isinstance(message, dict):
            continue

        role = str(message.get("role", "")).lower()
        content = str(message.get("content", "")).strip()

        if role not in {"user", "assistant"}:
            continue

        if not content:
            continue

        content = content[:2000]

        lines.append(
            f"{role.upper()}: {content}"
        )

    return "\n".join(lines) if lines else "No previous conversation."


# ---------------------------------------------------------
# 5. RETRIEVAL NODE
# ---------------------------------------------------------

def retrieve_node(state):

    retrieved_documents = retrieve_rules(
        game_id=state["game_id"],
        question=state["question"],
        k=TOP_K
    )

    return {
        "retrieved_documents": retrieved_documents,
        "retry_count": 0,
        "verified": False,
        "candidate_answer": "",
        "answer": "",
        "references": []
    }


def route_after_retrieval(state):

    if state.get("retrieved_documents"):
        return "generate"

    return "finalize"


# ---------------------------------------------------------
# 6. GENERATION NODE
# ---------------------------------------------------------

def generate_node(state):

    llm = get_llm()

    context = build_context(
        state.get("retrieved_documents", [])
    )

    history = format_history(
        state.get("history", [])
    )

    previous_feedback = state.get(
        "verification_feedback",
        ""
    )

    repair_instruction = ""

    if previous_feedback:
        repair_instruction = f"""
Your previous answer did not pass the verification step.

Verification feedback:
{previous_feedback}

Rewrite the answer using only the supplied source passages.
Remove any unsupported claims and correct invalid citations.
"""

    prompt = f"""
You are BoardBrain, a board-game rules assistant.

Your task is to answer the user's question using the supplied
official rulebook passages.

GAME:
{state.get("game_name", "Unknown")}

USER QUESTION:
{state["question"]}

RECENT CONVERSATION:
{history}

RETRIEVED RULEBOOK PASSAGES:
{context}

STRICT RULES:

1. Treat the retrieved passages as the source of truth for
   game rules.

2. Do not invent rules, numbers, exceptions, penalties,
   turn sequences, or conditions.

3. Cite every important rule-based claim using this exact format:
   [Page 3]

4. The page number must exist in the supplied passages.

5. If the passages do not contain enough information, clearly say:
   "I couldn't find a reliable answer to this in the uploaded rulebook."

6. Do not pretend that an answer is verified just because it
   sounds reasonable.

7. If the user asks for strategy, distinguish your strategic
   suggestion from an official rule.

8. Answer naturally and directly. Use short steps or bullets
   when they make the explanation easier to follow.

9. Never cite a page that was not supplied in the context.

{repair_instruction}

Write the answer only. Do not include internal reasoning.
"""

    response = llm.invoke(prompt)

    candidate_answer = get_response_text(response)

    return {
        "candidate_answer": candidate_answer
    }


# ---------------------------------------------------------
# 7. VERIFICATION NODE
# ---------------------------------------------------------

def verify_node(state):

    llm = get_llm()

    answer = state.get("candidate_answer", "")

    documents = state.get(
        "retrieved_documents",
        []
    )

    allowed_pages = sorted({
        int(document["page_number"])
        for document in documents
    })

    citations = [
        int(value)
        for value in re.findall(
            r"\[Page\s+(\d+)\]",
            answer,
            flags=re.IGNORECASE
        )
    ]

    # Deterministic citation validation.
    citations_valid = (
        bool(citations)
        and all(page in allowed_pages for page in citations)
    )

    context = build_context(documents)

    prompt = f"""
You are a strict rulebook-answer verifier.

Determine whether the answer is supported by the supplied
rulebook passages.

QUESTION:
{state["question"]}

ANSWER:
{answer}

ALLOWED SOURCE PAGES:
{allowed_pages}

RULEBOOK PASSAGES:
{context}

CHECK:

1. Is every important factual claim about the game supported
   by the passages?
2. Does the answer introduce any unsupported game rule?
3. Are the cited pages relevant to the claims?
4. Does the answer incorrectly claim something that the
   passages do not establish?

Return only valid JSON in this exact structure:

{{
    "supported": true,
    "reason": "Brief explanation"
}}

Set supported to false if the answer contains any important
unsupported rule claim.
"""

    supported = False
    reason = "Verification could not be completed."

    try:

        response = llm.invoke(prompt)

        result = extract_json(
            get_response_text(response)
        )

        model_supported = (
            result.get("supported") is True
        )

        reason = str(
            result.get("reason", reason)
        )

        supported = (
            model_supported and citations_valid
        )

    except Exception as error:

        reason = (
            "Verification response could not be parsed: "
            + str(error)[:300]
        )

        supported = False

    retry_count = state.get("retry_count", 0)

    if not supported:
        retry_count += 1

    return {
        "verified": supported,
        "verification_feedback": reason,
        "retry_count": retry_count
    }


def route_after_verification(state):

    if state.get("verified", False):
        return "finalize"

    if state.get("retry_count", 0) <= MAX_REPAIR_ATTEMPTS:
        return "retry"

    return "finalize"


# ---------------------------------------------------------
# 8. FINALIZATION NODE
# ---------------------------------------------------------

def finalize_node(state):

    if not state.get("retrieved_documents"):

        return {
            "answer": (
                "I couldn't find a relevant rule in the uploaded "
                "rulebook. Try rephrasing the question or check "
                "whether the correct rulebook is uploaded."
            ),
            "references": [],
            "verified": False,
            "needs_clarification": False
        }

    if not state.get("verified", False):

        return {
            "answer": (
                "I found some potentially relevant rulebook "
                "passages, but I couldn't verify a reliable answer "
                "from them. I don't want to guess at the rule. "
                "Try asking a more specific question."
            ),
            "references": [],
            "verified": False,
            "needs_clarification": False
        }

    answer = state.get("candidate_answer", "")

    cited_pages = set(
        int(value)
        for value in re.findall(
            r"\[Page\s+(\d+)\]",
            answer,
            flags=re.IGNORECASE
        )
    )

    references = []
    seen = set()

    for document in state.get("retrieved_documents", []):

        page_number = int(document["page_number"])

        if page_number not in cited_pages:
            continue

        key = (
            document["filename"],
            page_number
        )

        if key in seen:
            continue

        seen.add(key)

        references.append(
            RuleReference(
                game_name=document["game_name"],
                filename=document["filename"],
                page_number=page_number,
                excerpt=document["content"][:500]
            )
        )

    return {
        "answer": answer,
        "references": references,
        "verified": True,
        "needs_clarification": False
    }


# ---------------------------------------------------------
# 9. BUILD THE LANGGRAPH WORKFLOW
# ---------------------------------------------------------

def build_agent_graph():

    workflow = StateGraph(BoardBrainState)

    workflow.add_node(
        "retrieve",
        retrieve_node
    )

    workflow.add_node(
        "generate",
        generate_node
    )

    workflow.add_node(
        "verify",
        verify_node
    )

    workflow.add_node(
        "finalize",
        finalize_node
    )

    workflow.add_edge(
        START,
        "retrieve"
    )

    workflow.add_conditional_edges(
        "retrieve",
        route_after_retrieval,
        {
            "generate": "generate",
            "finalize": "finalize"
        }
    )

    workflow.add_edge(
        "generate",
        "verify"
    )

    workflow.add_conditional_edges(
        "verify",
        route_after_verification,
        {
            "retry": "generate",
            "finalize": "finalize"
        }
    )

    workflow.add_edge(
        "finalize",
        END
    )

    return workflow.compile()


# ---------------------------------------------------------
# 10. PUBLIC FUNCTION USED BY FLASK
# ---------------------------------------------------------

def get_agent():

    global _graph

    if _graph is None:
        _graph = build_agent_graph()

    return _graph


def ask_boardbrain(
    game_id,
    game_name,
    question,
    conversation_history=None
):

    question = str(question).strip()

    if not question:
        raise ValueError("Question cannot be empty.")

    if len(question) > 5000:
        raise ValueError(
            "Question cannot exceed 5000 characters."
        )

    initial_state = {
        "game_id": game_id,
        "game_name": game_name,
        "question": question,
        "history": conversation_history or [],
        "retrieved_documents": [],
        "candidate_answer": "",
        "answer": "",
        "references": [],
        "verified": False,
        "verification_feedback": "",
        "retry_count": 0,
        "needs_clarification": False
    }

    result = get_agent().invoke(initial_state)

    return AgentResponse(
        answer=result.get("answer", ""),
        references=result.get("references", []),
        verified=result.get("verified", False),
        needs_clarification=result.get(
            "needs_clarification",
            False
        )
    )