<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onBeforeUpdate, onMounted, onUpdated, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'

import { api } from '@/api/client'
import ChessViewer from '@/components/chess/ChessViewer.vue'
import MoveList from '@/components/chess/MoveList.vue'
import { buildPositions, parseFen, positionFen } from '@/components/chess/chess'
import ChatPanel from '@/components/public/ChatPanel.vue'
import ContentState from '@/components/public/ContentState.vue'
import EnginePanel from '@/components/public/EnginePanel.vue'
import GameTable from '@/components/public/GameTable.vue'
import StatusPill from '@/components/public/StatusPill.vue'
import StreamIndicator from '@/components/public/StreamIndicator.vue'
import {
  clockLabel,
  engineName,
  errorMessage,
  moveEvaluation,
  moveNps,
  resultLabel,
  statusLabel,
} from '@/components/public/format'
import type {
  ChatMessage,
  ChatSettings,
  ClockState,
  EngineAnalysis,
  GameRecord,
  Identifier,
  LiveSnapshot,
  MoveRecord,
  StreamEnvelope,
  TournamentDetailResponse,
} from '@/components/public/types'

type TabKey = 'standings' | 'games' | 'settings'
type StreamState = 'connecting' | 'live' | 'reconnecting' | 'closed'

interface ClockRuntime {
  activeSide: 'white' | 'black' | null
  running: boolean
  clocksMs: Partial<Record<'white' | 'black', number | null>>
  startedAt: number
}

interface EngineInfoEvent {
  tournament_id?: Identifier
  game_id?: Identifier
  side?: 'white' | 'black'
  engine_data?: EngineAnalysis
  [key: string]: unknown
}

interface ChatEvent {
  tournament_id?: Identifier
  message?: ChatMessage
}

interface ChatDeletedEvent {
  tournament_id?: Identifier
  message_id?: Identifier
}

interface ChatSettingsEvent {
  tournament_id?: Identifier
  settings?: ChatSettings
}

interface ViewportPosition {
  left: number
  top: number
}

const route = useRoute()
const router = useRouter()
const data = ref<TournamentDetailResponse | null>(null)
const loading = ref(true)
const loadError = ref('')
const selectedPly = ref(0)
const currentPositionFen = ref('startpos')
const streamState = ref<StreamState>('closed')
const clockLabels = ref<Record<'white' | 'black', string>>({ white: '--:--', black: '--:--' })
const clockRuntime = ref<ClockRuntime | null>(null)
const headingElement = ref<HTMLElement | null>(null)
const arenaElement = ref<HTMLElement | null>(null)
const boardColumnElement = ref<HTMLElement | null>(null)

let controller: AbortController | null = null
let eventSource: EventSource | null = null
let streamKey = ''
let refreshTimer: number | undefined
let clockFrame: number | undefined
let arenaFitFrame: number | undefined
let skipNextRouteLoad = false
let awaitingNextLiveAfterGameId = ''
let headingResizeObserver: ResizeObserver | null = null
let viewportBeforeUpdate: ViewportPosition | null = null

const tournamentId = computed(() => String(route.params.id || ''))
const routeGameId = computed(() => queryValue(route.query.game_id))
const selectedGameId = computed(() => routeGameId.value || String(data.value?.viewer_game?.id || ''))
const tournamentComplete = computed(() => ['finished', 'aborted'].includes(data.value?.tournament.status || ''))
const activeTab = computed<TabKey>(() => {
  const tab = queryValue(route.query.tab)
  return ['standings', 'games', 'settings'].includes(tab) ? tab as TabKey : 'standings'
})
const viewerGame = computed(() => data.value?.viewer_game || null)
const isSettingUp = computed(() => viewerGame.value?.status === 'assigned')
const pgnDownloadUrl = computed(() => {
  const game = viewerGame.value
  return game?.status === 'finished'
    ? `/api/games/${encodeURIComponent(String(game.id))}/pgn`
    : ''
})
const moves = computed(() => data.value?.viewer_moves || [])
const opening = computed(() => data.value?.opening || { name: 'Start position', fen: 'startpos' })
const isLatestPly = computed(() => selectedPly.value >= moves.value.length)
const format = computed(() => {
  const value = data.value?.tournament.config?.format
  return typeof value === 'string' ? value : value?.value || ''
})
const settingsRows = computed(() => (data.value?.settings || []).map((row) => Array.isArray(row)
  ? { label: String(row[0]), value: String(row[1]) }
  : { label: String(row.label), value: String(row.value) }))
const orderedMessages = computed(() => normalizeMessages(data.value?.chat_messages || []))
const whiteAnalysis = computed(() => analysisForSide('white'))
const blackAnalysis = computed(() => analysisForSide('black'))
const whiteClock = computed(() => clockForSide('white'))
const blackClock = computed(() => clockForSide('black'))
const activeSide = computed<'white' | 'black' | null>(() => {
  if (isLatestPly.value && clockRuntime.value?.running) return clockRuntime.value.activeSide
  if (!viewerGame.value) return null
  return parseFen(currentPositionFen.value).turn === 'w' ? 'white' : 'black'
})

watch(
  () => `${tournamentId.value}:${routeGameId.value}`,
  () => {
    if (awaitingNextLiveAfterGameId && routeGameId.value !== awaitingNextLiveAfterGameId) {
      awaitingNextLiveAfterGameId = ''
    }
    if (skipNextRouteLoad) {
      skipNextRouteLoad = false
      connectStream()
      return
    }
    void loadDetail(false)
  },
  { immediate: true },
)

watch(() => data.value?.tournament.name, (name) => {
  if (name) document.title = `${name} | COPE Chess`
})

watch(loadError, () => scheduleArenaFit(), { flush: 'post' })

