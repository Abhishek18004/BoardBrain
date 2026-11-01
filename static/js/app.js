"use strict";

/* =========================================================
   1. CONFIGURATION AND STATE
========================================================= */

const API_BASE = "/api";

const DEFAULT_GAME_PRESENTATION = {
    catan: {
        symbol: "C",
        type: "STRATEGY · SETTLEMENT",
        description: "Trade resources. Build roads. Settle the island."
    },

    uno: {
        symbol: "U",
        type: "CARD · FAMILY",
        description: "Match colors and numbers. Be the first to empty your hand."
    },

    monopoly: {
        symbol: "M",
        type: "PROPERTY · ECONOMY",
        description: "Buy properties, collect rent and build your empire."
    }
};

const state = {
    games: [],
    activeGame: null,

    selectedFile: null,
    uploadToken: null,

    currentDrawer: null,

    conversations: {},
    latestReferences: []
};


const $ = (selector) => document.querySelector(selector);

const $$ = (selector) => Array.from(
    document.querySelectorAll(selector)
);


/* =========================================================
   2. DOM REFERENCES
========================================================= */

const libraryView = $("#libraryView");
const workspaceView = $("#workspaceView");

const gamesGrid = $("#gamesGrid");
const gameCount = $("#gameCount");
const libraryError = $("#libraryError");

const uploadModal = $("#uploadModal");

const uploadStep1 = $("#uploadStep1");
const uploadStep2 = $("#uploadStep2");
const uploadProcessing = $("#uploadProcessing");

const rulebookFile = $("#rulebookFile");

const selectedFile = $("#selectedFile");
const selectedFileName = $("#selectedFileName");
const selectedFileSize = $("#selectedFileSize");

const gameSelection = $("#gameSelection");
const customGameField = $("#customGameField");
const customGameName = $("#customGameName");

const chatMessages = $("#chatMessages");
const chatInput = $("#chatInput");
const chatForm = $("#chatForm");
const chatUploadWarning = $("#chatUploadWarning");

const toolDrawer = $("#toolDrawer");
const drawerBackdrop = $("#drawerBackdrop");

const rulebookFrame = $("#rulebookFrame");


/* =========================================================
   3. GENERAL HELPERS
========================================================= */

