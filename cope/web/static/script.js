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
  const token = document.querySelector('meta[name="cope-csrf"]')?.content || "";
  if (!token) return;
  document.querySelectorAll('form[method="post"][action^="/admin"]').forEach((form) => {
    if (form.querySelector('input[name="csrf_token"]')) return;
    const field = document.createElement("input");
    field.type = "hidden";
    field.name = "csrf_token";
    field.value = token;
    form.prepend(field);
  });
})();

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

const MATERIAL_VALUES = {
  P: 1,
  N: 3,
  B: 3,
  R: 5,
  Q: 9,
};

function materialScoreFromFen(fen) {
  const placement = (fen || "").split(/\s+/, 1)[0];
  let white = 0;
  let black = 0;

  for (const piece of placement) {
    const value = MATERIAL_VALUES[piece.toUpperCase()] || 0;
    if (!value) continue;
    if (piece === piece.toUpperCase()) {
      white += value;
    } else {
      black += value;
    }
  }

  return white - black;
}

function createMaterialCounters(shell, grid) {
  if (!shell.querySelector("[data-board-status]")) return null;

  const dock = shell.querySelector("[data-material-counters]");
  const blackRow = shell.querySelector(".player-row--black");
  const whiteRow = shell.querySelector(".player-row--white");
  const black = document.createElement("span");
  black.className = "material-counter material-counter--black";
  black.hidden = true;

  const white = document.createElement("span");
  white.className = "material-counter material-counter--white";
  white.hidden = true;

  if (dock) {
    const equal = document.createElement("span");
    equal.className = "material-counter material-counter--equal";
    equal.hidden = true;
    dock.append(white, black, equal);
    return { black, white, equal };
  } else if (blackRow && whiteRow) {
    blackRow.classList.add("player-row--has-material-counter");
    whiteRow.classList.add("player-row--has-material-counter");
    blackRow.append(black);
    whiteRow.append(white);
  } else {
    grid.append(black, white);
  }

  return { black, white };
}

