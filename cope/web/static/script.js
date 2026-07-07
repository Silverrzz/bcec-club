document.querySelectorAll("tr[data-href], .card--link[data-href], .live-game-card[data-href]").forEach((element) => {
  element.addEventListener("click", (event) => {
    if (event.target.closest("a, button, form, input, select, label")) return;
    window.location.href = element.dataset.href;
  });
});

document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", (event) => {
    if (!window.confirm(button.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

(() => {
  const storageKey = "cope.chat.displayName";
  const fields = document.querySelectorAll("[data-chat-display-name]");
  if (!fields.length) return;

  function readName() {
    try {
      return window.localStorage.getItem(storageKey) || "";
    } catch {
      return "";
    }
  }

  function writeName(value) {
    try {
      const name = value.trim();
      if (name) {
        window.localStorage.setItem(storageKey, name);
      } else {
        window.localStorage.removeItem(storageKey);
      }
    } catch {
    }
  }

  const storedName = readName();
  fields.forEach((field) => {
    if (!field.value && storedName) {
      field.value = storedName;
    }
    field.addEventListener("input", () => writeName(field.value));
    field.closest("form")?.addEventListener("submit", () => writeName(field.value));
  });
})();

document.querySelectorAll("[data-chat-form]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const textField = form.querySelector('[name="text"]');
    const submitButton = form.querySelector('[type="submit"]');
    const formData = new FormData(form);
    if (!String(formData.get("text") || "").trim()) return;

    if (submitButton) submitButton.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: formData,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;

      let message = null;
      try {
        const payload = await response.json();
        message = payload.message;
      } catch {
        message = {
          display_name: String(formData.get("display_name") || "").trim() || "Anonymous",
          text: String(formData.get("text") || "").trim(),
        };
      }
      if (!message) return;

      const log = form.closest(".arena-chat")?.querySelector("[data-chat-log]");
      if (log) {
        log.querySelector(".muted")?.remove();
        const line = document.createElement("p");
        const name = document.createElement("strong");
        name.textContent = message.display_name;
        line.append(name, " ", message.text);
        log.append(line);
        log.scrollTop = log.scrollHeight;
      }
      if (textField) textField.value = "";
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  });
});

document.querySelectorAll("[data-tabs]").forEach((tabs) => {
  const links = tabs.querySelectorAll("[data-tab]");
  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      links.forEach((other) => other.classList.toggle("active", other === link));
      document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.tabPanel !== link.dataset.tab;
      });
      history.replaceState(null, "", link.getAttribute("href"));
    });
  });
});

function refreshConditionalFields(select, attribute) {
  const chosen = select.value;
  document.querySelectorAll(`[${attribute}]`).forEach((element) => {
    const applies = element.getAttribute(attribute).split(/\s+/).includes(chosen);
    element.hidden = !applies;
  });
}

function refreshSettingsOverrides() {
  const linkedToggle = document.querySelector("[data-linked-toggle]");
  const settings = document.querySelector("[data-settings-overrides]");
  const unlinkButton = document.querySelector("[data-unlink-settings]");
  if (!linkedToggle || !settings) return;

  settings.hidden = linkedToggle.checked;
  if (unlinkButton) unlinkButton.hidden = !linkedToggle.checked;
}

document.querySelectorAll("[data-toggle=format]").forEach((select) => {
  const refresh = () => refreshConditionalFields(select, "data-format-field");
  select.addEventListener("change", refresh);
  refresh();
});

document.querySelectorAll("[data-toggle=tc]").forEach((select) => {
  const refresh = () => refreshConditionalFields(select, "data-tc-field");
  select.addEventListener("change", refresh);
  refresh();
});

document.querySelectorAll("[data-toggle-panel]").forEach((checkbox) => {
  const panel = document.getElementById(checkbox.dataset.togglePanel);
  if (!panel) return;
  checkbox.addEventListener("change", () => {
    panel.hidden = !checkbox.checked;
  });
});