function escapeHTML(value) {

    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function formatFileSize(bytes) {

    if (!Number.isFinite(bytes)) {
        return "";
    }

    if (bytes < 1024) {
        return `${bytes} B`;
    }

    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}


function formatDate(value) {

    if (!value) {
        return "";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "";
    }

    return date.toLocaleString();
}


function showElement(element) {
    element.hidden = false;
}


function hideElement(element) {
    element.hidden = true;
}


function showError(element, message) {

    element.textContent = message;
    showElement(element);
}


function hideError(element) {

    element.textContent = "";
    hideElement(element);
}


async function apiRequest(path, options = {}) {

    const response = await fetch(
        `${API_BASE}${path}`,
        options
    );

    let payload;

    try {
        payload = await response.json();
    } catch {
        throw new Error(
            `Server returned an invalid response (${response.status}).`
        );
    }

    if (!response.ok || payload.success === false) {

        throw new Error(
            payload.error || `Request failed (${response.status}).`
        );
    }

    return payload.data;
}


function jsonOptions(data, method = "POST") {

    return {
        method,
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(data)
    };
}


/* =========================================================
   4. GAME LIBRARY
========================================================= */

function getGamePresentation(game) {

    return DEFAULT_GAME_PRESENTATION[game.id] || {
        symbol: (game.name || "?").charAt(0).toUpperCase(),
        type: "CUSTOM GAME",
        description: "Your own game workspace and rulebook."
    };
}


function getStatusDetails(game) {

    const status = game.rulebook_status;

    if (status === "ready") {
        return {
            label: "READY",
            className: "ready"
        };
    }

    if (status === "processing") {
        return {
            label: "PROCESSING",
            className: "processing"
        };
    }

    if (status === "failed") {
        return {
            label: "FAILED",
            className: "failed"
        };
    }

    return {
        label: "NO RULEBOOK",
        className: ""
    };
}


function renderGames(games) {

    state.games = games;

    gamesGrid.innerHTML = "";

    gameCount.textContent = String(
        games.length
    ).padStart(2, "0");

    if (!games.length) {

        gamesGrid.innerHTML = `
            <div class="loading-card">
                NO GAMES FOUND.
            </div>
        `;

        return;
    }


    games.forEach((game) => {

        const presentation = getGamePresentation(game);
        const status = getStatusDetails(game);

        const card = document.createElement("button");

        card.type = "button";
        card.className = "game-card";

        card.dataset.gameId = game.id;

        card.innerHTML = `
            <div>
                <div class="game-card-top">

                    <div class="game-card-symbol">
                        ${escapeHTML(presentation.symbol)}
                    </div>

                    <span class="game-card-type">
                        ${escapeHTML(presentation.type)}
                    </span>

                </div>

                <h3>${escapeHTML(game.name)}</h3>

                <p class="game-card-description">
                    ${escapeHTML(presentation.description)}
                </p>
            </div>

            <div class="game-card-bottom">

                <span class="game-status ${status.className}">
                    ${escapeHTML(status.label)}
                </span>

                <span class="open-game-label">
                    OPEN SPACE ↗
                </span>

            </div>
        `;

        gamesGrid.appendChild(card);
    });


    const addCard = document.createElement("button");

    addCard.type = "button";
    addCard.className = "game-card custom-game-card";
    addCard.dataset.action = "add-game";

    addCard.innerHTML = `
        <div class="custom-game-content">

            <span class="custom-game-plus">＋</span>

            <strong>ADD A GAME</strong>

            <small>
                Upload a rulebook for any game.
            </small>

        </div>
    `;

    gamesGrid.appendChild(addCard);
}


async function loadGames() {

    hideError(libraryError);

    try {

        const games = await apiRequest("/games");

        renderGames(games);

    } catch (error) {

        showError(
            libraryError,
            `Could not load the game library: ${error.message}`
        );

        // Show the three default game cards as a fallback.
        // Opening a game still requires the Flask backend.
        if (!state.games.length) {

            renderGames([
                {
                    id: "catan",
                    name: "Catan",
                    rulebook_status: null
                },
                {
                    id: "uno",
                    name: "UNO",
                    rulebook_status: null
                },
                {
                    id: "monopoly",
                    name: "Monopoly",
                    rulebook_status: null
                }
            ]);
        }
    }
}


/* =========================================================
   5. WORKSPACE
========================================================= */

function getConversation(gameId) {

    if (!state.conversations[gameId]) {

        const storageKey = `boardbrain_chat_${gameId}`;

        try {

            const stored = sessionStorage.getItem(storageKey);

            state.conversations[gameId] = stored
                ? JSON.parse(stored)
                : [];

        } catch {

            state.conversations[gameId] = [];
        }
    }

    return state.conversations[gameId];
}


function saveConversation(gameId) {

    const storageKey = `boardbrain_chat_${gameId}`;

    try {

        sessionStorage.setItem(
            storageKey,
            JSON.stringify(
                state.conversations[gameId] || []
            )
        );

    } catch (error) {

        console.warn(
            "Could not save chat history:",
            error
        );
    }
}


async function openWorkspace(gameId) {

    try {

        const game = await apiRequest(
            `/games/${encodeURIComponent(gameId)}`
        );

        state.activeGame = game;

        hideElement(libraryView);
        showElement(workspaceView);

        renderWorkspaceDetails(game);

        renderConversation(gameId);

        renderReferences([]);

        await loadGameNotes();

        window.scrollTo({
            top: 0,
            behavior: "instant"
        });

    } catch (error) {

        alert(
            `Could not open this game: ${error.message}`
        );
    }
}


function renderWorkspaceDetails(game) {

    const presentation = getGamePresentation(game);

    const active = game.active_rulebook;
    const latest = game.latest_rulebook;

    $("#workspaceGameName").textContent =
        game.name.toUpperCase();

    $("#workspaceGameInitial").textContent =
        presentation.symbol;

    $("#sidebarGameName").textContent =
        game.name.toUpperCase();


    const statusElement = $("#workspaceStatus");

    const status = getStatusDetails(game);

    statusElement.className = `status-pill ${status.className}`;

    statusElement.innerHTML = `
        <span class="status-dot"></span>
        ${escapeHTML(status.label)}
    `;


    $("#sidebarRulebookStatus").textContent = active
        ? "READY"
        : (latest?.status || "NOT UPLOADED").toUpperCase();


    $("#sidebarPageCount").textContent = active
        ? String(active.page_count)
        : "—";


    $("#sidebarIndexStatus").textContent = active
        ? "READY"
        : "INACTIVE";


    const composerArea = document.querySelector(
        ".chat-composer-area"
    );

    if (active) {

        composerArea.classList.remove("disabled");

        chatInput.disabled = false;

        chatInput.placeholder =
            "Ask BoardBrain anything about the game...";

        $("#sendButton").disabled = false;

    } else {

        composerArea.classList.add("disabled");

        chatInput.disabled = true;

        chatInput.placeholder =
            "Upload a rulebook to activate the assistant.";

        $("#sendButton").disabled = true;
    }


    $("#openRulebookButton").disabled = !active;

    if (active) {

        $("#viewerFilename").textContent =
            active.original_filename || active.filename;

        $("#viewerPageInfo").textContent =
            `${active.page_count} PAGES · ORIGINAL PDF`;

    } else {

        $("#viewerFilename").textContent =
            "NO RULEBOOK UPLOADED";

        $("#viewerPageInfo").textContent =
            "UPLOAD A PDF TO VIEW IT";
    }
}


/* =========================================================
   6. CHAT RENDERING
========================================================= */

function renderWelcomeMessage() {

    return `
        <div class="welcome-message">

            <div class="welcome-mark">
                B<span>0</span>
            </div>

            <div class="welcome-eyebrow">
                YOUR TABLESIDE COMPANION
            </div>

            <h3>Ready when you are.</h3>

            <p>
                Ask me about game rules, special situations,
                turn order or strategy. I'll use the uploaded
                rulebook whenever possible.
            </p>

            <div class="suggestion-list">

                <button
                    class="suggestion-chip"
                    type="button"
                    data-question="How do I set up this game?"
                >
                    HOW DO I SET UP?
                </button>

                <button
                    class="suggestion-chip"
                    type="button"
                    data-question="Explain the turn sequence."
                >
                    EXPLAIN THE TURN
                </button>

                <button
                    class="suggestion-chip"
                    type="button"
                    data-question="What are the special rules?"
                >
                    SPECIAL RULES
                </button>

            </div>

        </div>
    `;
}


function renderAssistantContent(content) {

    // Escape the original AI response first.
    let html = escapeHTML(String(content || ""));

    // Normalize line endings and convert them BEFORE
    // inserting any HTML elements.
    html = html
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
        .replace(/\n/g, "<br>");

    // Convert Markdown bold formatting.
    html = html.replace(
        /\*\*(.*?)\*\*/g,
        "<strong>$1</strong>"
    );

    // Convert page citations into clickable buttons.
    // IMPORTANT: Do not run newline replacement after this.
    html = html.replace(
        /\[Page\s+(\d+)\]/gi,
        (match, page) => {

            return (
                `<button type="button" ` +
                `class="page-citation" ` +
                `data-open-page="${Number(page)}">` +
                `Page ${Number(page)}` +
                `</button>`
            );
        }
    );

    return html;
}

function createMessageElement(message) {

    const wrapper = document.createElement("div");

    const isUser = message.role === "user";

    wrapper.className = (
        `chat-message ${isUser ? "user" : "assistant"}`
    );

    const label = isUser
        ? "YOU"
        : "BOARDBRAIN";

    const content = isUser
        ? escapeHTML(message.content).replace(/\n/g, "<br>")
        : renderAssistantContent(message.content);

    wrapper.innerHTML = `
        <div class="message-role">${label}</div>

        <div class="message-bubble">
            ${content}
        </div>

        <div class="message-meta">
            ${formatDate(message.created_at)}
        </div>
    `;

    return wrapper;
}


function renderConversation(gameId) {

    const conversation = getConversation(gameId);

    chatMessages.innerHTML = "";

    if (!conversation.length) {

        chatMessages.innerHTML =
            renderWelcomeMessage();

        return;
    }

    conversation.forEach((message) => {

        chatMessages.appendChild(
            createMessageElement(message)
        );
    });

    chatMessages.scrollTop = chatMessages.scrollHeight;
}


function appendMessage(role, content, gameId) {

    const message = {
        role,
        content,
        created_at: new Date().toISOString()
    };

    const conversation = getConversation(gameId);

    conversation.push(message);

    saveConversation(gameId);

    if (state.activeGame?.id === gameId) {

        if (conversation.length === 1) {
            chatMessages.innerHTML = "";
        }

        chatMessages.appendChild(
            createMessageElement(message)
        );

        chatMessages.scrollTop =
            chatMessages.scrollHeight;
    }

    return message;
}


function showTypingIndicator() {

    const indicator = document.createElement("div");

    indicator.className = "chat-message assistant";
    indicator.id = "typingIndicator";

    indicator.innerHTML = `
        <div class="message-role">BOARDBRAIN</div>

        <div class="message-bubble">

            <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </div>

        </div>
    `;

    chatMessages.appendChild(indicator);

    chatMessages.scrollTop = chatMessages.scrollHeight;
}


function removeTypingIndicator() {

    $("#typingIndicator")?.remove();
}


/* =========================================================
   7. SEND CHAT MESSAGE
========================================================= */

async function sendChatMessage(question) {

    if (!state.activeGame) {
        return;
    }

    const game = state.activeGame;

    if (!game.has_rulebook) {

        alert(
            "Upload and process a rulebook before asking questions."
        );

        return;
    }

    question = String(question).trim();

    if (!question) {
        return;
    }

    const previousHistory = [
        ...getConversation(game.id)
    ];

    appendMessage(
        "user",
        question,
        game.id
    );

    chatInput.value = "";
    chatInput.style.height = "auto";

    $("#sendButton").disabled = true;

    showTypingIndicator();

    try {

        const response = await apiRequest(
            "/chat",
            jsonOptions({
                game_id: game.id,
                question,
                conversation_history: previousHistory
            })
        );

        removeTypingIndicator();

        appendMessage(
            "assistant",
            response.answer,
            game.id
        );

        renderReferences(
            response.references || []
        );

    } catch (error) {

        removeTypingIndicator();

        appendMessage(
            "assistant",
            `I couldn't complete that request: ${error.message}`,
            game.id
        );

        renderReferences([]);

    } finally {

        $("#sendButton").disabled = false;

        chatInput.focus();
    }
}


/* =========================================================
   8. REFERENCES PANEL
========================================================= */

function renderReferences(references) {

    state.latestReferences = references;

    const container = $("#referencesList");

    const count = $("#referenceCount");

    container.innerHTML = "";

    count.textContent = String(
        references.length
    ).padStart(2, "0");


    if (!references.length) {

        container.innerHTML = `
            <div class="empty-references">

                <span>▤</span>

                <p>
                    No references available for the latest answer.
                    Ask another question to retrieve rulebook passages.
                </p>

            </div>
        `;

        return;
    }


    references.forEach((reference) => {

        const card = document.createElement("div");

        card.className = "reference-card";

        card.innerHTML = `
            <div class="reference-card-top">

                <strong class="reference-card-title">
                    ${escapeHTML(reference.game_name)}
                </strong>

                <span class="reference-page">
                    P. ${Number(reference.page_number)}
                </span>

            </div>

            <p class="reference-excerpt">
                ${escapeHTML(reference.excerpt)}
            </p>

            <button
                type="button"
                class="reference-open"
                data-open-page="${Number(reference.page_number)}"
            >
                OPEN PAGE ↗
            </button>
        `;

        container.appendChild(card);
    });
}


/* =========================================================
   9. DRAWER MANAGEMENT
========================================================= */

function openDrawer(panelName, pageNumber = 1) {

    if (!state.activeGame) {
        return;
    }

    const panels = {
        rulebook: $("#rulebookDrawerPanel"),
        notes: $("#notesDrawerPanel"),
        score: $("#scoreDrawerPanel")
    };

    const titles = {
        rulebook: "RULEBOOK VIEWER",
        notes: "MY GAME NOTES",
        score: "SCORE CALCULATOR"
    };


    if (!panels[panelName]) {
        return;
    }

    Object.values(panels).forEach((panel) => {
        hideElement(panel);
    });

    showElement(panels[panelName]);

    $("#drawerTitle").textContent =
        titles[panelName];

    state.currentDrawer = panelName;

    showElement(drawerBackdrop);
    showElement(toolDrawer);


    if (panelName === "rulebook") {

        const active = state.activeGame.active_rulebook;

        if (!active) {

            alert(
                "There is no ready rulebook for this game."
            );

            closeDrawer();

            return;
        }

        const page = Math.max(
            1,
            Number(pageNumber) || 1
        );

        $("#viewerFilename").textContent =
            active.original_filename || active.filename;

        $("#viewerPageInfo").textContent =
            `PAGE ${page} OF ${active.page_count}`;

        const pdfURL = (
            `/api/rulebooks/${encodeURIComponent(state.activeGame.id)}/file`
            + `#page=${page}`
        );

        rulebookFrame.src = pdfURL;
    }


    if (panelName === "notes") {
        loadGameNotes();
    }
}


function closeDrawer() {

    hideElement(toolDrawer);
    hideElement(drawerBackdrop);

    state.currentDrawer = null;

    // Do not remove or recreate the workspace/chat.
}


function openRulebookPage(pageNumber = 1) {

    openDrawer(
        "rulebook",
        pageNumber
    );
}


/* =========================================================
   10. NOTES
========================================================= */

async function loadGameNotes() {

    if (!state.activeGame) {
        return;
    }

    const container = $("#notesList");

    try {

        const notes = await apiRequest(
            `/notes?game_id=${encodeURIComponent(state.activeGame.id)}`
        );

        container.innerHTML = "";

        if (!notes.length) {

            container.innerHTML = `
                <div class="empty-notes">
                    NO NOTES SAVED YET.
                </div>
            `;

            return;
        }


        notes.forEach((note) => {

            const card = document.createElement("div");

            card.className = "note-card";

            card.innerHTML = `
                <p>${escapeHTML(note.content)}</p>

                <div class="note-card-footer">

                    <span>
                        ${escapeHTML(formatDate(note.created_at))}
                    </span>

                    <button
                        type="button"
                        class="delete-note-button"
                        data-delete-note="${Number(note.id)}"
                    >
                        DELETE
                    </button>

                </div>
            `;

            container.appendChild(card);
        });

    } catch (error) {

        container.innerHTML = `
            <div class="empty-notes">
                COULD NOT LOAD NOTES.
            </div>
        `;

        console.error(error);
    }
}


async function saveGameNote(content) {

    if (!state.activeGame) {
        return;
    }

    const confirmed = window.confirm(
        "Save this note to the current game's workspace?"
    );

    if (!confirmed) {
        return;
    }

    try {

        await apiRequest(
            "/notes",
            jsonOptions({
                game_id: state.activeGame.id,
                content
            })
        );

        $("#noteInput").value = "";

        await loadGameNotes();

    } catch (error) {

        alert(
            `Could not save note: ${error.message}`
        );
    }
}


async function removeGameNote(noteId) {

    if (!state.activeGame) {
        return;
    }

    const confirmed = window.confirm(
        "Delete this note?"
    );

    if (!confirmed) {
        return;
    }

    try {

        await apiRequest(
            `/notes/${noteId}`,
            jsonOptions(
                {
                    game_id: state.activeGame.id
                },
                "DELETE"
            )
        );

        await loadGameNotes();

    } catch (error) {

        alert(
            `Could not delete note: ${error.message}`
        );
    }
}


/* =========================================================
   11. SCORE CALCULATOR
========================================================= */

function createScoreRow(playerName = "") {

    const row = document.createElement("div");

    row.className = "score-player-row";

    row.innerHTML = `
        <input
            class="score-player-name"
            type="text"
            placeholder="Player name"
            maxlength="50"
            value="${escapeHTML(playerName)}"
        >

        <input
            class="score-player-value"
            type="number"
            value="0"
            step="any"
        >

        <button
            class="remove-player-button"
            type="button"
            aria-label="Remove player"
        >
            ×
        </button>
    `;

    return row;
}


function addScorePlayer() {

    const container = $("#scorePlayers");

    const rows = $$(".score-player-row");

    if (rows.length >= 20) {

        alert(
            "Maximum 20 players are supported."
        );

        return;
    }

    const newRow = createScoreRow(
        `Player ${rows.length + 1}`
    );

    container.appendChild(newRow);

    updateRemovePlayerButtons();
}


function updateRemovePlayerButtons() {

    const rows = $$(".score-player-row");

    rows.forEach((row) => {

        const button = row.querySelector(
            ".remove-player-button"
        );

        button.disabled = rows.length <= 2;
    });
}


async function calculateGameScores() {

    const rows = $$(".score-player-row");

    const scores = {};

    for (const row of rows) {

        const playerName = row.querySelector(
            ".score-player-name"
        ).value.trim();

        const playerScore = Number(
            row.querySelector(
                ".score-player-value"
            ).value
        );

        if (!playerName) {

            alert(
                "Enter a name for every player."
            );

            return;
        }

        if (!Number.isFinite(playerScore)) {

            alert(
                `Enter a valid score for ${playerName}.`
            );

            return;
        }

        if (Object.hasOwn(scores, playerName)) {

            alert(
                "Player names must be unique."
            );

            return;
        }

        scores[playerName] = {
            Score: playerScore
        };
    }


    try {

        const result = await apiRequest(
            "/tools/score",
            jsonOptions({
                scores
            })
        );

        renderScoreResults(result);

    } catch (error) {

        alert(
            `Could not calculate scores: ${error.message}`
        );
    }
}


function renderScoreResults(result) {

    const container = $("#scoreResults");

    showElement(container);

    const winners = result.winners || [];

    const winnerText = winners.join(", ");

    container.innerHTML = `
        <h3>
            ${winners.length > 1 ? "TIE GAME" : "TOP SCORE"}
        </h3>

        <p class="score-winner">
            ${escapeHTML(winnerText)}
            · ${Number(result.highest_score)}
        </p>

        ${(result.results || []).map((item) => `
            <div class="score-result-row">

                <span>
                    ${escapeHTML(item.player)}
                </span>

                <strong>
                    ${Number(item.total)}
                </strong>

            </div>
        `).join("")}
    `;
}


/* =========================================================
   12. UPLOAD MODAL
========================================================= */

function openUploadModal() {

    state.selectedFile = null;
    state.uploadToken = null;

    rulebookFile.value = "";

    hideElement(selectedFile);

    $("#continueUploadButton").disabled = true;

    $("#fileDropTitle").textContent =
        "DROP YOUR PDF HERE";

    $("#fileDropSubtitle").textContent =
        "OR CLICK TO BROWSE FILES";

    hideError($("#uploadError"));
    hideError($("#assignError"));

    showUploadStep(1);

    populateGameOptions();

    showElement(uploadModal);
}


function closeUploadModal() {

    if (!uploadProcessing.hidden) {
        return;
    }

    hideElement(uploadModal);
}


function showUploadStep(step) {

    showElement(uploadStep1);
    hideElement(uploadStep2);
    hideElement(uploadProcessing);

    if (step === 2) {

        hideElement(uploadStep1);
        showElement(uploadStep2);

    }

    $("#uploadStepIndicator1").classList.toggle(
        "active",
        step === 1
    );

    $("#uploadStepIndicator2").classList.toggle(
        "active",
        step === 2
    );
}


function showProcessing() {

    hideElement(uploadStep1);
    hideElement(uploadStep2);

    showElement(uploadProcessing);
}


function populateGameOptions() {

    gameSelection.innerHTML = "";

    state.games.forEach((game) => {

        const option = document.createElement("option");

        option.value = game.id;
        option.textContent = game.name;

        gameSelection.appendChild(option);
    });


    const customOption = document.createElement("option");

    customOption.value = "__custom__";
    customOption.textContent = "My game isn't listed";

    gameSelection.appendChild(customOption);
}


function updateSelectedFile(file) {

    state.selectedFile = file;

    if (!file) {

        hideElement(selectedFile);

        $("#continueUploadButton").disabled = true;

        return;
    }


    const maxSize = 30 * 1024 * 1024;

    const isPDF = (
        file.type === "application/pdf"
        || file.name.toLowerCase().endsWith(".pdf")
    );

    if (!isPDF) {

        state.selectedFile = null;

        showError(
            $("#uploadError"),
            "Only PDF files are supported."
        );

        return;
    }


    if (file.size > maxSize) {

        state.selectedFile = null;

        showError(
            $("#uploadError"),
            "The PDF exceeds the 30 MB upload limit."
        );

        return;
    }


    hideError($("#uploadError"));

    showElement(selectedFile);

    selectedFileName.textContent = file.name;

    selectedFileSize.textContent =
        formatFileSize(file.size);

    $("#continueUploadButton").disabled = false;

    $("#fileDropTitle").textContent =
        "PDF SELECTED";

    $("#fileDropSubtitle").textContent =
        "READY TO UPLOAD";
}


async function uploadSelectedPDF() {

    const file = state.selectedFile;

    if (!file) {
        return;
    }


    const formData = new FormData();

    formData.append("file", file);


    const button = $("#continueUploadButton");

    button.disabled = true;
    button.textContent = "UPLOADING...";


    try {

        const result = await apiRequest(
            "/upload",
            {
                method: "POST",
                body: formData
            }
        );

        state.uploadToken = result.upload_token;

        $("#uploadSummaryFilename").textContent =
            result.original_filename;

        showUploadStep(2);

    } catch (error) {

        showError(
            $("#uploadError"),
            error.message
        );

    } finally {

        button.disabled = false;
        button.textContent = "CONTINUE →";
    }
}


function updateCustomGameField() {

    const isCustom = (
        gameSelection.value === "__custom__"
    );

    if (isCustom) {
        showElement(customGameField);
    } else {
        hideElement(customGameField);
    }
}


async function processUploadedRulebook() {

    if (!state.uploadToken) {

        showError(
            $("#assignError"),
            "Upload a PDF before continuing."
        );

        return;
    }


    const selectedGame = gameSelection.value;

    const payload = {
        upload_token: state.uploadToken
    };


    if (selectedGame === "__custom__") {

        const name = customGameName.value.trim();

        if (!name) {

            showError(
                $("#assignError"),
                "Enter the name of your custom game."
            );

            return;
        }

        payload.custom_game_name = name;

    } else {

        payload.game_id = selectedGame;
    }


    hideError($("#assignError"));

    showProcessing();


    try {

        const result = await apiRequest(
            "/assign-game",
            jsonOptions(payload)
        );

        const gameId = result.game.id;

        hideElement(uploadModal);

        state.uploadToken = null;
        state.selectedFile = null;

        await loadGames();

        await openWorkspace(gameId);

    } catch (error) {

        hideElement(uploadProcessing);
        showElement(uploadStep2);

        showError(
            $("#assignError"),
            error.message
        );
    }
}


/* =========================================================
   13. NAVIGATION
========================================================= */

function backToLibrary() {

    closeDrawer();

    hideElement(workspaceView);
    showElement(libraryView);

    state.activeGame = null;

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });

    loadGames();
}