watch(headingElement, (next, previous) => {
  if (previous) headingResizeObserver?.unobserve(previous)
  if (next) headingResizeObserver?.observe(next)
  scheduleArenaFit()
}, { flush: 'post' })

watch([arenaElement, boardColumnElement], () => scheduleArenaFit(), { flush: 'post' })

onMounted(() => {
  headingResizeObserver = new ResizeObserver(scheduleArenaFit)
  if (headingElement.value) headingResizeObserver.observe(headingElement.value)
  window.addEventListener('resize', scheduleArenaFit)
  window.visualViewport?.addEventListener('resize', scheduleArenaFit)
  scheduleArenaFit()
})

onBeforeUpdate(() => {
  viewportBeforeUpdate = currentViewportPosition()
})

onUpdated(() => {
  if (!viewportBeforeUpdate) return
  restoreViewportPosition(viewportBeforeUpdate)
  viewportBeforeUpdate = null
})

onBeforeUnmount(() => {
  controller?.abort()
  window.clearTimeout(refreshTimer)
  if (arenaFitFrame !== undefined) window.cancelAnimationFrame(arenaFitFrame)
  headingResizeObserver?.disconnect()
  window.removeEventListener('resize', scheduleArenaFit)
  window.visualViewport?.removeEventListener('resize', scheduleArenaFit)
  stopClock()
  closeStream()
})

function scheduleArenaFit(): void {
  if (arenaFitFrame !== undefined) window.cancelAnimationFrame(arenaFitFrame)
  arenaFitFrame = window.requestAnimationFrame(() => {
    arenaFitFrame = undefined
    void fitArenaToViewport()
  })
}

async function fitArenaToViewport(): Promise<void> {
  await nextTick()
  const arena = arenaElement.value
  const boardColumn = boardColumnElement.value
  if (!arena || !boardColumn) return

  const viewer = boardColumn.firstElementChild as HTMLElement | null
  const board = viewer?.querySelector<HTMLElement>('.board-mount')
  if (!viewer || !board) return

  const visualViewport = window.visualViewport
  const viewportBottom = visualViewport
    ? visualViewport.offsetTop + visualViewport.height
    : window.innerHeight
  const availableHeight = Math.floor(viewportBottom - arena.getBoundingClientRect().top - 8)
  if (availableHeight <= 0) return

  const viewerChrome = Math.max(0, viewer.getBoundingClientRect().height - board.getBoundingClientRect().height)
  const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  const maximumBoardSize = 42 * rootFontSize
  const fittedBoardSize = (chromeHeight: number) => Math.max(
    0,
    Math.min(maximumBoardSize, Math.floor(availableHeight - chromeHeight)),
  )

  const viewportPosition = currentViewportPosition()

  arena.style.setProperty('--arena-content-height', `${availableHeight}px`)
  arena.style.setProperty('--arena-board-size', `${fittedBoardSize(viewerChrome)}px`)

  const settledChrome = Math.max(0, viewer.getBoundingClientRect().height - board.getBoundingClientRect().height)
  arena.style.setProperty('--arena-board-size', `${fittedBoardSize(settledChrome)}px`)
  restoreViewportPosition(viewportPosition)
}

function currentViewportPosition(): ViewportPosition {
  return { left: window.scrollX, top: window.scrollY }
}

function restoreViewportPosition(position: ViewportPosition): void {
  if (window.scrollX === position.left && window.scrollY === position.top) return
  window.scrollTo(position.left, position.top)
}

async function loadDetail(background: boolean): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  if (!background || !data.value) loading.value = true
  if (!background) loadError.value = ''

  const requestedGameId = routeGameId.value || selectedGameId.value
  try {
    const response = await api.get<TournamentDetailResponse>(`/api/tournaments/${encodeURIComponent(tournamentId.value)}`, {
      query: requestedGameId ? { game_id: requestedGameId } : {},
      signal: controller.signal,
    })
    applyDetail(response)
    loadError.value = ''

    if (!routeGameId.value && response.viewer_game) {
      skipNextRouteLoad = true
      await router.replace({
        query: { ...route.query, game_id: String(response.viewer_game.id) },
      })
    }
    connectStream()
  } catch (error) {
    if ((error as { name?: string })?.name !== 'AbortError') {
      loadError.value = errorMessage(error, 'This tournament could not be loaded.')
    }
  } finally {
    loading.value = false
  }
}

function applyDetail(response: TournamentDetailResponse): void {
  const previousGame = data.value?.viewer_game?.id
  const previousLength = data.value?.viewer_moves.length || 0
  const followedLatest = selectedPly.value >= previousLength
  const existingMessages = data.value?.chat_messages || []
  response.chat_messages = mergeMessages(response.chat_messages || [], existingMessages)
  data.value = response

  if (String(previousGame ?? '') !== String(response.viewer_game?.id ?? '') || followedLatest) {
    selectedPly.value = response.viewer_moves.length
  } else {
    selectedPly.value = Math.min(selectedPly.value, response.viewer_moves.length)
  }

  clockLabels.value = {
    white: response.clocks?.white || '--:--',
    black: response.clocks?.black || '--:--',
  }
  if (response.clock_state) applyClockState(response.clock_state, response.clock_state.observed_at || undefined)
  else {
    clockRuntime.value = null
    stopClock()
  }
}