(() => {
  const categorySelect = document.querySelector("[data-category-select]");
  const defaultsScript = document.querySelector("[data-category-defaults]");
  if (!categorySelect || !defaultsScript) return;

  const defaults = JSON.parse(defaultsScript.textContent || "{}");
  const linkedToggle = document.querySelector("[data-linked-toggle]");
  const unlinkButton = document.querySelector("[data-unlink-settings]");

  function applyDefaults() {
    if (linkedToggle && !linkedToggle.checked) return;
    const values = defaults[categorySelect.value];
    if (!values) return;
    Object.entries(values).forEach(([name, value]) => {
      const field = document.querySelector(`[name="${name}"]`);
      if (!field) return;
      if (field.type === "checkbox") {
        field.checked = Boolean(value);
        field.dispatchEvent(new Event("change"));
      } else {
        field.value = value === null ? "" : value;
        if (field.tagName === "SELECT") field.dispatchEvent(new Event("change"));
      }
    });
  }

  categorySelect.addEventListener("change", applyDefaults);
  if (linkedToggle) {
    linkedToggle.addEventListener("change", () => {
      refreshSettingsOverrides();
      applyDefaults();
    });
    refreshSettingsOverrides();
  }
  if (unlinkButton && linkedToggle) {
    unlinkButton.addEventListener("click", () => {
      linkedToggle.checked = false;
      linkedToggle.dispatchEvent(new Event("change"));
    });
  }
})();

function startPosition() {
  const board = Array.from({ length: 8 }, () => Array(8).fill(null));
  const back = ["r", "n", "b", "q", "k", "b", "n", "r"];
  for (let file = 0; file < 8; file += 1) {
    board[0][file] = back[file].toUpperCase();
    board[1][file] = "P";
    board[6][file] = "p";
    board[7][file] = back[file];
  }
  return board;
}

function positionFromFen(fen) {
  if (!fen || fen === "startpos") return startPosition();

  const placement = fen.split(/\s+/, 1)[0];
  const board = Array.from({ length: 8 }, () => Array(8).fill(null));
  placement.split("/").forEach((rankText, rankOffset) => {
    let file = 0;
    const rank = 7 - rankOffset;
    for (const char of rankText) {
      if (/\d/.test(char)) {
        file += Number(char);
      } else if (file < 8 && rank >= 0) {
        board[rank][file] = char;
        file += 1;
      }
    }
  });
  return board;
}

function fenSideToMove(fen) {
  if (!fen || fen === "startpos") return "w";
  return fen.split(/\s+/)[1] === "b" ? "b" : "w";
}

function fenFullmove(fen) {
  if (!fen || fen === "startpos") return 1;
  const raw = fen.split(/\s+/)[5];
  const fullmove = Number(raw);
  return Number.isInteger(fullmove) && fullmove > 0 ? fullmove : 1;
}

function squareIndex(square) {
  return {
    file: square.charCodeAt(0) - 97,
    rank: square.charCodeAt(1) - 49,
  };
}

function applyUciMove(board, uci) {
  const from = squareIndex(uci.slice(0, 2));
  const to = squareIndex(uci.slice(2, 4));
  const promotion = uci[4];
  const piece = board[from.rank][from.file];
  if (!piece) return;

  const isWhite = piece === piece.toUpperCase();

  // En passant: pawn moves diagonally onto an empty square.
  if (
    piece.toUpperCase() === "P" &&
    from.file !== to.file &&
    board[to.rank][to.file] === null
  ) {
    board[from.rank][to.file] = null;
  }

  // Castling: king moves two files; bring the rook across.
  if (piece.toUpperCase() === "K" && Math.abs(to.file - from.file) === 2) {
    const rank = from.rank;
    if (to.file === 6) {
      board[rank][5] = board[rank][7];
      board[rank][7] = null;
    } else if (to.file === 2) {
      board[rank][3] = board[rank][0];
      board[rank][0] = null;
    }
  }

  board[from.rank][from.file] = null;
  board[to.rank][to.file] = promotion
    ? (isWhite ? promotion.toUpperCase() : promotion.toLowerCase())
    : piece;
}

function boardToFen(board) {
  const ranks = [];
  for (let rank = 7; rank >= 0; rank -= 1) {
    let row = "";
    let empty = 0;
    for (let file = 0; file < 8; file += 1) {
      const piece = board[rank][file];
      if (piece) {
        if (empty) {
          row += empty;
          empty = 0;
        }
        row += piece;
      } else {
        empty += 1;
      }
    }
    if (empty) row += empty;
    ranks.push(row);
  }
  return ranks.join("/");
}