/* =========================================================
   14. EVENT LISTENERS
========================================================= */

// Brand and library navigation.

$("#brandButton").addEventListener(
    "click",
    backToLibrary
);

$("#libraryNav").addEventListener(
    "click",
    backToLibrary
);

$("#backToLibraryButton").addEventListener(
    "click",
    backToLibrary
);


// Upload modal.

$("#openUploadButton").addEventListener(
    "click",
    openUploadModal
);

$("#heroUploadButton").addEventListener(
    "click",
    openUploadModal
);

$("#workspaceUploadButton").addEventListener(
    "click",
    openUploadModal
);

$("#closeUploadModal").addEventListener(
    "click",
    closeUploadModal
);

$("#cancelUploadStep1").addEventListener(
    "click",
    closeUploadModal
);

$("#continueUploadButton").addEventListener(
    "click",
    uploadSelectedPDF
);

$("#backUploadStepButton").addEventListener(
    "click",
    () => showUploadStep(1)
);

$("#processRulebookButton").addEventListener(
    "click",
    processUploadedRulebook
);

rulebookFile.addEventListener(
    "change",
    (event) => {
        updateSelectedFile(
            event.target.files[0]
        );
    }
);

gameSelection.addEventListener(
    "change",
    updateCustomGameField
);


// File drag and drop.