function connectStream(): void {
  if (typeof EventSource === 'undefined' || !data.value) return
  const nextKey = `${tournamentId.value}:${selectedGameId.value}`
  if (eventSource && streamKey === nextKey) return

  closeStream()
  streamKey = nextKey
  streamState.value = 'connecting'
  const query = selectedGameId.value ? `?game_id=${encodeURIComponent(selectedGameId.value)}` : ''
  eventSource = new EventSource(`/tournaments/${encodeURIComponent(tournamentId.value)}/events${query}`)
  eventSource.onopen = () => { streamState.value = 'live' }
  eventSource.onerror = () => { streamState.value = 'reconnecting' }
  eventSource.addEventListener('tournament.snapshot', handleSnapshot)
  eventSource.addEventListener('game.move', handleGameMove)
  eventSource.addEventListener('engine.info', handleEngineInfo)
  eventSource.addEventListener('clock.sync', handleClockSync)
  eventSource.addEventListener('chat.message', handleChatMessage)
  eventSource.addEventListener('chat.deleted', handleChatDeleted)
  eventSource.addEventListener('chat.settings', handleChatSettings)
  eventSource.addEventListener('tournament.changed', scheduleSnapshotRefresh)
  eventSource.addEventListener('tournament.live', scheduleSnapshotRefresh)
}

function closeStream(): void {
  eventSource?.close()
  eventSource = null
  streamKey = ''
  streamState.value = 'closed'
}

function handleSnapshot(event: Event): void {
  const envelope = parseEnvelope<LiveSnapshot>(event)
  if (!envelope) return
  applySnapshot(envelope.data)
}

function handleGameMove(event: Event): void {
  const envelope = parseEnvelope<{ game_id?: Identifier }>(event)
  if (envelope?.data.game_id !== undefined && sameId(envelope.data.game_id, selectedGameId.value)) {
    if (clockRuntime.value) clockRuntime.value = { ...clockRuntime.value, running: false }
    stopClock()
    scheduleSnapshotRefresh()
  }
}

function handleEngineInfo(event: Event): void {
  const envelope = parseEnvelope<EngineInfoEvent>(event)
  const payload = envelope?.data
  if (!payload || !sameId(payload.game_id, selectedGameId.value)) return
  if (payload.side !== 'white' && payload.side !== 'black') return
  if (!data.value) return
  const analysis = payload.engine_data || payload as EngineAnalysis
  data.value.engine_data = {
    ...data.value.engine_data,
    [payload.side]: { ...data.value.engine_data?.[payload.side], ...analysis },
  }
}

function handleClockSync(event: Event): void {
  const envelope = parseEnvelope<ClockState>(event)
  if (!envelope || !sameId(envelope.data.game_id, selectedGameId.value)) return
  applyClockState(envelope.data, envelope.sent_at)
}

function handleChatMessage(event: Event): void {
  const envelope = parseEnvelope<ChatEvent>(event)
  if (!envelope?.data.message || !sameId(envelope.data.tournament_id, tournamentId.value)) return
  appendChatMessage(envelope.data.message)
}

function handleChatDeleted(event: Event): void {
  const envelope = parseEnvelope<ChatDeletedEvent>(event)
  const payload = envelope?.data
  if (!data.value || !payload || !sameId(payload.tournament_id, tournamentId.value)) return
  if (payload.message_id === undefined) return
  data.value.chat_messages = (data.value.chat_messages || []).filter(
    (message) => !sameId(message.id, payload.message_id),
  )
}

function handleChatSettings(event: Event): void {
  const envelope = parseEnvelope<ChatSettingsEvent>(event)
  const payload = envelope?.data
  if (!data.value || !payload?.settings || !sameId(payload.tournament_id, tournamentId.value)) return
  data.value.chat_settings = { ...data.value.chat_settings, ...payload.settings }
}

function applySnapshot(snapshot: LiveSnapshot): void {
  if (!data.value) return
  if (snapshot.tournament) data.value.tournament = { ...data.value.tournament, ...snapshot.tournament }
  if (snapshot.games) data.value.games = mergeGames(data.value.games, snapshot.games)

  const displayedGame = data.value.viewer_game
  const displayedGameUpdate = displayedGame
    ? data.value.games.find((game) => sameId(game.id, displayedGame.id))
    : undefined
  if (
    displayedGame?.status === 'live'
    && displayedGameUpdate?.status === 'finished'
    && sameId(displayedGame.id, selectedGameId.value)
  ) {
    awaitingNextLiveAfterGameId = String(displayedGame.id)
  }

  if (snapshot.game && sameId(snapshot.game.id, selectedGameId.value)) {
    data.value.viewer_game = { ...(data.value.viewer_game || {}), ...snapshot.game } as GameRecord
    if (snapshot.moves) {
      const followedLatest = selectedPly.value >= data.value.viewer_moves.length
      data.value.viewer_moves = snapshot.moves
      if (followedLatest) selectedPly.value = snapshot.moves.length
    }
    if (snapshot.opening) data.value.opening = snapshot.opening
    if (snapshot.engine_data) data.value.engine_data = snapshot.engine_data
    if (snapshot.clocks) {
      data.value.clocks = snapshot.clocks
      clockLabels.value = {
        white: snapshot.clocks.white || '--:--',
        black: snapshot.clocks.black || '--:--',
      }
    }
    if (snapshot.clock_state) applyClockState(snapshot.clock_state, snapshot.clock_state.observed_at || undefined)
  } else if (displayedGameUpdate && sameId(displayedGameUpdate.id, selectedGameId.value)) {
    data.value.viewer_game = { ...displayedGame, ...displayedGameUpdate } as GameRecord
  }
  if (snapshot.standings) data.value.standings = snapshot.standings

  if (awaitingNextLiveAfterGameId && routeGameId.value === awaitingNextLiveAfterGameId) {
    const nextLiveGame = isActiveGame(snapshot.game)
      && !sameId(snapshot.game.id, awaitingNextLiveAfterGameId)
      ? snapshot.game
      : data.value.games.find((game) => isActiveGame(game) && !sameId(game.id, awaitingNextLiveAfterGameId))
    if (nextLiveGame) void followLiveGame(nextLiveGame.id)
  }
}

