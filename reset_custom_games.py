import sqlite3
import shutil
from pathlib import Path


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "boardbrain.db"
DOCUMENTS_DIR = BASE_DIR / "documents"
VECTOR_DIR = BASE_DIR / "vector_db"

DEFAULT_GAME_IDS = {
    "catan",
    "uno",
    "monopoly"
}


# =========================================================
# SAFE FILE DELETION
# =========================================================

def remove_index_folder(game_id, stored_index_path=None):

    if stored_index_path:

        index_path = Path(stored_index_path)

        if not index_path.is_absolute():
            index_path = BASE_DIR / index_path

    else:
        index_path = VECTOR_DIR / game_id

    try:

        resolved_path = index_path.resolve()
        resolved_root = VECTOR_DIR.resolve()

        # Only delete folders inside vector_db.
        resolved_path.relative_to(resolved_root)

        if resolved_path.exists():

            shutil.rmtree(resolved_path)

            print(f"Deleted FAISS index: {resolved_path}")

    except ValueError:

        print(
            f"Skipped unsafe index path for game: {game_id}"
        )


def remove_game_pdf(filename):

    if not filename:
        return

    # Only permit a filename, not an arbitrary path.
    safe_filename = Path(filename).name

    pdf_path = DOCUMENTS_DIR / safe_filename

    try:

        resolved_path = pdf_path.resolve()

        resolved_path.relative_to(
            DOCUMENTS_DIR.resolve()
        )

        if resolved_path.is_file():

            resolved_path.unlink()

            print(f"Deleted PDF: {safe_filename}")

    except ValueError:

        print(f"Skipped unsafe PDF path: {filename}")


# =========================================================
# RESET CUSTOM GAMES
# =========================================================

def reset_custom_games():

    if not DB_PATH.exists():

        print("Database not found.")
        return


    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    try:

        # Find all custom games.
        custom_games = conn.execute("""
            SELECT id, name
            FROM games
            WHERE is_default = 0
        """).fetchall()


        if not custom_games:

            print("No custom games found.")

            return


        print("\nCUSTOM GAMES TO REMOVE")
        print("=" * 50)


        for game in custom_games:

            print(
                f"{game['name']} ({game['id']})"
            )


        for game in custom_games:

            game_id = game["id"]

            print("\n" + "-" * 50)
            print(f"Removing: {game['name']}")


            # Get all rulebooks belonging to this game.
            rulebooks = conn.execute("""
                SELECT filename, index_path
                FROM rulebooks
                WHERE game_id = ?
            """, (game_id,)).fetchall()


            # Delete associated notes.
            conn.execute("""
                DELETE FROM notes
                WHERE game_id = ?
            """, (game_id,))


            # Delete associated rulebook records.
            conn.execute("""
                DELETE FROM rulebooks
                WHERE game_id = ?
            """, (game_id,))


            # Delete the game itself.
            conn.execute("""
                DELETE FROM games
                WHERE id = ?
                AND is_default = 0
            """, (game_id,))


            # Remove the corresponding PDF and FAISS index.
            for rulebook in rulebooks:

                remove_game_pdf(
                    rulebook["filename"]
                )

                remove_index_folder(
                    game_id,
                    rulebook["index_path"]
                )


            # Also remove the default game-ID index folder
            # if the rulebook record did not contain an index path.
            if not rulebooks:

                remove_index_folder(game_id)


        conn.commit()


        # Display the remaining games.
        remaining_games = conn.execute("""
            SELECT id, name, is_default
            FROM games
            ORDER BY is_default DESC, name ASC
        """).fetchall()


        print("\n" + "=" * 50)
        print("RESET COMPLETED")
        print("=" * 50)

        print("\nREMAINING GAMES:")

        for game in remaining_games:

            print(
                f"- {game['name']} ({game['id']})"
            )


        print(
            f"\nTotal games remaining: {len(remaining_games)}"
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


if __name__ == "__main__":

    reset_custom_games()