const dropZone = $("#fileDropZone");

dropZone.addEventListener("dragover", (event) => {

    event.preventDefault();

    dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", () => {

    dropZone.classList.remove("drag-over");
});

dropZone.addEventListener("drop", (event) => {

    event.preventDefault();

    dropZone.classList.remove("drag-over");

    const file = event.dataTransfer.files[0];

    updateSelectedFile(file);
});


// Game cards.

gamesGrid.addEventListener("click", (event) => {

    const addButton = event.target.closest(
        '[data-action="add-game"]'
    );

    if (addButton) {

        openUploadModal();

        gameSelection.value = "__custom__";

        updateCustomGameField();

        return;
    }


    const card = event.target.closest(
        "[data-game-id]"
    );

    if (card) {
        openWorkspace(card.dataset.gameId);
    }
});


// Workspace tools.

$("#openRulebookButton").addEventListener(
    "click",
    () => openDrawer("rulebook")
);

$("#openNotesButton").addEventListener(
    "click",
    () => openDrawer("notes")
);

$("#openCalculatorButton").addEventListener(
    "click",
    () => openDrawer("score")
);

$("#rightCalculatorButton").addEventListener(
    "click",
    () => openDrawer("score")
);

$("#rightNotesButton").addEventListener(
    "click",
    () => openDrawer("notes")
);

