from __future__ import annotations

import io
from pathlib import Path


UploadedTextFiles = list[tuple[str, str]]


def parse_openings(text: str) -> list[tuple[str, str]]:
    openings: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        name, separator, fen = line.partition(";")
        if separator:
            openings.append((name.strip(), fen.strip()))
        else:
            openings.append(("", line))
    return openings


def parse_opening_uploads(files: UploadedTextFiles) -> list[tuple[str, str]]:
    openings: list[tuple[str, str]] = []
    for filename, text in files:
        if not text.strip():
            continue
        suffix = Path(filename).suffix.lower()
        if suffix == ".pgn":
            openings.extend(_parse_pgn_openings(text))
        elif suffix == ".epd":
            openings.extend(_parse_epd_openings(text))
        else:
            openings.extend(parse_openings(text))
    return openings


def _parse_pgn_openings(text: str) -> list[tuple[str, str]]:
    import chess.pgn

    openings: list[tuple[str, str]] = []
    stream = io.StringIO(text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        board = game.board()
        for move in game.mainline_moves():
            board.push(move)
        name = next(
            (
                value
                for key in ("Opening", "Event")
                if (value := game.headers.get(key, "").strip()) not in {"?", "-"}
            ),
            f"PGN line {len(openings) + 1}",
        )
        openings.append((name, board.fen()))
    return openings


def _parse_epd_openings(text: str) -> list[tuple[str, str]]:
    import chess

    openings: list[tuple[str, str]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        board = chess.Board(" ".join(fields[:4]) + " 0 1")
        openings.append((f"EPD {index}", board.fen()))
    return openings
