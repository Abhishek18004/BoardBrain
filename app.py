import os
import re
import sys
import uuid
import shutil
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory
)
from werkzeug.utils import secure_filename
from pydantic import ValidationError

import database

from database import (
    initialize_database,
    get_all_games,
    get_game,
    create_game,
    save_rulebook,
    update_rulebook_status,
    get_active_rulebook,
    get_latest_rulebook,
    save_pending_upload,
    get_pending_upload,
    delete_pending_upload,
    save_note,
    get_notes,
    delete_note
)

from schemas import (
    ChatRequest,
    NoteCreate,
    ScoreRequest,
    UploadAssignmentRequest
)

from rag import create_game_index
from agent import ask_boardbrain
from tools import calculate_scores
from flask import Flask, render_template


load_dotenv()


# ---------------------------------------------------------
# 1. PATHS AND CONFIGURATION
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DOCUMENTS_DIR = BASE_DIR / "documents"
UPLOADS_DIR = BASE_DIR / "uploads"
VECTOR_DIR = BASE_DIR / "vector_db"

for directory in [
    TEMPLATES_DIR,
    STATIC_DIR,
    STATIC_DIR / "css",
    STATIC_DIR / "js",
    STATIC_DIR / "images",
    DOCUMENTS_DIR,
    UPLOADS_DIR,
    VECTOR_DIR
]:
    directory.mkdir(
        parents=True,
        exist_ok=True
    )

MAX_UPLOAD_SIZE_MB = int(
    os.getenv("MAX_UPLOAD_SIZE_MB", "30")
)

MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {"pdf"}

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
    static_url_path="/static"
)

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE

initialize_database()


# ---------------------------------------------------------
# 2. COMMON HELPERS
# ---------------------------------------------------------

def success_response(data=None, message=None, status=200):

    payload = {
        "success": True
    }

    if data is not None:
        payload["data"] = data

    if message:
        payload["message"] = message

    return jsonify(payload), status


def error_response(message, status=400):

    return jsonify({
        "success": False,
        "error": str(message)
    }), status


def validate_model(model_class, data):

    try:
        return model_class.model_validate(data), None

    except ValidationError as error:
        return None, error


def get_game_payload(game_id):

    game = get_game(game_id)

    if not game:
        return None

    latest = get_latest_rulebook(game_id)
    active = get_active_rulebook(game_id)

    game["rulebook_status"] = (
        latest["status"] if latest else None
    )

    game["has_rulebook"] = active is not None

    game["active_rulebook"] = active

    game["latest_rulebook"] = latest

    return game


def slugify_game_name(name):

    slug = name.strip().lower()

    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        slug
    )

    slug = slug.strip("-")

    if not slug:
        raise ValueError(
            "Please enter a valid game name."
        )

    return slug[:80]


def get_unique_game_id(name):

    base_id = slugify_game_name(name)

    existing = get_all_games()

    existing_ids = {
        game["id"]
        for game in existing
    }

    # Reuse a custom game with the same name.
    for game in existing:

        if game["name"].strip().lower() == name.strip().lower():
            return game["id"], False

    candidate = base_id
    counter = 2

    while candidate in existing_ids:

        candidate = f"{base_id}-{counter}"
        counter += 1

    return candidate, True


def is_allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# ---------------------------------------------------------
# 3. GENERAL ROUTES
# ---------------------------------------------------------

@app.route("/", methods=["GET"])
def home():

    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():

    return success_response({
        "status": "online",
        "application": "BoardBrain"
    })


# ---------------------------------------------------------
# 4. GAME LIBRARY
# ---------------------------------------------------------

@app.route("/api/games", methods=["GET"])
def games_route():

    games = get_all_games()

    results = [
        get_game_payload(game["id"])
        for game in games
    ]

    return success_response(results)


@app.route("/api/games/<game_id>", methods=["GET"])
def game_details_route(game_id):

    game = get_game_payload(game_id)

    if not game:
        return error_response(
            "Game not found.",
            404
        )

    return success_response(game)


# ---------------------------------------------------------
# 5. UPLOAD PDF
# ---------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def upload_route():

    uploaded_file = request.files.get("file")

    if uploaded_file is None:
        return error_response(
            "Please select a PDF file."
        )

    original_filename = uploaded_file.filename or ""

    if not original_filename.strip():
        return error_response(
            "Please select a file."
        )

    if not is_allowed_file(original_filename):
        return error_response(
            "Only PDF files are supported."
        )

    # Check the file signature instead of relying only on extension.
    header = uploaded_file.stream.read(5)
    uploaded_file.stream.seek(0)

    if header != b"%PDF-":
        return error_response(
            "The selected file does not appear to be a valid PDF."
        )

    safe_original_name = (
        secure_filename(original_filename)
        or "rulebook.pdf"
    )

    token = uuid.uuid4().hex

    stored_filename = f"{token}.pdf"

    temporary_path = UPLOADS_DIR / stored_filename

    try:

        uploaded_file.save(str(temporary_path))

        if (
            temporary_path.stat().st_size > MAX_UPLOAD_SIZE
        ):
            temporary_path.unlink(missing_ok=True)

            return error_response(
                f"File exceeds the {MAX_UPLOAD_SIZE_MB} MB upload limit.",
                413
            )

        save_pending_upload(
            token=token,
            filename=stored_filename,
            original_filename=safe_original_name
        )

    except Exception as error:

        temporary_path.unlink(missing_ok=True)

        return error_response(
            f"Could not save the uploaded file: {error}",
            500
        )

    return success_response(
        data={
            "upload_token": token,
            "original_filename": safe_original_name
        },
        message="PDF uploaded. Select its game to continue.",
        status=201
    )


