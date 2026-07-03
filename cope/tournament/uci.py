import chess


def setoption_command(name: str, value: str | int | bool) -> str:
    return f"setoption name {name} value {value}"


def position_command(board: chess.Board) -> str:
    root = board.root()
    moves = " ".join(move.uci() for move in board.move_stack)

    if root.fen() == chess.STARTING_FEN:
        command = "position startpos"
    else:
        command = f"position fen {root.fen()}"

    if moves:
        command = f"{command} moves {moves}"

    return command


def go_command(**kwargs: int | None) -> str:
    parts = ["go"]
    for key in ("wtime", "btime", "winc", "binc", "movetime", "movestogo", "nodes"):
        value = kwargs.get(key)
        if value is not None:
            parts.extend([key, str(value)])
    return " ".join(parts)