function isActiveGame(game: GameRecord | null | undefined): game is GameRecord {
  return game?.status === 'assigned' || game?.status === 'live'
}

async function followLiveGame(gameId: Identifier): Promise<void> {
  awaitingNextLiveAfterGameId = ''
  await router.replace({ query: { ...route.query, game_id: String(gameId) } })
}

function scheduleSnapshotRefresh(): void {
  window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(() => { void loadDetail(true) }, 120)
}

function applyClockState(state: ClockState, observedAt?: string): void {
  if (state.game_id !== undefined && !sameId(state.game_id, selectedGameId.value)) return
  const parsedTime = Date.parse(observedAt || state.sent_at || '')
  clockRuntime.value = {
    activeSide: state.active_side || null,
    running: Boolean(state.running),
    clocksMs: state.clocks_ms || {},
    startedAt: Number.isFinite(parsedTime) ? parsedTime : Date.now(),
  }
  stopClock()
  renderClocks()
}

function renderClocks(): void {
  const runtime = clockRuntime.value
  if (!runtime) return
  const elapsed = runtime.running ? Math.max(0, Date.now() - runtime.startedAt) : 0
  const next = { ...clockLabels.value }
  for (const side of ['white', 'black'] as const) {
    let value = runtime.clocksMs[side]
    if (runtime.running && runtime.activeSide === side && value !== null && value !== undefined) {
      value = Math.max(0, value - elapsed)
    }
    if (value !== null && value !== undefined) next[side] = clockLabel(value)
  }
  clockLabels.value = next
  if (runtime.running) clockFrame = window.requestAnimationFrame(renderClocks)
}

function stopClock(): void {
  if (clockFrame !== undefined) window.cancelAnimationFrame(clockFrame)
  clockFrame = undefined
}

function analysisForSide(side: 'white' | 'black'): EngineAnalysis {
  if (isLatestPly.value) return data.value?.engine_data?.[side] || {}
  const moveIndex = latestMoveIndexForSide(side, selectedPly.value)
  const move = moveIndex >= 0 ? moves.value[moveIndex] : undefined
  if (!move) return {}
  const analysis: EngineAnalysis = {
    nps: moveNps(move),
    eval: moveEvaluation(move),
    root_fen: positionFen(buildPositions(
      opening.value.fen,
      moves.value.slice(0, moveIndex).map((item) => item.uci),
    ).at(-1)!),
  }
  if (move.depth !== undefined) analysis.depth = move.depth
  if (move.nodes !== undefined) analysis.nodes = move.nodes
  if (move.pv !== undefined) analysis.pv = move.pv
  const info = move.info_line || move.pv
  if (info !== undefined) analysis.info = info
  return analysis
}

function clockForSide(side: 'white' | 'black'): string {
  if (isLatestPly.value) return clockLabels.value[side]
  return clockLabel(latestMoveForSide(side, selectedPly.value)?.clock_after_ms)
}

function latestMoveForSide(side: 'white' | 'black', ply: number): MoveRecord | undefined {
  const index = latestMoveIndexForSide(side, ply)
  return index >= 0 ? moves.value[index] : undefined
}

function latestMoveIndexForSide(side: 'white' | 'black', ply: number): number {
  for (let index = Math.min(ply, moves.value.length) - 1; index >= 0; index -= 1) {
    if (moveSide(index) === side) return index
  }
  return -1
}

function moveSide(index: number): 'white' | 'black' {
  const first = parseFen(opening.value.fen).turn === 'w' ? 'white' : 'black'
  return index % 2 === 0 ? first : first === 'white' ? 'black' : 'white'
}

function selectGame(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (!value || value === selectedGameId.value) return
  void router.push({ query: { ...route.query, game_id: value } })
}

function gameLabel(game: GameRecord): string {
  const white = engineName(data.value?.engines, game.white_engine_id, game.white_name)
  const black = engineName(data.value?.engines, game.black_engine_id, game.black_name)
  const outcome = game.result ? `, ${game.result}` : `, ${statusLabel(game.status)}`
  return `Round ${game.round ?? '-'}, ${white} vs ${black}${outcome}`
}

function tabTarget(tab: TabKey): RouteLocationRaw {
  return { query: { ...route.query, tab } }
}

function appendChatMessage(message: ChatMessage): void {
  if (!data.value) return
  data.value.chat_messages = mergeMessages(data.value.chat_messages || [], [message])
}