# ---------------------------------------------------------
# 6. ASSIGN PDF TO A GAME AND INDEX IT
# ---------------------------------------------------------

@app.route("/api/assign-game", methods=["POST"])
def assign_game_route():

    data = request.get_json(silent=True) or {}

    validated, validation_error = validate_model(
        UploadAssignmentRequest,
        data
    )

    if validation_error:
        return error_response(
            str(validation_error),
            400
        )

    pending = get_pending_upload(
        validated.upload_token
    )

    if not pending:
        return error_response(
            "Upload not found or it has already been assigned.",
            404
        )

    temporary_path = (
        UPLOADS_DIR / pending["filename"]
    )

    if not temporary_path.exists():
        return error_response(
            "Uploaded PDF could not be found. Please upload it again.",
            404
        )

    # Resolve the selected game.
    if validated.custom_game_name:

        custom_name = validated.custom_game_name.strip()

        if not custom_name:
            return error_response(
                "Please enter a custom game name."
            )

        game_id, should_create = get_unique_game_id(
            custom_name
        )

        if should_create:

            try:
                create_game(
                    game_id,
                    custom_name
                )
            except Exception as error:
                return error_response(
                    f"Could not create the game: {error}",
                    500
                )

    else:

        game_id = validated.game_id

        selected_game = get_game(game_id)

        if not selected_game:
            return error_response(
                "Selected game does not exist.",
                404
            )

    game = get_game(game_id)

    if not game:
        return error_response(
            "Could not resolve the selected game.",
            500
        )

    # Store a unique filename so uploads never overwrite PDFs accidentally.
    final_filename = (
        f"{game_id}_{uuid.uuid4().hex}.pdf"
    )

    final_path = DOCUMENTS_DIR / final_filename

    try:

        shutil.copy2(
            str(temporary_path),
            str(final_path)
        )
    except Exception as error:

        return error_response(
            f"Could not move the uploaded PDF: {error}",
            500
        )

    rulebook_id = save_rulebook(
        game_id=game_id,
        filename=final_filename,
        original_filename=pending["original_filename"],
        status="processing"
    )

    try:

        result = create_game_index(
            pdf_path=final_path,
            game_id=game_id,
            game_name=game["name"]
        )

        update_rulebook_status(
            rulebook_id=rulebook_id,
            status="ready",
            page_count=result["total_pages"],
            index_path=result["index_path"]
        )

        temporary_path.unlink(missing_ok=True)

        delete_pending_upload(
            validated.upload_token
        )

        return success_response(
            data={
                "game": get_game_payload(game_id),
                "index": {
                    "total_pages": result["total_pages"],
                    "total_chunks": result["total_chunks"],
                    "index_path": result["index_path"]
                }
            },
            message="Rulebook processed successfully."
        )

    except Exception as error:

        update_rulebook_status(
            rulebook_id=rulebook_id,
            status="failed"
        )

        app.logger.exception(
            "Rulebook indexing failed for %s",
            game_id
        )

        return error_response(
            f"Rulebook processing failed: {error}",
            500
        )


# ---------------------------------------------------------
# 7. RULEBOOK PDF VIEWER
# ---------------------------------------------------------

@app.route(
    "/api/rulebooks/<game_id>/file",
    methods=["GET"]
)
def rulebook_file_route(game_id):

    game = get_game(game_id)

    if not game:
        return error_response(
            "Game not found.",
            404
        )

    active = get_active_rulebook(game_id)

    if not active:
        return error_response(
            "No successfully indexed rulebook is available.",
            404
        )

    filename = active["filename"]

    pdf_path = DOCUMENTS_DIR / filename

    if not pdf_path.exists():
        return error_response(
            "Rulebook PDF file is missing.",
            404
        )

    return send_from_directory(
        DOCUMENTS_DIR,
        filename,
        mimetype="application/pdf",
        as_attachment=False
    )


# ---------------------------------------------------------
# 8. CHAT ENDPOINT
# ---------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
def chat_route():

    data = request.get_json(silent=True) or {}

    validated, validation_error = validate_model(
        ChatRequest,
        data
    )

    if validation_error:
        return error_response(
            str(validation_error),
            400
        )

    game = get_game(validated.game_id)

    if not game:
        return error_response(
            "Game not found.",
            404
        )

    active_rulebook = get_active_rulebook(
        validated.game_id
    )

    if not active_rulebook:
        return error_response(
            "This game does not have a ready rulebook. Upload and process one first.",
            409
        )

    history = [
        message.model_dump()
        for message in validated.conversation_history
    ]

    try:

        response = ask_boardbrain(
            game_id=validated.game_id,
            game_name=game["name"],
            question=validated.question,
            conversation_history=history
        )

        return success_response(
            response.model_dump()
        )

    except Exception as error:

        app.logger.exception(
            "Chat request failed for %s",
            validated.game_id
        )

        return error_response(
            f"Could not generate an answer: {error}",
            502
        )