$("#closeDrawerButton").addEventListener(
    "click",
    closeDrawer
);

drawerBackdrop.addEventListener(
    "click",
    closeDrawer
);


// Chat.

chatForm.addEventListener(
    "submit",
    async (event) => {

        event.preventDefault();

        const question = chatInput.value.trim();

        if (!question) {
            return;
        }

        await sendChatMessage(question);
    }
);


chatInput.addEventListener(
    "keydown",
    (event) => {

        if (
            event.key === "Enter"
            && !event.shiftKey
        ) {

            event.preventDefault();

            chatForm.requestSubmit();
        }
    }
);


chatInput.addEventListener(
    "input",
    () => {

        chatInput.style.height = "auto";

        chatInput.style.height = Math.min(
            chatInput.scrollHeight,
            120
        ) + "px";
    }
);


// Suggested questions.

chatMessages.addEventListener(
    "click",
    (event) => {

        const suggestion = event.target.closest(
            "[data-question]"
        );

        if (suggestion) {

            chatInput.value =
                suggestion.dataset.question;

            chatForm.requestSubmit();

            return;
        }


        const citation = event.target.closest(
            "[data-open-page]"
        );

        if (citation) {

            openRulebookPage(
                Number(citation.dataset.openPage)
            );
        }
    }
);


