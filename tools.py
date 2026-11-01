import math


def calculate_scores(scores):

    if not isinstance(scores, dict) or not scores:
        raise ValueError("At least one player is required.")

    results = []

    for player, categories in scores.items():

        player = str(player).strip()

        if not player:
            raise ValueError("Player name cannot be empty.")

        if not isinstance(categories, dict):
            raise ValueError(
                f"Scores for {player} must be a dictionary."
            )

        total = 0.0

        for category, value in categories.items():

            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Invalid score for {player}: {category}"
                )

            if not math.isfinite(numeric_value):
                raise ValueError(
                    f"Score for {player} must be a finite number."
                )

            total += numeric_value

        results.append({
            "player": player,
            "total": total,
            "categories": categories
        })

    results.sort(
        key=lambda item: item["total"],
        reverse=True
    )

    highest_score = results[0]["total"]

    winners = [
        item["player"]
        for item in results
        if item["total"] == highest_score
    ]

    return {
        "results": results,
        "winners": winners,
        "highest_score": highest_score
    }


def validate_numeric_rule(value, minimum=None, maximum=None):

    try:
        value = float(value)
    except (TypeError, ValueError):
        return {
            "valid": False,
            "reason": "Value must be numeric."
        }

    if not math.isfinite(value):
        return {
            "valid": False,
            "reason": "Value must be finite."
        }

    if minimum is not None and value < minimum:
        return {
            "valid": False,
            "reason": f"Value must be at least {minimum}."
        }

    if maximum is not None and value > maximum:
        return {
            "valid": False,
            "reason": f"Value cannot exceed {maximum}."
        }

    return {
        "valid": True,
        "reason": "Value is within the specified limits."
    }