function mergeMessages(first: ChatMessage[], second: ChatMessage[]): ChatMessage[] {
  const result: ChatMessage[] = []
  const seen = new Set<string>()
  for (const message of [...first, ...second]) {
    const key = message.id !== undefined
      ? `id:${message.id}`
      : `${message.at || ''}:${message.display_name}:${message.text}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(message)
  }
  return normalizeMessages(result)
}

function normalizeMessages(messages: ChatMessage[]): ChatMessage[] {
  return [...messages].sort((left, right) => {
    const leftId = Number(left.id)
    const rightId = Number(right.id)
    if (Number.isFinite(leftId) && Number.isFinite(rightId)) return leftId - rightId
    if (left.at && right.at) return Date.parse(left.at) - Date.parse(right.at)
    return 0
  })
}

function mergeGames(existing: GameRecord[], incoming: GameRecord[]): GameRecord[] {
  const byId = new Map(existing.map((game) => [String(game.id), game]))
  return incoming.map((game) => ({ ...byId.get(String(game.id)), ...game } as GameRecord))
}

function parseEnvelope<T>(event: Event): StreamEnvelope<T> | null {
  try {
    return JSON.parse((event as MessageEvent<string>).data) as StreamEnvelope<T>
  } catch {
    return null
  }
}

function sameId(left: Identifier | null | undefined, right: Identifier | null | undefined): boolean {
  return left !== undefined && left !== null && right !== undefined && right !== null && String(left) === String(right)
}

function queryValue(value: unknown): string {
  return Array.isArray(value) ? String(value[0] || '') : typeof value === 'string' ? value : ''
}
</script>

<template>
  <div class="page-container tournament-page">
    <ContentState v-if="loading && !data" kind="loading" title="Loading tournament" />
    <ContentState v-else-if="loadError && !data" kind="error" :message="loadError" action-label="Try again" @action="loadDetail(false)" />

    <template v-else-if="data">
      <header ref="headingElement" class="tournament-heading">
        <div class="tournament-heading__title">
          <div class="title-line">
            <h1>{{ data.tournament.name }}</h1>
            <StatusPill :status="data.tournament.status" />
          </div>
          <p>
            {{ format ? statusLabel(format) : 'Tournament' }}
            <template v-if="data.tournament.current_round"> / Round {{ data.tournament.current_round }}</template>
            <template v-if="viewerGame"> / {{ resultLabel(viewerGame.result) }}</template>
          </p>
        </div>

        <div class="tournament-heading__controls">
          <a
            v-if="pgnDownloadUrl"
            class="pgn-download"
            :href="pgnDownloadUrl"
            download
          >
            Download PGN
          </a>
          <label v-if="data.games.length" class="game-picker">
            <span class="game-picker__heading">
              <span>Selected game</span>
              <StreamIndicator v-if="!tournamentComplete" :state="streamState" />
            </span>
            <select :value="selectedGameId" @change="selectGame">
              <option v-for="game in data.games" :key="game.id" :value="String(game.id)">{{ gameLabel(game) }}</option>
            </select>
          </label>
        </div>
      </header>

      <p v-if="loadError" class="inline-error" role="alert">{{ loadError }} <button type="button" @click="loadDetail(true)">Try again</button></p>

      <section ref="arenaElement" v-if="viewerGame && !isSettingUp" class="arena" :aria-label="`${engineName(data.engines, viewerGame.white_engine_id, viewerGame.white_name)} versus ${engineName(data.engines, viewerGame.black_engine_id, viewerGame.black_name)}`">
        <div class="engine-column">
          <EnginePanel
            side="black"
            :name="engineName(data.engines, viewerGame.black_engine_id, viewerGame.black_name)"
            :engine-id="viewerGame.black_engine_id"
            :clock="blackClock"
            :analysis="blackAnalysis"
            :position-fen="currentPositionFen"
            :active="activeSide === 'black'"
          />
          <EnginePanel
            side="white"
            :name="engineName(data.engines, viewerGame.white_engine_id, viewerGame.white_name)"
            :engine-id="viewerGame.white_engine_id"
            :clock="whiteClock"
            :analysis="whiteAnalysis"
            :position-fen="currentPositionFen"
            :active="activeSide === 'white'"
          />
          <dl class="game-facts">
            <div><dt>Round</dt><dd>{{ viewerGame.round ?? '-' }}</dd></div>
            <div><dt>Status</dt><dd>{{ statusLabel(viewerGame.status) }}</dd></div>
            <div><dt>Result</dt><dd>{{ resultLabel(viewerGame.result) }}</dd></div>
            <div><dt>Termination</dt><dd>{{ viewerGame.termination ? statusLabel(viewerGame.termination) : '-' }}</dd></div>
          </dl>
        </div>

        <div ref="boardColumnElement" class="board-column">
          <ChessViewer
            :opening="opening"
            :moves="moves"
            :model-value="selectedPly"
            :label="`${engineName(data.engines, viewerGame.white_engine_id, viewerGame.white_name)} versus ${engineName(data.engines, viewerGame.black_engine_id, viewerGame.black_name)} replay`"
            @update:model-value="selectedPly = $event"
            @position="currentPositionFen = $event.fen"
          />
        </div>

        <aside class="activity-column" aria-label="Game activity">
          <MoveList
            class="arena-moves"
            :moves="moves.map((move) => move.san || move.uci)"
            :uci-moves="moves.map((move) => move.uci)"
            :fen="opening.fen"
            :model-value="selectedPly"
            @update:model-value="selectedPly = $event"
          />
          <ChatPanel
            class="arena-chat"
            :messages="orderedMessages"
            :settings="data.chat_settings || {}"
            :tournament-id="data.tournament.id"
            @sent="appendChatMessage"
          />
        </aside>
      </section>

      <section v-else-if="viewerGame" class="setup-arena" aria-labelledby="setup-title">
        <article class="setup-card">
          <div class="setup-card__indicator" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>
          <h2 id="setup-title">Preparing the game environment</h2>
          <div class="setup-card__engines" aria-label="Engines being prepared">
            <RouterLink :to="`/engines/${viewerGame.white_engine_id}`">
              <span>White</span>
              <strong>{{ engineName(data.engines, viewerGame.white_engine_id, viewerGame.white_name) }}</strong>
            </RouterLink>
            <span class="setup-card__versus">vs</span>
            <RouterLink :to="`/engines/${viewerGame.black_engine_id}`">
              <span>Black</span>
              <strong>{{ engineName(data.engines, viewerGame.black_engine_id, viewerGame.black_name) }}</strong>
            </RouterLink>
          </div>
          <dl class="setup-card__facts">
            <div><dt>Round</dt><dd>{{ viewerGame.round ?? '-' }}</dd></div>
            <div><dt>Game</dt><dd>{{ viewerGame.id }}</dd></div>
            <div><dt>Status</dt><dd>Setting up</dd></div>
          </dl>
        </article>
        <ChatPanel
          class="setup-chat"
          :messages="orderedMessages"
          :settings="data.chat_settings || {}"
          :tournament-id="data.tournament.id"
          @sent="appendChatMessage"
        />
      </section>

      <section v-else class="empty-arena">
        <ContentState kind="empty" compact title="No game selected" />
        <ChatPanel class="empty-chat" :messages="orderedMessages" :settings="data.chat_settings || {}" :tournament-id="data.tournament.id" @sent="appendChatMessage" />
      </section>

      <section class="tournament-data">
        <nav class="data-tabs" aria-label="Tournament information">
          <RouterLink :to="tabTarget('standings')" :aria-current="activeTab === 'standings' ? 'page' : undefined">Standings <span>{{ data.standings?.length || 0 }}</span></RouterLink>
          <RouterLink :to="tabTarget('games')" :aria-current="activeTab === 'games' ? 'page' : undefined">Games <span>{{ data.games.length }}</span></RouterLink>
          <RouterLink :to="tabTarget('settings')" :aria-current="activeTab === 'settings' ? 'page' : undefined">Settings</RouterLink>
        </nav>

        <section v-if="activeTab === 'standings'" class="data-panel" aria-labelledby="standings-title">
          <header><div><h2 id="standings-title">Standings</h2></div></header>
          <div v-if="data.standings?.length" class="table-wrap">
            <table>
              <thead><tr><th>Rank</th><th>Engine</th><th>Points</th><th>Played</th><th v-if="format === 'swiss'">Buchholz</th><th v-if="format === 'knockout'">Stage</th><th><span class="sr-only">View engine</span></th></tr></thead>
              <tbody>
                <tr v-for="(standing, index) in data.standings" :key="standing.engine_id">
                  <td class="rank-cell">{{ index + 1 }}</td>
                  <td><RouterLink :to="`/engines/${standing.engine_id}`">{{ standing.name }}</RouterLink></td>
                  <td class="number-cell">{{ standing.points }}</td>
                  <td class="number-cell">{{ standing.played }}</td>
                  <td v-if="format === 'swiss'" class="number-cell">{{ standing.buchholz ?? 0 }}</td>
                  <td v-if="format === 'knockout'" class="number-cell">{{ standing.stage ?? 0 }}</td>
                  <td class="action-cell"><RouterLink :to="`/engines/${standing.engine_id}`" :aria-label="`View ${standing.name}`">View</RouterLink></td>
                </tr>
              </tbody>
            </table>
          </div>
          <ContentState v-else kind="empty" compact title="No standings yet" />
        </section>

        <section v-else-if="activeTab === 'games'" class="data-panel" aria-labelledby="games-title">
          <header><div><h2 id="games-title">All games</h2></div></header>
          <GameTable v-if="data.games.length" :games="data.games" :engines="data.engines" caption="Tournament games" />
          <ContentState v-else kind="empty" compact title="No games scheduled" />
        </section>

        <section v-else class="data-panel settings-panel" aria-labelledby="settings-title">
          <header><div><h2 id="settings-title">Settings</h2></div></header>
          <dl v-if="settingsRows.length" class="settings-list">
            <div v-for="row in settingsRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
          </dl>
          <ContentState v-else kind="empty" compact title="No settings recorded" />

          <div v-if="data.engine_hardware?.length" class="hardware-section">
            <h3>Engine hardware</h3>
            <div class="table-wrap">
              <table>
                <thead><tr><th>Engine</th><th>Hash</th><th>Threads</th><th>Active hardware</th></tr></thead>
                <tbody>
                  <tr v-for="row in data.engine_hardware" :key="row.engine_id">
                    <td><RouterLink :to="`/engines/${row.engine_id}`">{{ row.name }}</RouterLink></td>
                    <td>{{ row.hash || '-' }}</td>
                    <td>{{ row.threads || '-' }}</td>
                    <td>{{ row.hardware || 'Not reported' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </section>
    </template>
  </div>
</template>

<style scoped>
.tournament-page {
  --arena-board-size: clamp(30rem, calc(100dvh - 15rem), 42rem);
  --arena-content-height: calc(var(--arena-board-size) + 6.35rem);
  position: relative;
  display: grid;
  overflow-anchor: none;
  width: 100%;
  gap: var(--space-md, 1rem);
  padding-inline: clamp(0.75rem, 1.5vw, 1.75rem);
  padding-block: 0.55rem 3rem;
}

.tournament-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-xl, 2rem);
  padding-block-end: 0.55rem;
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.tournament-heading__title {
  display: grid;
  align-items: center;
}

.title-line {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 0.5rem);
}

.tournament-heading h1,
.tournament-heading p,
.game-facts {
  margin: 0;
}

.tournament-heading h1 {
  max-width: 54rem;
  font-size: clamp(1.45rem, 2.7vw, 2.15rem);
  letter-spacing: -0.035em;
  line-height: 1.05;
}

.tournament-heading__title > p {
  margin-block-start: 0.18rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.75rem;
}

.tournament-heading__controls {
  display: flex;
  align-items: end;
  gap: 0.65rem;
}

.pgn-download {
  display: inline-flex;
  min-height: 2.35rem;
  align-items: center;
  padding-inline: 0.8rem;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-sm, 0.35rem);
  color: var(--color-text-muted, #607080);
  font-size: 0.72rem;
  font-weight: 730;
  text-decoration: none;
  white-space: nowrap;
}

.pgn-download:hover {
  border-color: var(--color-border-strong, #99a8bb);
  color: var(--color-text, #17202a);
  background: color-mix(in srgb, var(--color-text, #17202a) 4%, transparent);
}

.tournament-heading__controls label {
  display: grid;
  gap: 0.25rem;
  min-width: min(27rem, 42vw);
  color: var(--color-text-muted, #607080);
  font-size: 0.64rem;
  font-weight: 700;
}

.game-picker__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.game-picker__heading > span:first-child {
  color: var(--color-text-muted, #607080);
}

.game-picker__heading :deep(.stream-indicator) {
  font-size: 0.64rem;
  font-weight: 650;
}

.game-picker__heading :deep(.stream-indicator > span) {
  width: 0.4rem;
  height: 0.4rem;
}

.tournament-heading select {
  width: 100%;
  min-height: 2.35rem;
  padding: 0.4rem 2rem 0.4rem 0.65rem;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-surface, #fff);
  color: var(--color-text, #17202a);
  font: inherit;
  font-size: 0.77rem;
}

.tournament-heading select:focus {
  border-color: var(--color-accent, #2f78c4);
  outline: 2px solid color-mix(in srgb, var(--color-accent, #2f78c4) 20%, transparent);
}

.inline-error {
  margin: 0;
  padding: 0.65rem 0.8rem;
  border: 1px solid color-mix(in srgb, var(--color-danger, #b42318) 25%, transparent);
  border-radius: var(--radius-sm, 0.35rem);
  background: color-mix(in srgb, var(--color-danger, #b42318) 7%, transparent);
  color: var(--color-danger, #b42318);
  font-size: 0.75rem;
}

.inline-error button {
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  font-weight: 750;
  text-decoration: underline;
  cursor: pointer;
}

.arena {
  display: grid;
  grid-template-columns: minmax(25rem, 29rem) var(--arena-board-size) minmax(28rem, 1fr);
  gap: clamp(0.7rem, 1.5vw, 1.2rem);
  align-items: start;
  height: var(--arena-content-height);
  min-height: 0;
}

.engine-column,
.activity-column {
  display: grid;
  min-height: 0;
  gap: var(--space-sm, 0.5rem);
}

.engine-column {
  grid-template-rows: repeat(2, minmax(0, 1fr)) auto;
  height: var(--arena-content-height);
}

.board-column {
  width: var(--arena-board-size);
  min-width: 0;
  justify-self: center;
}

.activity-column {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: minmax(0, 1fr);
  height: var(--arena-content-height);
}

.activity-column > * {
  min-width: 0;
  min-height: 0;
  height: 100%;
}

.game-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: 1px;
  height: 6.35rem;
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-border, #d5dbe1);
}

.game-facts div {
  min-width: 0;
  padding: 0.65rem 0.75rem;
  background: var(--color-surface, #fff);
}

.game-facts dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.59rem;
  font-weight: 750;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.game-facts dd {
  overflow: hidden;
  margin: 0.18rem 0 0;
  font-size: 0.75rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-arena {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(18rem, 0.36fr);
  gap: var(--space-md, 1rem);
  height: min(36rem, calc(100dvh - 8rem));
  min-height: 0;
}

.empty-arena > * {
  min-height: 0;
}

.setup-arena {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(20rem, 0.55fr);
  gap: clamp(0.7rem, 1.5vw, 1.2rem);
  min-height: min(36rem, calc(100dvh - 13rem));
}

.setup-card {
  display: grid;
  align-content: center;
  justify-items: center;
  padding: clamp(2rem, 6vw, 5rem);
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-lg, 0.75rem);
  background:
    radial-gradient(circle at 50% 15%, color-mix(in srgb, var(--color-accent, #2f78c4) 10%, transparent), transparent 42%),
    var(--color-surface, #fff);
  text-align: center;
}

.setup-card__indicator {
  display: flex;
  gap: 0.38rem;
  margin-block-end: 1.1rem;
}

.setup-card__indicator span {
  width: 0.58rem;
  height: 0.58rem;
  border-radius: 50%;
  background: var(--color-accent, #2f78c4);
  animation: setup-pulse 1.35s ease-in-out infinite;
}

.setup-card__indicator span:nth-child(2) { animation-delay: 0.15s; }
.setup-card__indicator span:nth-child(3) { animation-delay: 0.3s; }

.setup-card h2,
.setup-card__facts {
  margin: 0;
}

.setup-card h2 {
  max-width: 42rem;
  margin-block-start: 0.45rem;
  font-size: clamp(1.35rem, 2.5vw, 2rem);
  letter-spacing: -0.025em;
}

.setup-card__engines {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  width: min(100%, 48rem);
  gap: 0.8rem;
  margin-block-start: 1.6rem;
}

.setup-card__engines a {
  display: grid;
  gap: 0.22rem;
  min-width: 0;
  padding: 0.9rem 1rem;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface-raised, var(--color-surface, #fff));
  color: inherit;
  text-decoration: none;
}

.setup-card__engines a:hover { border-color: var(--color-border-strong, #99a8bb); }
.setup-card__engines a > span { color: var(--color-text-muted, #607080); font-size: 0.6rem; font-weight: 750; text-transform: uppercase; }
.setup-card__engines strong { overflow: hidden; font-size: 0.88rem; text-overflow: ellipsis; white-space: nowrap; }
.setup-card__versus { color: var(--color-text-muted, #607080); font-size: 0.7rem; font-weight: 800; text-transform: uppercase; }

.setup-card__facts {
  display: flex;
  gap: 1.5rem;
  margin-block-start: 1.35rem;
}

.setup-card__facts div { display: grid; gap: 0.15rem; }
.setup-card__facts dt { color: var(--color-text-muted, #607080); font-size: 0.58rem; font-weight: 750; letter-spacing: 0.045em; text-transform: uppercase; }
.setup-card__facts dd { margin: 0; font-size: 0.76rem; font-weight: 750; }
.setup-chat { min-height: 0; }

@keyframes setup-pulse {
  0%, 60%, 100% { opacity: 0.35; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-0.25rem); }
}

.tournament-data {
  display: grid;
  gap: var(--space-sm, 0.5rem);
  margin-block-start: var(--space-md, 1rem);
}

.data-tabs {
  display: flex;
  gap: 0.3rem;
  overflow-x: auto;
}

.data-tabs a {
  display: inline-flex;
  min-height: 2.35rem;
  align-items: center;
  gap: 0.45rem;
  padding-inline: 0.85rem;
  border: 1px solid transparent;
  border-radius: var(--radius-sm, 0.35rem);
  color: var(--color-text-muted, #607080);
  font-size: 0.78rem;
  font-weight: 730;
  text-decoration: none;
  white-space: nowrap;
}

.data-tabs a:hover { color: var(--color-text, #17202a); background: color-mix(in srgb, var(--color-text, #17202a) 5%, transparent); }
.data-tabs a[aria-current='page'] { border-color: color-mix(in srgb, var(--color-accent, #2f78c4) 24%, transparent); background: color-mix(in srgb, var(--color-accent, #2f78c4) 9%, var(--color-surface, #fff)); color: var(--color-accent, #2f78c4); }
.data-tabs a span { color: inherit; font-size: 0.64rem; opacity: 0.75; }

.data-panel {
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-lg, 0.75rem);
  background: var(--color-surface, #fff);
}

.data-panel > header {
  padding: var(--space-md, 1rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.data-panel h2,
.data-panel header p,
.hardware-section h3 {
  margin: 0;
}

.data-panel h2 { font-size: 1rem; }
.data-panel header p { margin-block-start: 0.18rem; color: var(--color-text-muted, #607080); font-size: 0.7rem; }

.table-wrap { overflow-x: auto; }
.data-panel table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.data-panel th,
.data-panel td { padding: 0.72rem 0.85rem; border-block-end: 1px solid var(--color-border, #d5dbe1); text-align: start; }
.data-panel th { color: var(--color-text-muted, #607080); font-size: 0.63rem; letter-spacing: 0.04em; text-transform: uppercase; white-space: nowrap; }
.data-panel tbody tr:last-child td { border-block-end: 0; }
.data-panel tbody tr:hover { background: color-mix(in srgb, var(--color-accent, #2f78c4) 4.5%, transparent); }
.data-panel td a { color: inherit; font-weight: 700; text-decoration: none; }
.data-panel td a:hover { color: var(--color-accent, #2f78c4); text-decoration: underline; text-underline-offset: 0.16em; }
.rank-cell { width: 4rem; color: var(--color-text-muted, #607080); font-variant-numeric: tabular-nums; }
.number-cell { width: 6rem; font-weight: 730; font-variant-numeric: tabular-nums; }
.action-cell { width: 4rem; text-align: end !important; }
.action-cell a { color: var(--color-accent, #2f78c4) !important; font-size: 0.72rem; }

.settings-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: 1px;
  margin: 0;
  background: var(--color-border, #d5dbe1);
}

.settings-list div {
  min-width: 0;
  padding: 0.85rem 1rem;
  background: var(--color-surface, #fff);
}

.settings-list dt { color: var(--color-text-muted, #607080); font-size: 0.62rem; font-weight: 750; letter-spacing: 0.04em; text-transform: uppercase; }
.settings-list dd { margin: 0.22rem 0 0; font-size: 0.8rem; font-weight: 650; overflow-wrap: anywhere; }

.hardware-section { border-block-start: 1px solid var(--color-border, #d5dbe1); }
.hardware-section h3 { padding: 0.85rem 1rem; border-block-end: 1px solid var(--color-border, #d5dbe1); font-size: 0.88rem; }

@media (max-width: 96rem) {
  .arena { grid-template-columns: minmax(25rem, 1fr) var(--arena-board-size); height: auto; }
  .engine-column { grid-column: 1; grid-row: 1; }
  .board-column { grid-column: 2; grid-row: 1; }
  .activity-column { grid-column: 1 / -1; grid-row: 2; grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: minmax(24rem, 34rem); height: min(34rem, calc(100dvh - 8rem)); }
}

@media (max-width: 58rem) {
  .tournament-heading { align-items: stretch; flex-direction: column; }
  .tournament-heading__controls { justify-content: space-between; }
  .tournament-heading__controls label { min-width: 0; flex: 1; }
  .arena { grid-template-columns: 1fr; }
  .engine-column { grid-column: 1; grid-row: 2; grid-template-columns: 1fr 1fr; grid-template-rows: auto auto; height: auto; }
  .engine-column .game-facts { grid-column: 1 / -1; }
  .board-column { grid-column: 1; grid-row: 1; width: min(100%, var(--arena-board-size)); }
  .activity-column { grid-column: 1; grid-row: 3; }
  .setup-arena { grid-template-columns: 1fr; }
  .setup-chat { min-height: 24rem; }
}

@media (max-width: 40rem) {
  .tournament-heading__controls { align-items: stretch; flex-direction: column-reverse; }
  .engine-column { grid-template-columns: 1fr; }
  .engine-column .game-facts { grid-column: 1; }
  .activity-column { grid-template-columns: 1fr; grid-template-rows: minmax(12rem, 19rem) minmax(18rem, 26rem); }
  .empty-arena { grid-template-columns: 1fr; height: auto; }
  .empty-chat { height: min(36rem, calc(100dvh - 8rem)); }
  .setup-card { padding: 2rem 1rem; }
  .setup-card__engines { grid-template-columns: 1fr; }
  .setup-card__versus { padding-block: 0.1rem; }
  .settings-list { grid-template-columns: 1fr; }
}
</style>