// Notes.

$("#noteForm").addEventListener(
    "submit",
    async (event) => {

        event.preventDefault();

        const content = $("#noteInput").value.trim();

        if (!content) {
            return;
        }

        await saveGameNote(content);
    }
);


$("#notesList").addEventListener(
    "click",
    (event) => {

        const button = event.target.closest(
            "[data-delete-note]"
        );

        if (!button) {
            return;
        }

        removeGameNote(
            Number(button.dataset.deleteNote)
        );
    }
);


// Score calculator.

$("#addPlayerButton").addEventListener(
    "click",
    addScorePlayer
);

$("#calculateScoresButton").addEventListener(
    "click",
    calculateGameScores
);


$("#scorePlayers").addEventListener(
    "click",
    (event) => {

        const button = event.target.closest(
            ".remove-player-button"
        );

        if (!button || button.disabled) {
            return;
        }

        button.closest(".score-player-row").remove();

        updateRemovePlayerButtons();
    }
);


// Escape closes drawers and the upload modal.

document.addEventListener(
    "keydown",
    (event) => {

        if (event.key !== "Escape") {
            return;
        }

        if (!toolDrawer.hidden) {
            closeDrawer();
            return;
        }

        if (!uploadModal.hidden && uploadProcessing.hidden) {
            closeUploadModal();
        }
    }
);


/* =========================================================
   15. INITIALIZATION
========================================================= */

async function initializeBoardBrain() {

    updateRemovePlayerButtons();

    await loadGames();
}


document.addEventListener(
    "DOMContentLoaded",
    initializeBoardBrain
);