# ---------------------------------------------------------
# 9. NOTES
# ---------------------------------------------------------

@app.route("/api/notes", methods=["GET"])
def get_notes_route():

    game_id = request.args.get("game_id", "").strip()

    if not game_id:
        return error_response(
            "game_id is required."
        )

    if not get_game(game_id):
        return error_response(
            "Game not found.",
            404
        )

    return success_response(
        get_notes(game_id)
    )


@app.route("/api/notes", methods=["POST"])
def create_note_route():

    data = request.get_json(silent=True) or {}

    validated, validation_error = validate_model(
        NoteCreate,
        data
    )

    if validation_error:
        return error_response(
            str(validation_error),
            400
        )

    if not get_game(validated.game_id):
        return error_response(
            "Game not found.",
            404
        )

    try:

        note_id = save_note(
            validated.game_id,
            validated.content
        )

        return success_response(
            {
                "id": note_id,
                "game_id": validated.game_id,
                "content": validated.content
            },
            message="Note saved.",
            status=201
        )

    except Exception as error:

        return error_response(
            str(error),
            400
        )


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note_route(note_id):

    data = request.get_json(silent=True) or {}

    game_id = str(
        data.get("game_id", "")
    ).strip()

    if not game_id:
        return error_response(
            "game_id is required."
        )

    deleted = delete_note(
        note_id,
        game_id
    )

    if not deleted:
        return error_response(
            "Note not found.",
            404
        )

    return success_response(
        message="Note deleted."
    )


# ---------------------------------------------------------
# 10. SCORE CALCULATOR
# ---------------------------------------------------------

@app.route("/api/tools/score", methods=["POST"])
def score_route():

    data = request.get_json(silent=True) or {}

    validated, validation_error = validate_model(
        ScoreRequest,
        data
    )

    if validation_error:
        return error_response(
            str(validation_error),
            400
        )

    try:

        result = calculate_scores(
            validated.scores
        )

        return success_response(result)

    except ValueError as error:

        return error_response(
            str(error),
            400
        )


# ---------------------------------------------------------
# 11. DEFAULT RULEBOOK INDEXING
# ---------------------------------------------------------

DEFAULT_PDF_FILES = {
    "catan": "catan_rules.pdf",
    "uno": "uno_rules.pdf",
    "monopoly": "monopoly_rules.pdf"
}


def index_default_rulebooks(force=False):

    initialize_database()

    for game_id, filename in DEFAULT_PDF_FILES.items():

        game = get_game(game_id)

        pdf_path = DOCUMENTS_DIR / filename

        print("\n" + "=" * 65)
        print(f"GAME: {game['name']}")
        print("=" * 65)

        if not pdf_path.exists():

            print(f"SKIPPED: PDF not found: {pdf_path}")
            continue

        active = get_active_rulebook(game_id)

        index_path = VECTOR_DIR / game_id

        index_exists = (
            index_path / "index.faiss"
        ).exists()

        if active and index_exists and not force:

            print("SKIPPED: A ready index already exists.")
            continue

        rulebook_id = save_rulebook(
            game_id=game_id,
            filename=filename,
            original_filename=filename,
            status="processing"
        )

        try:

            result = create_game_index(
                pdf_path=pdf_path,
                game_id=game_id,
                game_name=game["name"]
            )

            update_rulebook_status(
                rulebook_id=rulebook_id,
                status="ready",
                page_count=result["total_pages"],
                index_path=result["index_path"]
            )

            print("STATUS: READY")
            print("Pages:", result["total_pages"])
            print("Chunks:", result["total_chunks"])
            print("Index:", result["index_path"])

        except Exception as error:

            update_rulebook_status(
                rulebook_id,
                status="failed"
            )

            print("STATUS: FAILED")
            print("ERROR:", error)


# ---------------------------------------------------------
# 12. FLASK ERROR HANDLERS
# ---------------------------------------------------------

@app.errorhandler(413)
def file_too_large(error):

    return error_response(
        f"Upload exceeds the {MAX_UPLOAD_SIZE_MB} MB limit.",
        413
    )


@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):
        return error_response(
            "API endpoint not found.",
            404
        )

    return error_response(
        "Page not found.",
        404
    )


# ---------------------------------------------------------
# 13. RUN
# ---------------------------------------------------------

if __name__ == "__main__":

    if "--index-defaults" in sys.argv:

        force = "--force" in sys.argv

        index_default_rulebooks(
            force=force
        )

    else:

        debug = (
            os.getenv("FLASK_DEBUG", "False").lower()
            == "true"
        )

        app.run(
            host="127.0.0.1",
            port=5000,
            debug=debug
        )