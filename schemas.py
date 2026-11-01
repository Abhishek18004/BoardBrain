from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator


class GameCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=5000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=5000)

    conversation_history: list[ChatMessage] = Field(
        default_factory=list,
        max_length=20
    )


class UploadAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_token: str = Field(
        pattern=r"^[a-f0-9]{32}$"
    )

    game_id: Optional[str] = None

    custom_game_name: Optional[str] = Field(
        default=None,
        max_length=100
    )

    @model_validator(mode="after")
    def validate_game_selection(self):

        has_existing_game = bool(self.game_id)
        has_custom_game = bool(
            self.custom_game_name
            and self.custom_game_name.strip()
        )

        if has_existing_game == has_custom_game:
            raise ValueError(
                "Select an existing game or provide a custom game name."
            )

        if has_existing_game and self.game_id == "__custom__":
            raise ValueError(
                "Provide a custom game name instead of __custom__."
            )

        return self


class RuleReference(BaseModel):
    game_name: str
    filename: str
    page_number: int = Field(ge=1)
    excerpt: str


class AgentResponse(BaseModel):
    answer: str

    references: list[RuleReference] = Field(
        default_factory=list
    )

    verified: bool = False

    needs_clarification: bool = False


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=5000)


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores: dict[str, dict[str, object]]

    @model_validator(mode="after")
    def check_players(self):

        if not self.scores:
            raise ValueError("At least one player is required.")

        if len(self.scores) > 20:
            raise ValueError("Maximum 20 players are supported.")

        return self