function updateMaterialCounters(counters, fen) {
  if (!counters) return;

  const score = materialScoreFromFen(fen);
  counters.white.hidden = score <= 0;
  counters.black.hidden = score >= 0;
  if (counters.equal) counters.equal.hidden = score !== 0;

  if (score > 0) {
    counters.white.textContent = counters.equal ? `White +${score}` : `+${score}`;
    counters.white.title = `White is up ${score} material`;
  } else if (score < 0) {
    const blackScore = Math.abs(score);
    counters.black.textContent = counters.equal ? `Black +${blackScore}` : `+${blackScore}`;
    counters.black.title = `Black is up ${blackScore} material`;
  } else if (counters.equal) {
    counters.equal.textContent = "Equal";
    counters.equal.title = "Material is equal";
  }
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
  const materialCounters = createMaterialCounters(shell, grid);

  function render() {
    const lastMove = ply > 0 ? moves[ply - 1] : null;
    const fen = fens[ply];
    ground.set({
      fen,
      lastMove: lastMove ? [lastMove.slice(0, 2), lastMove.slice(2, 4)] : undefined,
    });
    updateMaterialCounters(materialCounters, fen);
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
    shell.dispatchEvent(new CustomEvent("cope:board-position", {
      detail: { ply, fen, moves: moves.slice(0, ply) },
    }));
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

  const viewerLocked = arena.dataset.viewerLocked === "true";
  const liveBoard = arena.querySelector("[data-live-board]");
  const openingButton = arena.querySelector("[data-live-opening]");
  const replayMoves = parseReplayMoves();
  const pvBoards = {
    white: arena.querySelector("[data-live-white-pv-board]"),
    black: arena.querySelector("[data-live-black-pv-board]"),
  };
  const engineState = {
    white: emptyEngineState(),
    black: emptyEngineState(),
  };
  let lastGameId = null;
  let lastMoveKey = "";
  let stopped = false;
  let currentOpening = {
    name: openingButton?.querySelector("strong")?.textContent || "Start position",
    fen: liveBoard?.dataset.fen || "startpos",
  };
  let currentMoves = [];
  let clockState = null;
  let clockFrame = null;

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

  function emptyEngineState() {
    return {
      depth: "-",
      nodes: "-",
      nps: "-",
      eval: "-",
      info: "not recorded",
      pv: "not recorded",
      rootFen: null,
      rootMoves: [],
    };
  }

  function displayValue(value, fallback = "-") {
    if (value === undefined || value === null || value === "") return fallback;
    return String(value);
  }

  function recordedPv(value) {
    const pv = displayValue(value, "").trim();
    return pv && pv.toLowerCase() !== "not recorded" ? pv : "";
  }

  function parsePvMoves(pv) {
    return recordedPv(pv)
      .split(/\s+/)
      .map((move) => move.toLowerCase())
      .filter((move) => /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(move));
  }

  function setEngineData(side, data, options = {}) {
    if (options.gameChanged || options.replace) {
      engineState[side] = emptyEngineState();
    }

    const values = data && typeof data === "object" ? data : {};
    const state = engineState[side];
    ["depth", "nodes", "nps", "eval", "info"].forEach((name) => {
      state[name] = displayValue(values[name], name === "info" ? "not recorded" : "-");
      setLiveText(`${side}-${name}`, state[name]);
    });

    const pv = recordedPv(values.pv);
    if (pv) {
      state.pv = pv;
      state.rootFen = displayValue(values.root_fen, "").trim() || null;
      state.rootMoves = state.rootFen ? [] : (options.gameMoves || []).slice();
    } else if (options.replace) {
      state.pv = "not recorded";
      state.rootFen = null;
      state.rootMoves = [];
    }
    setLiveText(`${side}-pv`, state.pv);
  }

  function updatePvBoard(side, opening, gameMoves) {
    const shell = pvBoards[side];
    if (!shell) return;

    const pvMoves = parsePvMoves(engineState[side].pv);
    let fen = engineState[side].rootFen;
    let moves = pvMoves;

    if (!pvMoves.length) {
      fen = opening.fen || "startpos";
      moves = [];
    } else if (!fen) {
      fen = opening.fen || "startpos";
      moves = (engineState[side].rootMoves || gameMoves).concat(pvMoves);
    }

    shell.dataset.fen = fen;
    shell.dataset.moves = moves.join(" ");
    if (shell.copeBoard) {
      shell.copeBoard.updatePosition(fen, moves, { forceLatest: true });
    }
  }

  function updatePvBoards(opening, gameMoves) {
    updatePvBoard("white", opening, gameMoves);
    updatePvBoard("black", opening, gameMoves);
  }

  function setClocks(clocks) {
    const values = clocks || {};
    ["white", "black"].forEach((side) => {
      setLiveText(`${side}-clock`, values[side] || "--:--");
    });
  }

  function clockLabel(milliseconds) {
    if (milliseconds === undefined || milliseconds === null) return "--:--";
    const total = Math.max(0, Math.floor(Number(milliseconds) || 0));
    const seconds = Math.floor(total / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }

  function stopClockRender() {
    if (clockFrame !== null) {
      window.cancelAnimationFrame(clockFrame);
      clockFrame = null;
    }
  }

  function renderClockState() {
    if (!clockState) return;
    const elapsed = clockState.running
      ? Math.max(0, Date.now() - clockState.startedAt)
      : 0;
    ["white", "black"].forEach((side) => {
      let value = clockState.clocksMs[side];
      if (clockState.running && clockState.activeSide === side && value !== null && value !== undefined) {
        value = Math.max(0, Number(value) - elapsed);
      }
      setLiveText(`${side}-clock`, clockLabel(value));
    });
    if (clockState.running) {
      clockFrame = window.requestAnimationFrame(renderClockState);
    }
  }

  function applyClockSync(envelope) {
    const data = envelope?.data || {};
    const sentAt = Date.parse(envelope.sent_at || "");
    clockState = {
      activeSide: data.active_side || null,
      running: Boolean(data.running),
      clocksMs: data.clocks_ms || {},
      startedAt: Number.isFinite(sentAt) ? sentAt : Date.now(),
    };
    stopClockRender();
    renderClockState();
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

  function parseReplayMoves() {
    const script = arena.querySelector("[data-viewer-moves]");
    if (!script) return [];
    try {
      const moves = JSON.parse(script.textContent || "[]");
      return Array.isArray(moves) ? moves : [];
    } catch {
      return [];
    }
  }

  function formatNumber(value) {
    if (value === undefined || value === null || value === "") return "-";
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : String(value);
  }

  function formatEval(move) {
    if (!move) return "-";
    if (move.eval_mate !== undefined && move.eval_mate !== null) return `#${move.eval_mate}`;
    if (move.eval_cp !== undefined && move.eval_cp !== null) {
      return (Number(move.eval_cp) / 100).toLocaleString(undefined, {
        signDisplay: "always",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
    return "-";
  }

  function npsForMove(move) {
    if (!move) return "-";
    if (move.nps !== undefined && move.nps !== null) return formatNumber(move.nps);
    const nodes = Number(move.nodes);
    const timeMs = Number(move.time_ms);
    if (Number.isFinite(nodes) && Number.isFinite(timeMs) && timeMs > 0) {
      return Math.floor(nodes / (timeMs / 1000)).toLocaleString();
    }
    return "-";
  }

  function engineDataForMove(move) {
    if (!move) return emptyEngineState();
    return {
      depth: displayValue(move.depth),
      nodes: formatNumber(move.nodes),
      nps: npsForMove(move),
      eval: formatEval(move),
      info: displayValue(move.info_line || move.pv, "not recorded"),
      pv: displayValue(move.pv, "not recorded"),
    };
  }

  function latestReplayMove(side, ply) {
    const wantsWhite = side === "white";
    for (let index = replayMoves.length - 1; index >= 0; index -= 1) {
      const move = replayMoves[index];
      if (!move || move.ply > ply) continue;
      if ((move.ply % 2 === 1) === wantsWhite) return move;
    }
    return null;
  }

  function replayClockLabel(side, ply) {
    const wantsWhite = side === "white";
    for (let index = replayMoves.length - 1; index >= 0; index -= 1) {
      const move = replayMoves[index];
      if (!move || move.ply > ply) continue;
      if ((move.ply % 2 === 1) === wantsWhite) return clockLabel(move.clock_after_ms);
    }
    return "--:--";
  }

  function applyReplayPly(ply) {
    ["white", "black"].forEach((side) => {
      const move = latestReplayMove(side, ply);
      setEngineData(side, engineDataForMove(move), {
        replace: true,
        gameMoves: move ? currentMoves.slice(0, Math.max(0, move.ply - 1)) : [],
      });
      setLiveText(`${side}-clock`, replayClockLabel(side, ply));
    });
    updatePvBoards(currentOpening, currentMoves.slice(0, ply));
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
      const row = linkedRow(`/tournaments/${game.tournament_id}?game_id=${game.id}`);
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
    currentOpening = opening;
    currentMoves = moves;

    setEngine("white", game);
    setEngine("black", game);
    setEngineData("white", payload.engine_data?.white, { gameChanged, gameMoves: moves });
    setEngineData("black", payload.engine_data?.black, { gameChanged, gameMoves: moves });
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
    if (liveBoard && boardNeedsUpdate) {
      liveBoard.dataset.gameId = game ? game.id : "";
      liveBoard.dataset.fen = opening.fen || "startpos";
      liveBoard.dataset.moves = moveKey;
      if (liveBoard.copeBoard) {
        liveBoard.copeBoard.updatePosition(opening.fen || "startpos", moves, {
          forceLatest: gameChanged,
        });
      }
    }
    updatePvBoards(opening, moves);

    lastGameId = game ? game.id : null;
    lastMoveKey = moveKey;
    if (!game && ["finished", "aborted"].includes(payload.tournament?.status)) {
      stopped = true;
      stopClockRender();
    }
  }

  if (viewerLocked) {
    currentMoves = replayMoves.map((move) => move.uci).filter(Boolean);
    liveBoard?.addEventListener("cope:board-position", (event) => {
      applyReplayPly(event.detail?.ply || 0);
    });
    applyReplayPly(currentMoves.length);
    return;
  }

  const events = new EventSource(`/tournaments/${tournamentId}/events`);

  function parseEnvelope(event) {
    try {
      return JSON.parse(event.data);
    } catch {
      return null;
    }
  }

  events.addEventListener("tournament.snapshot", (event) => {
    const envelope = parseEnvelope(event);
    if (envelope) applyLivePayload(envelope.data);
  });

  events.addEventListener("engine.info", (event) => {
    const envelope = parseEnvelope(event);
    const data = envelope?.data || {};
    const side = data.side;
    if (side !== "white" && side !== "black") return;
    setEngineData(side, data.engine_data || data, { gameMoves: currentMoves });
    updatePvBoard(side, currentOpening, currentMoves);
  });

  events.addEventListener("clock.sync", (event) => {
    const envelope = parseEnvelope(event);
    if (envelope) applyClockSync(envelope);
  });

  events.addEventListener("game.move", () => {
    stopClockRender();
  });

  events.onerror = () => {
    if (stopped) {
      events.close();
    }
  };
});

(() => {
  const table = document.querySelector("[data-worker-monitor]");
  if (!table) return;

  function statusBadge(status) {
    const badge = document.createElement("span");
    badge.className = `badge badge--${status}`;
    badge.textContent = status;
    return badge;
  }

  function rowIds() {
    return Array.from(table.querySelectorAll("[data-worker-row]"))
      .map((row) => row.dataset.workerRow || "")
      .filter(Boolean);
  }

  function sameIds(workers) {
    const current = rowIds();
    const next = workers.map((worker) => String(worker.id));
    return current.length === next.length && current.every((id, index) => id === next[index]);
  }

  function setWork(row, work) {
    const summary = row.querySelector("[data-worker-work-summary]");
    const activityLabel = row.querySelector("[data-worker-work-label]");
    const detail = row.querySelector("[data-worker-work-detail]");
    const meta = row.querySelector("[data-worker-work-meta]");
    if (activityLabel) {
      activityLabel.className = `worker-state worker-state--${work.status || "pending"}`;
      activityLabel.textContent = work.label || "Pending";
    }
    if (summary) {
      const label = work.summary || "No active assignment";
      const value = document.createElement(work.href ? "a" : "strong");
      if (work.href) value.href = work.href;
      value.textContent = label;
      if (activityLabel) {
        summary.replaceChildren(activityLabel, value);
      } else {
        summary.replaceChildren(value);
      }
    }
    if (detail) detail.textContent = work.detail || "";
    if (meta) {
      meta.textContent = work.meta || "";
      meta.hidden = !work.meta;
    }
  }

  function setMachine(row, machine) {
    const element = row.querySelector("[data-worker-machine]");
    if (!element) return;
    element.className = `worker-state worker-state--${machine.status}`;
    element.textContent = machine.label || machine.status || "";
  }

  function setHardware(row, hardware) {
    const coresCell = row.querySelector("[data-worker-cores]");
    const memoryCell = row.querySelector("[data-worker-memory]");
    if (!coresCell || !memoryCell) return;
    if (hardware.reported) {
      const coresValue = document.createElement("strong");
      const memoryValue = document.createElement("strong");
      coresValue.textContent = hardware.cores || "-";
      memoryValue.textContent = hardware.memory || "-";
      coresCell.replaceChildren(coresValue);
      memoryCell.replaceChildren(memoryValue);
      return;
    }
    const emptyCores = document.createElement("span");
    const emptyMemory = document.createElement("span");
    emptyCores.className = "worker-table__subtle";
    emptyMemory.className = "worker-table__subtle";
    emptyCores.textContent = "-";
    emptyMemory.textContent = "-";
    coresCell.replaceChildren(emptyCores);
    memoryCell.replaceChildren(emptyMemory);
  }

  function applyWorker(worker) {
    const row = table.querySelector(`[data-worker-row="${worker.id}"]`);
    if (!row) return;
    const statusCell = row.querySelector("[data-worker-status]");
    if (statusCell) statusCell.replaceChildren(statusBadge(worker.status || "offline"));
    row.classList.toggle("worker-row--abnormal", Boolean(worker.work?.abnormal));
    setWork(row, worker.work || {});
    setMachine(row, worker.machine || {});
    setHardware(row, worker.hardware || {});
  }

  function applyWorkersPayload(payload) {
    const workers = Array.isArray(payload?.workers) ? payload.workers : [];
    if (!sameIds(workers)) {
      window.location.reload();
      return;
    }
    workers.forEach(applyWorker);
  }

  function parseEnvelope(event) {
    try {
      return JSON.parse(event.data);
    } catch {
      return null;
    }
  }

  const events = new EventSource("/admin/workers/events");
  events.addEventListener("workers.snapshot", (event) => {
    const envelope = parseEnvelope(event);
    if (envelope) applyWorkersPayload(envelope.data);
  });
})();

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