function initBoard(shell, Chessground) {
  const grid = shell.querySelector("[data-board-grid]");
  if (!grid) return;
  let moves = (shell.dataset.moves || "").split(/\s+/).filter(Boolean);
  let initialFen = shell.dataset.fen || "startpos";
  let initialSide = fenSideToMove(initialFen);
  let initialFullmove = fenFullmove(initialFen);
  const currentFen = shell.querySelector("[data-current-fen]");

  function buildFens(fen, uciMoves) {
    let position = positionFromFen(fen);
    const nextFens = [boardToFen(position)];
    uciMoves.forEach((uci) => {
      position = position.map((rank) => rank.slice());
      applyUciMove(position, uci);
      nextFens.push(boardToFen(position));
    });
    return nextFens;
  }

  let fens = buildFens(initialFen, moves);
  let ply = fens.length - 1;
  const status = shell.querySelector("[data-board-status]");

  const ground = Chessground(grid, {
    viewOnly: true,
    coordinates: shell.dataset.boardCoordinates === "true",
    animation: { duration: 150 },
    drawable: { enabled: false },
  });

  function render() {
    const lastMove = ply > 0 ? moves[ply - 1] : null;
    const fen = fens[ply];
    ground.set({
      fen,
      lastMove: lastMove ? [lastMove.slice(0, 2), lastMove.slice(2, 4)] : undefined,
    });
    if (status) {
      status.textContent = moves.length
        ? `move ${ply} / ${moves.length}`
        : "start position";
    }
    if (currentFen) {
      const side = (initialSide === "w" ? ply : ply + 1) % 2 === 0 ? "w" : "b";
      const fullmove = initialFullmove + Math.floor((ply + (initialSide === "b" ? 1 : 0)) / 2);
      const fullFen = ply === 0 && initialFen !== "startpos"
        ? initialFen
        : `${fen} ${side} - - 0 ${fullmove}`;
      currentFen.dataset.copy = fullFen;
      const value = currentFen.querySelector("strong");
      if (value) value.textContent = fullFen;
    }
  }

  function step(target) {
    ply = Math.max(0, Math.min(fens.length - 1, target));
    render();
  }

  function updatePosition(nextFen, nextMoves, options = {}) {
    const wasFollowing = ply === fens.length - 1;
    const oldFen = initialFen;
    initialFen = nextFen || "startpos";
    initialSide = fenSideToMove(initialFen);
    initialFullmove = fenFullmove(initialFen);
    moves = nextMoves.slice();
    fens = buildFens(initialFen, moves);

    if (options.forceLatest || oldFen !== initialFen || wasFollowing || ply >= fens.length) {
      ply = fens.length - 1;
    }
    render();
  }

  shell.querySelector("[data-board-first]")?.addEventListener("click", () => step(0));
  shell.querySelector("[data-board-prev]")?.addEventListener("click", () => step(ply - 1));
  shell.querySelector("[data-board-next]")?.addEventListener("click", () => step(ply + 1));
  shell.querySelector("[data-board-last]")?.addEventListener("click", () => step(fens.length - 1));

  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input, textarea, select")) return;
    if (event.key === "ArrowLeft") step(ply - 1);
    if (event.key === "ArrowRight") step(ply + 1);
  });

  render();
  shell.copeBoard = { updatePosition };
}

const boardShells = document.querySelectorAll("[data-board]");
if (boardShells.length) {
  import("https://cdn.jsdelivr.net/npm/chessground@9/+esm").then(({ Chessground }) => {
    boardShells.forEach((shell) => initBoard(shell, Chessground));
  });
}

