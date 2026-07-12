export const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

export type Color = 'white' | 'black'
export type Piece = 'P' | 'N' | 'B' | 'R' | 'Q' | 'K' | 'p' | 'n' | 'b' | 'r' | 'q' | 'k'

export interface Position {
  squares: Array<Piece | null>
  turn: 'w' | 'b'
  castling: string
  enPassant: string
  halfmove: number
  fullmove: number
}

export interface MaterialSummary {
  white: number
  black: number
  balance: number
  label: string
}

const MATERIAL_VALUES: Record<string, number> = {
  p: 1,
  n: 3,
  b: 3,
  r: 5,
  q: 9,
  k: 0,
}

export function normalizedFen(fen?: string | null): string {
  return !fen || fen.trim().toLowerCase() === 'startpos' ? START_FEN : fen.trim()
}

export function parseFen(fen?: string | null): Position {
  const fields = normalizedFen(fen).split(/\s+/)
  const ranks = fields[0]?.split('/') || []
  const squares: Array<Piece | null> = Array(64).fill(null)

  ranks.slice(0, 8).forEach((rank, rankIndex) => {
    let file = 0
    for (const value of rank) {
      const empty = Number(value)
      if (Number.isInteger(empty) && empty > 0) {
        file += empty
      } else if (isPiece(value) && file < 8) {
        squares[rankIndex * 8 + file] = value
        file += 1
      }
    }
  })

  return {
    squares,
    turn: fields[1] === 'b' ? 'b' : 'w',
    castling: fields[2] && fields[2] !== '' ? fields[2] : '-',
    enPassant: fields[3] && fields[3] !== '' ? fields[3] : '-',
    halfmove: integerOr(fields[4], 0),
    fullmove: Math.max(1, integerOr(fields[5], 1)),
  }
}

export function applyUci(position: Position, move: string): Position {
  const next = clonePosition(position)
  const normalized = move.trim().toLowerCase()
  if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(normalized)) return next

  const fromSquare = normalized.slice(0, 2)
  const toSquare = normalized.slice(2, 4)
  const from = squareIndex(fromSquare)
  const to = squareIndex(toSquare)
  const piece = next.squares[from]
  if (!piece) return next

  const isWhite = piece === piece.toUpperCase()
  const isPawn = piece.toLowerCase() === 'p'
  const isKing = piece.toLowerCase() === 'k'
  const captured = next.squares[to] ?? null
  const fromFile = fileIndex(fromSquare)
  const toFile = fileIndex(toSquare)
  const fromRank = rankNumber(fromSquare)
  const toRank = rankNumber(toSquare)

  if (isPawn && fromFile !== toFile && !captured) {
    const capturedRank = isWhite ? toRank - 1 : toRank + 1
    next.squares[squareIndex(`${toSquare[0]}${capturedRank}`)] = null
  }

  if (isKing && Math.abs(toFile - fromFile) === 2) {
    const rank = fromSquare[1]
    const kingSide = toFile > fromFile
    const rookFrom = squareIndex(`${kingSide ? 'h' : 'a'}${rank}`)
    const rookTo = squareIndex(`${kingSide ? 'f' : 'd'}${rank}`)
    next.squares[rookTo] = next.squares[rookFrom] ?? null
    next.squares[rookFrom] = null
  }

  next.squares[from] = null
  const promotion = normalized[4]
  next.squares[to] = promotion
    ? (isWhite ? promotion.toUpperCase() : promotion) as Piece
    : piece

  next.castling = updateCastling(next.castling, piece, fromSquare, toSquare, captured)
  next.enPassant = isPawn && Math.abs(toRank - fromRank) === 2
    ? `${fromSquare[0]}${(fromRank + toRank) / 2}`
    : '-'
  next.halfmove = isPawn || captured ? 0 : next.halfmove + 1
  if (position.turn === 'b') next.fullmove += 1
  next.turn = position.turn === 'w' ? 'b' : 'w'
  return next
}

export function buildPositions(fen: string | null | undefined, moves: string[]): Position[] {
  const positions = [parseFen(fen)]
  for (const move of moves) {
    positions.push(applyUci(positions.at(-1)!, move))
  }
  return positions
}

export function positionFen(position: Position): string {
  const ranks: string[] = []
  for (let rank = 0; rank < 8; rank += 1) {
    let value = ''
    let empty = 0
    for (let file = 0; file < 8; file += 1) {
      const piece = position.squares[rank * 8 + file]
      if (piece) {
        if (empty) value += String(empty)
        empty = 0
        value += piece
      } else {
        empty += 1
      }
    }
    if (empty) value += String(empty)
    ranks.push(value)
  }
  return `${ranks.join('/')} ${position.turn} ${position.castling || '-'} ${position.enPassant || '-'} ${position.halfmove} ${position.fullmove}`
}

export function materialSummary(position: Position): MaterialSummary {
  let white = 0
  let black = 0
  for (const piece of position.squares) {
    if (!piece) continue
    const score = MATERIAL_VALUES[piece.toLowerCase()] || 0
    if (piece === piece.toUpperCase()) white += score
    else black += score
  }
  const balance = white - black
  return {
    white,
    black,
    balance,
    label: balance === 0 ? 'Material equal' : `${balance > 0 ? 'White' : 'Black'} +${Math.abs(balance)}`,
  }
}

function clonePosition(position: Position): Position {
  return { ...position, squares: [...position.squares] }
}

function isPiece(value: string): value is Piece {
  return /^[prnbqkPRNBQK]$/.test(value)
}

function integerOr(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value || '', 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

function fileIndex(square: string): number {
  return square.charCodeAt(0) - 97
}

function rankNumber(square: string): number {
  return Number.parseInt(square.charAt(1), 10)
}

function squareIndex(square: string): number {
  const file = fileIndex(square)
  const rank = rankNumber(square)
  return (8 - rank) * 8 + file
}

function updateCastling(
  current: string,
  piece: Piece,
  from: string,
  to: string,
  captured: Piece | null,
): string {
  let rights = current === '-' ? '' : current
  if (piece === 'K') rights = rights.replace(/[KQ]/g, '')
  if (piece === 'k') rights = rights.replace(/[kq]/g, '')

  const rightsByRookSquare: Record<string, string> = {
    a1: 'Q',
    h1: 'K',
    a8: 'q',
    h8: 'k',
  }
  if (piece.toLowerCase() === 'r' && rightsByRookSquare[from]) {
    rights = rights.replace(rightsByRookSquare[from], '')
  }
  if (captured?.toLowerCase() === 'r' && rightsByRookSquare[to]) {
    rights = rights.replace(rightsByRookSquare[to], '')
  }
  return rights || '-'
}