document.querySelectorAll("[data-tournament-live]").forEach((arena) => {
  const tournamentId = arena.dataset.tournamentId;
  if (!tournamentId) return;

  const liveBoard = arena.querySelector("[data-live-board]");
  const openingButton = arena.querySelector("[data-live-opening]");
  let lastGameId = null;
  let lastMoveKey = "";
  let stopped = false;

  function setText(selector, value) {
    const element = arena.querySelector(selector);
    if (element) element.textContent = value;
  }

  function setLiveText(key, value) {
    setText(`[data-live-${key}]`, value);
  }

  function setEngine(side, game) {
    const id = game ? game[`${side}_engine_id`] : null;
    const name = game ? game[`${side}_name`] : side[0].toUpperCase() + side.slice(1);
    setLiveText(`${side}-name`, name);
    const link = arena.querySelector(`[data-live-${side}-link]`);
    if (link && id !== null) link.href = `/engines/${id}`;
  }

  function setEngineData(side, data) {
    const values = data || {};
    ["depth", "nodes", "nps", "eval"].forEach((name) => {
      setLiveText(`${side}-${name}`, values[name] || "-");
    });
    setLiveText(`${side}-pv`, values.pv || "not recorded");
  }

  function setClocks(clocks) {
    const values = clocks || {};
    ["white", "black"].forEach((side) => {
      setLiveText(`${side}-clock`, values[side] || "--:--");
    });
  }

  function linkedRow(href) {
    const row = document.createElement("tr");
    row.dataset.href = href;
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, form, input, select, label")) return;
      window.location.href = href;
    });
    return row;
  }

  function appendCell(row, value, className) {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = value;
    row.append(cell);
    return cell;
  }

  function statusBadge(status) {
    const badge = document.createElement("span");
    badge.className = `badge badge--${status}`;
    badge.textContent = status;
    return badge;
  }

  function resultText(result) {
    return result || "-";
  }

  function renderStandings(standings) {
    const body = document.querySelector("[data-live-standings]");
    if (!body || !Array.isArray(standings)) return;

    body.replaceChildren(...standings.map((standing, index) => {
      const row = linkedRow(`/engines/${standing.engine_id}`);
      appendCell(row, String(index + 1), "col-narrow");
      appendCell(row, standing.name || `Engine ${standing.engine_id}`);
      appendCell(row, String(standing.points ?? 0));
      appendCell(row, String(standing.played ?? 0));
      return row;
    }));
  }

  function renderGames(games) {
    const body = document.querySelector("[data-live-games]");
    if (!body || !Array.isArray(games)) return;

    body.replaceChildren(...games.map((game) => {
      const row = linkedRow(`/games/${game.id}`);
      appendCell(row, String(game.round), "col-narrow");
      appendCell(row, game.white_name || "White");
      appendCell(row, game.black_name || "Black");
      const statusCell = document.createElement("td");
      statusCell.append(statusBadge(game.status || "pending"));
      row.append(statusCell);
      appendCell(row, resultText(game.result), "col-result");
      return row;
    }));
  }

  function applyLivePayload(payload) {
    if (!payload || stopped) return;
    const game = payload.game || null;
    const opening = payload.opening || { name: "Start position", fen: "startpos" };
    const moves = Array.isArray(payload.moves) ? payload.moves.map((move) => move.uci) : [];
    const moveKey = moves.join(" ");
    const gameChanged = (game ? game.id : null) !== lastGameId;

    setEngine("white", game);
    setEngine("black", game);
    setEngineData("white", payload.engine_data?.white);
    setEngineData("black", payload.engine_data?.black);
    setClocks(payload.clocks);
    renderStandings(payload.standings);
    renderGames(payload.games);

    if (openingButton) {
      const name = opening.name || "Start position";
      const fen = opening.fen || "startpos";
      openingButton.dataset.copy = fen === "startpos" ? name : `${name} | ${fen}`;
      const value = openingButton.querySelector("strong");
      if (value) value.textContent = name;
    }

    const boardNeedsUpdate = gameChanged || moveKey !== lastMoveKey;
    if (liveBoard && !liveBoard.copeBoard && boardNeedsUpdate) {
      return;
    }

    if (liveBoard?.copeBoard && boardNeedsUpdate) {
      liveBoard.dataset.gameId = game ? game.id : "";
      liveBoard.dataset.fen = opening.fen || "startpos";
      liveBoard.dataset.moves = moveKey;
      liveBoard.copeBoard.updatePosition(opening.fen || "startpos", moves, {
        forceLatest: gameChanged,
      });
    }

    lastGameId = game ? game.id : null;
    lastMoveKey = moveKey;
    if (!game && ["finished", "aborted"].includes(payload.tournament?.status)) {
      stopped = true;
    }
  }

  const events = new EventSource(`/tournaments/${tournamentId}/events`);
  events.addEventListener("snapshot", (event) => {
    try {
      applyLivePayload(JSON.parse(event.data));
    } catch {
    }
  });
});

document.querySelectorAll("[data-copy]").forEach((element) => {
  element.addEventListener("click", async () => {
    const text = element.dataset.copy || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      element.classList.add("copied");
      window.setTimeout(() => element.classList.remove("copied"), 700);
    } catch {
    }
  });
});
