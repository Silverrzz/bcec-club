from __future__ import annotations

import asyncio
import contextlib
import copy
import hmac
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from cope.db import (
    DEFAULT_DB_PATH,
    ChatSettingsRecord,
    GameRecord,
    MoveRecord,
    TournamentRecord,
    active_engine_hardware_profiles,
    category_tournament_count,
    connect_database,
    create_category,
    create_chat_message,
    create_engine,
    create_opening_suite,
    create_tournament,
    create_worker,
    database_stats,
    delete_category,
    delete_chat_message,
    delete_engine,
    delete_opening_suite,
    delete_tournament,
    delete_worker,
    engine_game_count,
    get_category,
    get_chat_settings,
    get_engine,
    get_engine_record,
    get_opening_position,
    get_opening_suite,
    get_tournament,
    get_tournament_rating_commit,
    get_worker,
    get_worker_activity,
    list_categories,
    list_chat_messages,
    list_active_games,
    list_engine_games,
    list_engine_records,
    list_engines,
    list_games_by_status,
    list_games,
    list_moves,
    list_opening_suites,
    list_rating_rows,
    list_suite_openings,
    list_tournaments,
    list_tournament_matches,
    list_uncommitted_finished_tournaments,
    list_upcoming_games,
    list_workers,
    mint_worker_token_for_worker,
    next_engine_id,
    replace_suite_openings,
    request_tournament_rating_commit,
    revoke_worker,
    set_tournament_status,
    suite_opening_count,
    update_category,
    update_chat_settings,
    update_engine,
    update_opening_suite,
    update_tournament,
    update_worker_label,
)
from cope.core.models import EngineSpec, HardwareInfo, TournamentFormat
from cope.core.stream import (
    StreamEnvelope,
    StreamProtocolError,
    decode_stream_event,
    encode_stream_event,
    make_stream_event,
    sse_stream_event,
)
from cope.network import (
    ADMIN_TOKEN_ENV,
    LOCAL_EVENT_PUBLISHERS,
    default_admin_token,
    default_web_event_token,
    default_worker_server_url,
)
from cope.web import forms
from cope.web.forms import FormError, form_flag, form_value
from cope.web.openings import parse_opening_uploads, parse_openings
from cope.web.requests import read_form, read_form_with_files


PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

# Valid admin actions on a tournament, per current status.
TOURNAMENT_ACTIONS: dict[str, dict[str, str]] = {
    "draft": {"schedule": "scheduled"},
    "scheduled": {"pause": "paused", "abort": "aborted"},
    "running": {"pause": "paused", "abort": "aborted"},
    "paused": {"resume": "scheduled", "abort": "aborted"},
}
CONNECTED_WORKER_STATUSES = {"connected", "building", "ready", "busy"}
WORKER_RECENT_SECONDS = 60


class StreamBacklogExceeded(RuntimeError):
    pass


class StreamSubscription:
    def __init__(self, topics: tuple[str, ...], *, max_queue: int) -> None:
        self.topics = topics
        self.queue: asyncio.Queue[StreamEnvelope | None] = asyncio.Queue(maxsize=max_queue)
        self.closed = False

    def enqueue(self, event: StreamEnvelope) -> None:
        if self.closed:
            return
        if self.queue.full():
            self.closed = True
            while not self.queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()
            self.queue.put_nowait(None)
            return
        self.queue.put_nowait(event)


class StreamHub:
    def __init__(self, *, max_subscribers: int = 256, max_queue: int = 512) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._seq_by_topic: dict[str, int] = {}
        self._subscribers: dict[str, set[StreamSubscription]] = {}
        self._internal_clients: set[asyncio.Queue[StreamEnvelope | None]] = set()
        self._tournament_live: dict[int, dict[str, Any]] = {}
        self._max_subscribers = max_subscribers
        self._max_queue = max_queue

    def bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            self._loop = loop

    def subscribe(self, *topics: str) -> StreamSubscription:
        with self._lock:
            count = sum(len(items) for items in self._subscribers.values())
            if count >= self._max_subscribers:
                raise StreamBacklogExceeded("too many stream subscribers")
            subscription = StreamSubscription(tuple(topics), max_queue=self._max_queue)
            for topic in topics:
                self._subscribers.setdefault(topic, set()).add(subscription)
            return subscription

    def unsubscribe(self, subscription: StreamSubscription) -> None:
        with self._lock:
            subscription.closed = True
            for topic in subscription.topics:
                subscribers = self._subscribers.get(topic)
                if subscribers is None:
                    continue
                subscribers.discard(subscription)
                if not subscribers:
                    self._subscribers.pop(topic, None)

    def register_internal_client(self) -> asyncio.Queue[StreamEnvelope | None]:
        queue: asyncio.Queue[StreamEnvelope | None] = asyncio.Queue(maxsize=self._max_queue)
        with self._lock:
            self._internal_clients.add(queue)
        return queue

    def unregister_internal_client(self, queue: asyncio.Queue[StreamEnvelope | None]) -> None:
        with self._lock:
            self._internal_clients.discard(queue)

    def publish(
        self,
        topic: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        source: str = "web",
    ) -> StreamEnvelope:
        with self._lock:
            seq = self._seq_by_topic.get(topic, 0) + 1
            self._seq_by_topic[topic] = seq
            event = make_stream_event(
                topic,
                event_type,
                data,
                source=source,
                seq=seq,
                event_id=f"{topic}:{seq}",
            )
            self._record_live_event(event)
            subscribers = tuple(self._subscribers.get(topic, ()))
            loop = self._loop
        if loop is None:
            return event
        for subscription in subscribers:
            loop.call_soon_threadsafe(subscription.enqueue, event)
        return event

    def make_private_event(
        self,
        topic: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        source: str = "web",
    ) -> StreamEnvelope:
        return make_stream_event(
            topic,
            event_type,
            data,
            source=source,
            seq=0,
            event_id=f"{topic}:0",
        )

    def publish_to_internal(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> StreamEnvelope:
        event = self.publish("runner", event_type, data, source="web")
        with self._lock:
            clients = tuple(self._internal_clients)
            loop = self._loop
        if loop is None:
            return event
        for queue in clients:
            loop.call_soon_threadsafe(_enqueue_internal_event, queue, event)
        return event

    def tournament_live(self, tournament_id: int) -> dict[str, Any] | None:
        with self._lock:
            live = self._tournament_live.get(tournament_id)
            if live is None:
                return None
            return copy.deepcopy(live)

    def clear_tournament_live(self, tournament_id: int) -> None:
        with self._lock:
            self._tournament_live.pop(tournament_id, None)

    def _record_live_event(self, event: StreamEnvelope) -> None:
        tournament_id = _event_tournament_id(event)
        if tournament_id is None:
            return
        if event.type == "game.move":
            self._tournament_live.pop(tournament_id, None)
            return
        if event.type == "tournament.live":
            live = event.data.get("live")
            if isinstance(live, dict):
                if live.get("clear"):
                    self._tournament_live.pop(tournament_id, None)
                else:
                    self._tournament_live[tournament_id] = dict(live)
            return
        if event.type == "engine.info":
            side = event.data.get("side")
            engine_data = event.data.get("engine_data")
            game_id = event.data.get("game_id")
            if side not in {"white", "black"} or not isinstance(engine_data, dict):
                return
            live = self._tournament_live.setdefault(
                tournament_id,
                {"game_id": game_id, "engine_data": {}, "clocks": {}},
            )
            live["game_id"] = game_id
            live.setdefault("engine_data", {})[side] = dict(engine_data)
            return
        if event.type == "clock.sync":
            clocks = event.data.get("clocks_ms")
            game_id = event.data.get("game_id")
            if not isinstance(clocks, dict):
                return
            live = self._tournament_live.setdefault(
                tournament_id,
                {"game_id": game_id, "engine_data": {}, "clocks": {}},
            )
            live["game_id"] = game_id
            live["clocks"] = dict(clocks)


def _enqueue_internal_event(
    queue: asyncio.Queue[StreamEnvelope | None],
    event: StreamEnvelope,
) -> None:
    if queue.full():
        while not queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        queue.put_nowait(None)
        return
    queue.put_nowait(event)


def create_app(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    worker_server_url: str | None = None,
    event_token: str | None = None,
    admin_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="COPE Chess")
    app.state.db_path = Path(db_path)
    app.state.worker_server_url = worker_server_url or default_worker_server_url()
    app.state.event_token = event_token or default_web_event_token()
    app.state.admin_token = admin_token or default_admin_token()
    app.state.stream_hub = StreamHub()
    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_DIR / "static")),
        name="static",
    )

    @app.middleware("http")
    async def admin_security(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/admin") or path == "/admin/login":
            return await call_next(request)
        token = _admin_token(request)
        if not token:
            return HTMLResponse(
                f"Admin access requires {ADMIN_TOKEN_ENV}.",
                status_code=503,
            )
        if not _request_is_secure_or_local(request):
            return HTMLResponse("Admin access requires HTTPS.", status_code=403)
        if not _admin_session_valid(request, token):
            if request.method == "GET":
                return RedirectResponse(url="/admin/login", status_code=303)
            return HTMLResponse("Admin session required.", status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            await request.body()
            form = await request.form()
            supplied = str(form.get("csrf_token") or "")
            if not _csrf_token_valid(request, token, supplied):
                return HTMLResponse("CSRF validation failed.", status_code=403)
        response = await call_next(request)
        if request.method == "POST" and 200 <= response.status_code < 400:
            _publish_admin_post_streams(request)
        return response

    @app.get("/admin/login")
    def admin_login(request: Request):
        token = _admin_token(request)
        if not token:
            return HTMLResponse(
                f"Admin access requires {ADMIN_TOKEN_ENV}.",
                status_code=503,
            )
        if not _request_is_secure_or_local(request):
            return HTMLResponse("Admin access requires HTTPS.", status_code=403)
        if _admin_session_valid(request, token):
            return RedirectResponse(url="/admin", status_code=303)
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {
                "error": request.query_params.get("error"),
            },
        )

    @app.post("/admin/login")
    async def admin_login_submit(request: Request):
        token = _admin_token(request)
        if not token:
            return HTMLResponse(
                f"Admin access requires {ADMIN_TOKEN_ENV}.",
                status_code=503,
            )
        if not _request_is_secure_or_local(request):
            return HTMLResponse("Admin access requires HTTPS.", status_code=403)
        form = await read_form(request)
        if not hmac.compare_digest(form_value(form, "token"), token):
            return RedirectResponse(
                url="/admin/login?error=" + quote("Invalid admin token."),
                status_code=303,
            )
        response = RedirectResponse(url="/admin", status_code=303)
        nonce = secrets.token_urlsafe(32)
        response.set_cookie(
            "cope_admin_session",
            _signed_value(token, nonce),
            httponly=True,
            secure=_request_is_secure(request),
            samesite="lax",
        )
        return response

    @app.post("/admin/logout")
    def admin_logout():
        response = RedirectResponse(url="/admin/login", status_code=303)
        response.delete_cookie("cope_admin_session")
        return response

    # ------------------------------------------------------------------
    # Public site
    # ------------------------------------------------------------------

    @app.post("/chat")
    async def post_chat_message(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        next_url = _safe_redirect_target(form_value(form, "next"), "/#chat")
        message = _create_chat_message_from_form(connection, form)
        if _wants_json(request):
            return JSONResponse({"ok": True, "message": message})
        return RedirectResponse(url=next_url, status_code=303)

    @app.post("/tournaments/{tournament_id}/chat")
    async def post_tournament_chat_message(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_tournament(connection, tournament_id) is None:
            raise HTTPException(status_code=404, detail="tournament not found")

        form = await read_form(request)
        message = _create_chat_message_from_form(connection, form)
        if _wants_json(request):
            return JSONResponse({"ok": True, "message": message})
        return RedirectResponse(url=f"/tournaments/{tournament_id}#chat", status_code=303)

    @app.get("/tournaments")
    def tournaments(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        return templates.TemplateResponse(
            request,
            "tournaments.html",
            _tournament_index_context(request, connection),
        )

    @app.get("/")
    def home(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engines = _engine_names(connection)
        return templates.TemplateResponse(
            request,
            "live.html",
            {
                "active_nav": None,
                "live_games": _home_game_cards(connection, engines),
                "upcoming_rows": _upcoming_rows(connection, engines, limit=16),
                "recent_games": list_games_by_status(connection, "finished", limit=16),
                "engines": engines,
                "tournament_names": _tournament_names(connection),
            },
        )

    @app.get("/tournaments/{tournament_id}")
    def tournament_detail(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")

        engines = _engine_names(connection)
        games = list_games(connection, tournament.id)
        viewer_game = _selected_viewer_game(request, games)
        viewer_moves = list_moves(connection, viewer_game.id) if viewer_game else ()
        viewer_locked = (
            request.query_params.get("game_id") is not None
            and viewer_game is not None
            and viewer_game.status not in {"assigned", "live"}
        )
        chat_messages = list_chat_messages(connection, limit=30)
        return templates.TemplateResponse(
            request,
            "tournament_detail.html",
            {
                "active_nav": "tournaments",
                "tournament": tournament,
                "games": games,
                "engines": engines,
                "viewer_game": viewer_game,
                "viewer_moves": viewer_moves,
                "viewer_move_payloads": [_move_payload(move) for move in viewer_moves],
                "viewer_locked": viewer_locked,
                "engine_data": _engine_data(viewer_game, viewer_moves),
                "clocks": _clock_data(viewer_moves),
                "standings": _standings(connection, tournament, games, engines),
                "settings": _settings_view(connection, tournament),
                "engine_hardware": _engine_hardware_view(connection, tournament),
                "chat_messages": chat_messages,
                "opening": _opening_view(connection, viewer_game.opening_id) if viewer_game else None,
            },
        )

    @app.get("/tournaments/{tournament_id}/live.json")
    def tournament_live_snapshot(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")

        hub: StreamHub = request.app.state.stream_hub
        return JSONResponse(
            _tournament_live_payload(connection, tournament, hub.tournament_live(tournament_id))
        )

    @app.get("/tournaments/{tournament_id}/events")
    async def tournament_events(tournament_id: int, request: Request):
        hub: StreamHub = request.app.state.stream_hub
        hub.bind_loop()

        def snapshot() -> dict[str, Any]:
            connection = connect_database(request.app.state.db_path)
            try:
                tournament = get_tournament(connection, tournament_id)
                if tournament is None:
                    return {"error": "tournament not found"}
                live = hub.tournament_live(tournament_id)
                return _tournament_live_payload(connection, tournament, live)
            finally:
                connection.close()

        async def stream():
            topic = f"tournament.{tournament_id}"
            subscription = hub.subscribe(topic)
            try:
                yield sse_stream_event(
                    hub.make_private_event(
                        topic,
                        "tournament.snapshot",
                        snapshot(),
                        source="web",
                    )
                )
                while True:
                    event = await subscription.queue.get()
                    if event is None:
                        break
                    yield sse_stream_event(event)
            finally:
                hub.unsubscribe(subscription)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.websocket("/internal/stream")
    async def internal_stream(websocket: WebSocket):
        await websocket.accept()
        if not _internal_stream_peer_allowed(websocket):
            await websocket.close(code=4003, reason="stream peer not allowed")
            return

        hub: StreamHub = websocket.app.state.stream_hub
        hub.bind_loop()
        queue: asyncio.Queue[StreamEnvelope | None] | None = None
        try:
            hello = decode_stream_event(await websocket.receive_text())
            if hello.type != "stream.hello" or not _stream_hello_authorized(websocket, hello):
                await websocket.close(code=4003, reason="stream auth failed")
                return
            queue = hub.register_internal_client()
            await websocket.send_text(
                _stream_text(
                    make_stream_event("internal", "stream.ready", source="web")
                )
            )
            receiver = asyncio.create_task(_receive_internal_stream(websocket, hub))
            sender = asyncio.create_task(_send_internal_stream(websocket, queue))
            done, pending = await asyncio.wait(
                {receiver, sender},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        except (StreamProtocolError, WebSocketDisconnect):
            return
        finally:
            if queue is not None:
                hub.unregister_internal_client(queue)

    @app.get("/ratings")
    def ratings(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        categories = list_categories(connection, active_only=True)
        category_id = _selected_category_id(request, categories)
        category = get_category(connection, category_id) if category_id is not None else None
        return templates.TemplateResponse(
            request,
            "ratings.html",
            {
                "active_nav": "ratings",
                "category": category,
                "categories": categories,
                "ratings": list_rating_rows(connection, category.id) if category else [],
            },
        )

    @app.get("/engines/{engine_id}")
    def engine_detail(
        engine_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engine = get_engine(connection, engine_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="engine not found")

        games = list_engine_games(connection, engine_id)
        return templates.TemplateResponse(
            request,
            "engine_detail.html",
            {
                "active_nav": "ratings",
                "engine": engine,
                "games": games,
                "engines": _engine_names(connection),
                "record": _engine_record_summary(games, engine_id),
            },
        )

    @app.get("/archive")
    def archive(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engines = _engine_names(connection)
        tournaments = [
            _tournament_summary(connection, tournament, engines)
            for tournament in list_tournaments(connection)
            if tournament.status in {"finished", "aborted"}
        ]
        return templates.TemplateResponse(
            request,
            "archive.html",
            {
                "active_nav": "archive",
                "tournaments": tournaments,
                "games": list_games_by_status(connection, "finished", limit=50),
                "engines": engines,
            },
        )

    # ------------------------------------------------------------------
    # Admin: dashboard
    # ------------------------------------------------------------------

    @app.get("/admin")
    def admin_dashboard(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournaments = list_tournaments(connection)
        return templates.TemplateResponse(
            request,
            "admin/dashboard.html",
            _admin_context(
                request,
                "dashboard",
                workers=_worker_admin_rows(connection),
                live_games=list_games_by_status(connection, "live", limit=8),
                engines=_engine_names(connection),
                db_stats=database_stats(connection),
                running_tournaments=[t for t in tournaments if t.status in {"scheduled", "running", "paused"}],
                complete_tournaments=list_uncommitted_finished_tournaments(connection),
                recent_games=list_games_by_status(connection, "finished", limit=6),
            ),
        )

    # ------------------------------------------------------------------
    # Admin: tournaments
    # ------------------------------------------------------------------

    @app.get("/admin/tournaments")
    def admin_tournaments(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engines = _engine_names(connection)
        status_filter = request.query_params.get("status", "")
        tournaments = [
            _tournament_summary(connection, tournament, engines)
            for tournament in list_tournaments(connection)
            if not status_filter or tournament.status == status_filter
        ]
        return templates.TemplateResponse(
            request,
            "admin/tournaments.html",
            _admin_context(
                request,
                "tournaments",
                tournaments=tournaments,
                status_filter=status_filter,
                statuses=("draft", "scheduled", "running", "paused", "finished", "aborted"),
            ),
        )

    @app.get("/admin/tournaments/new")
    def admin_new_tournament(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        return templates.TemplateResponse(
            request,
            "admin/tournament_form.html",
            _tournament_form_context(request, connection),
        )

    @app.post("/admin/tournaments")
    async def admin_create_tournament(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        name = form_value(form, "name")
        errors = [] if name else ["Tournament name is required."]
        try:
            config = forms.build_tournament_config(form)
        except FormError as exc:
            errors.extend(exc.errors)
            config = None

        if errors or config is None:
            return templates.TemplateResponse(
                request,
                "admin/tournament_form.html",
                _tournament_form_context(request, connection, form=form, errors=errors),
                status_code=400,
            )

        tournament_id = create_tournament(connection, name, config)
        connection.commit()
        return RedirectResponse(
            url=f"/admin/tournaments/{tournament_id}?notice=" + quote("Tournament created."),
            status_code=303,
        )

    @app.get("/admin/tournaments/{tournament_id}")
    def admin_tournament_detail(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")

        context = _admin_context(
            request,
            "tournaments",
            tournament=tournament,
            games=list_games(connection, tournament.id),
            engines=_engine_names(connection),
            category=get_category(connection, tournament.category_id),
            settings=_settings_view(connection, tournament),
            commit=get_tournament_rating_commit(connection, tournament.id),
            actions=TOURNAMENT_ACTIONS.get(tournament.status, {}),
        )
        if tournament.status == "draft":
            context.update(
                _tournament_form_context(request, connection, tournament=tournament, wrap=False)
            )
        return templates.TemplateResponse(request, "admin/tournament_detail.html", context)

    @app.post("/admin/tournaments/{tournament_id}")
    async def admin_update_tournament(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")
        if tournament.status != "draft":
            raise HTTPException(status_code=409, detail="only draft tournaments can be edited")

        form = await read_form(request)
        name = form_value(form, "name")
        errors = [] if name else ["Tournament name is required."]
        try:
            config = forms.build_tournament_config(form)
        except FormError as exc:
            errors.extend(exc.errors)
            config = None

        if errors or config is None:
            context = _admin_context(
                request,
                "tournaments",
                tournament=tournament,
                games=(),
                engines=_engine_names(connection),
                category=get_category(connection, tournament.category_id),
                settings=_settings_view(connection, tournament),
                commit=None,
                actions=TOURNAMENT_ACTIONS.get(tournament.status, {}),
                errors=errors,
            )
            context.update(
                _tournament_form_context(request, connection, form=form, wrap=False)
            )
            return templates.TemplateResponse(
                request, "admin/tournament_detail.html", context, status_code=400
            )

        update_tournament(connection, tournament_id, name=name, config=config)
        connection.commit()
        return RedirectResponse(
            url=f"/admin/tournaments/{tournament_id}?notice=" + quote("Tournament updated."),
            status_code=303,
        )

    @app.post("/admin/tournaments/{tournament_id}/status")
    async def admin_tournament_status(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")

        form = await read_form(request)
        action = form_value(form, "action")
        allowed = TOURNAMENT_ACTIONS.get(tournament.status, {})
        if action not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"cannot {action} a {tournament.status} tournament",
            )

        set_tournament_status(connection, tournament_id, allowed[action])
        connection.commit()
        return RedirectResponse(
            url=f"/admin/tournaments/{tournament_id}?notice=" + quote(f"Tournament {allowed[action]}."),
            status_code=303,
        )

    @app.post("/admin/tournaments/{tournament_id}/delete")
    def admin_delete_tournament(
        tournament_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")
        if tournament.status in {"scheduled", "running"}:
            raise HTTPException(
                status_code=409,
                detail="abort the tournament before deleting it",
            )

        try:
            delete_tournament(connection, tournament_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        return RedirectResponse(
            url="/admin/tournaments?notice=" + quote("Tournament deleted."),
            status_code=303,
        )

    @app.post("/admin/tournaments/{tournament_id}/commit-results")
    def admin_commit_tournament_results(
        tournament_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")
        if tournament.status != "finished":
            raise HTTPException(status_code=409, detail="tournament is not complete")

        try:
            requested = request_tournament_rating_commit(connection, tournament)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        notice = "Rating commit requested." if requested else "Rating commit is already queued or applied."
        return RedirectResponse(
            url=f"/admin/tournaments/{tournament_id}?notice=" + quote(notice),
            status_code=303,
        )

    # ------------------------------------------------------------------
    # Admin: engines
    # ------------------------------------------------------------------

    @app.get("/admin/engines")
    def admin_engines(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engines = list_engine_records(connection)
        return templates.TemplateResponse(
            request,
            "admin/engines.html",
            _admin_context(
                request,
                "engines",
                engines=engines,
                game_counts={
                    engine.id: engine_game_count(connection, engine.id) for engine in engines
                },
            ),
        )

    @app.get("/admin/engines/new")
    def admin_new_engine(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        return templates.TemplateResponse(
            request,
            "admin/engine_form.html",
            _admin_context(request, "engines", engine=None, values={}, uci_options_text=""),
        )

    @app.post("/admin/engines")
    async def admin_create_engine(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        values, uci_options, errors = _engine_form_values(form)
        if not errors:
            try:
                spec = EngineSpec(
                    engine_id=next_engine_id(connection),
                    name=values["name"],
                    version=values["version"],
                    git_url=values["git_url"],
                    branch=values["branch"],
                    commit=values["commit"],
                    build_cmd=values["build_cmd"],
                    binary_path=values["binary_path"],
                    uci_options=uci_options,
                )
                create_engine(
                    connection,
                    spec,
                    author=values["author"],
                    active=values["active"],
                )
                connection.commit()
            except (ValidationError, sqlite3.IntegrityError, ValueError) as exc:
                errors.append(_friendly_error(exc))

        if errors:
            return templates.TemplateResponse(
                request,
                "admin/engine_form.html",
                _admin_context(
                    request,
                    "engines",
                    engine=None,
                    values=values,
                    uci_options_text=form_value(form, "uci_options"),
                    errors=errors,
                ),
                status_code=400,
            )
        return RedirectResponse(
            url="/admin/engines?notice=" + quote("Engine registered."),
            status_code=303,
        )

    @app.get("/admin/engines/{engine_id}/edit")
    def admin_edit_engine(
        engine_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engine = get_engine_record(connection, engine_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="engine not found")
        return templates.TemplateResponse(
            request,
            "admin/engine_form.html",
            _admin_context(
                request,
                "engines",
                engine=engine,
                values={
                    "name": engine.name,
                    "author": engine.author,
                    "version": engine.version,
                    "git_url": engine.git_url,
                    "branch": engine.branch,
                    "commit": engine.commit,
                    "build_cmd": engine.build_cmd,
                    "binary_path": engine.binary_path,
                    "active": engine.active,
                },
                uci_options_text="\n".join(
                    f"{key} = {value}" for key, value in engine.uci_options.items()
                ),
            ),
        )

    @app.post("/admin/engines/{engine_id}")
    async def admin_update_engine(
        engine_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        engine = get_engine_record(connection, engine_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="engine not found")

        form = await read_form(request)
        values, uci_options, errors = _engine_form_values(form)
        if not errors:
            try:
                EngineSpec(
                    engine_id=engine_id,
                    name=values["name"],
                    version=values["version"],
                    git_url=values["git_url"],
                    branch=values["branch"],
                    commit=values["commit"],
                    build_cmd=values["build_cmd"],
                    binary_path=values["binary_path"],
                    uci_options=uci_options,
                )
                update_engine(
                    connection,
                    engine_id,
                    name=values["name"],
                    author=values["author"],
                    version=values["version"],
                    git_url=values["git_url"],
                    branch=values["branch"],
                    commit=values["commit"],
                    build_cmd=values["build_cmd"],
                    binary_path=values["binary_path"],
                    uci_options=uci_options,
                    active=values["active"],
                )
                connection.commit()
            except (ValidationError, sqlite3.IntegrityError, ValueError) as exc:
                errors.append(_friendly_error(exc))

        if errors:
            return templates.TemplateResponse(
                request,
                "admin/engine_form.html",
                _admin_context(
                    request,
                    "engines",
                    engine=engine,
                    values=values,
                    uci_options_text=form_value(form, "uci_options"),
                    errors=errors,
                ),
                status_code=400,
            )
        return RedirectResponse(
            url="/admin/engines?notice=" + quote("Engine updated."),
            status_code=303,
        )

    @app.post("/admin/engines/{engine_id}/delete")
    def admin_delete_engine(
        engine_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_engine_record(connection, engine_id) is None:
            raise HTTPException(status_code=404, detail="engine not found")
        try:
            delete_engine(connection, engine_id)
        except ValueError as exc:
            return RedirectResponse(
                url="/admin/engines?error=" + quote(str(exc)),
                status_code=303,
            )
        connection.commit()
        return RedirectResponse(
            url="/admin/engines?notice=" + quote("Engine deleted."),
            status_code=303,
        )

    # ------------------------------------------------------------------
    # Admin: categories
    # ------------------------------------------------------------------

    @app.get("/admin/categories")
    def admin_categories(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        categories = list_categories(connection)
        return templates.TemplateResponse(
            request,
            "admin/categories.html",
            _admin_context(
                request,
                "categories",
                categories=categories,
                tournament_counts={
                    category.id: category_tournament_count(connection, category.id)
                    for category in categories
                },
            ),
        )

    @app.get("/admin/categories/new")
    def admin_new_category(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        return templates.TemplateResponse(
            request,
            "admin/category_form.html",
            _category_form_context(request, connection),
        )

    @app.post("/admin/categories")
    async def admin_create_category(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        name = form_value(form, "name")
        errors = [] if name else ["Category name is required."]
        default_config: dict[str, Any] = {}
        try:
            default_config = forms.settings_as_dict(forms.build_settings(form))
        except FormError as exc:
            errors.extend(exc.errors)

        if not errors:
            try:
                create_category(
                    connection,
                    name=name,
                    description=form_value(form, "description"),
                    default_config=default_config,
                    active=form_flag(form, "active"),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                errors.append(_friendly_error(exc))

        if errors:
            return templates.TemplateResponse(
                request,
                "admin/category_form.html",
                _category_form_context(request, connection, form=form, errors=errors),
                status_code=400,
            )
        return RedirectResponse(
            url="/admin/categories?notice=" + quote("Category created."),
            status_code=303,
        )

    @app.get("/admin/categories/{category_id}")
    def admin_category_detail(
        category_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        category = get_category(connection, category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="category not found")
        return templates.TemplateResponse(
            request,
            "admin/category_form.html",
            _category_form_context(request, connection, category=category),
        )

    @app.post("/admin/categories/{category_id}")
    async def admin_update_category(
        category_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        category = get_category(connection, category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="category not found")

        form = await read_form(request)
        name = form_value(form, "name")
        errors = [] if name else ["Category name is required."]
        default_config: dict[str, Any] = {}
        try:
            default_config = forms.settings_as_dict(forms.build_settings(form))
        except FormError as exc:
            errors.extend(exc.errors)

        if not errors:
            try:
                update_category(
                    connection,
                    category_id,
                    name=name,
                    description=form_value(form, "description"),
                    default_config=default_config,
                    active=form_flag(form, "active"),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                errors.append(_friendly_error(exc))

        if errors:
            return templates.TemplateResponse(
                request,
                "admin/category_form.html",
                _category_form_context(
                    request, connection, category=category, form=form, errors=errors
                ),
                status_code=400,
            )
        return RedirectResponse(
            url=f"/admin/categories/{category_id}?notice=" + quote("Category saved."),
            status_code=303,
        )

    @app.post("/admin/categories/{category_id}/delete")
    def admin_delete_category(
        category_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_category(connection, category_id) is None:
            raise HTTPException(status_code=404, detail="category not found")
        try:
            delete_category(connection, category_id)
        except ValueError as exc:
            return RedirectResponse(
                url="/admin/categories?error=" + quote(str(exc)),
                status_code=303,
            )
        connection.commit()
        return RedirectResponse(
            url="/admin/categories?notice=" + quote("Category deleted."),
            status_code=303,
        )

    # ------------------------------------------------------------------
    # Admin: openings
    # ------------------------------------------------------------------

    @app.get("/admin/openings")
    def admin_openings(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        suites = list_opening_suites(connection)
        return templates.TemplateResponse(
            request,
            "admin/openings.html",
            _admin_context(
                request,
                "openings",
                suites=suites,
                opening_counts={
                    suite.id: suite_opening_count(connection, suite.id) for suite in suites
                },
            ),
        )

    @app.get("/admin/openings/new")
    def admin_new_opening_suite(request: Request):
        return templates.TemplateResponse(
            request,
            "admin/opening_form.html",
            _admin_context(
                request,
                "openings",
                suite=None,
                positions_text="",
            ),
        )

    @app.post("/admin/openings")
    async def admin_create_opening_suite(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form, files = await read_form_with_files(request)
        name = form_value(form, "name")
        if not name:
            return RedirectResponse(
                url="/admin/openings?error=" + quote("Suite name is required."),
                status_code=303,
            )
        try:
            openings = parse_openings(form_value(form, "positions"))
            openings.extend(parse_opening_uploads(files))
            suite_id = create_opening_suite(
                connection,
                name=name,
                description=form_value(form, "description"),
            )
            replace_suite_openings(connection, suite_id, openings)
            connection.commit()
        except (ValueError, sqlite3.IntegrityError) as exc:
            return RedirectResponse(
                url="/admin/openings?error=" + quote(_friendly_error(exc)),
                status_code=303,
            )
        return RedirectResponse(
            url=f"/admin/openings/{suite_id}?notice=" + quote("Suite created."),
            status_code=303,
        )

    @app.get("/admin/openings/{suite_id:int}")
    def admin_opening_suite_detail(
        suite_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        suite = get_opening_suite(connection, suite_id)
        if suite is None:
            raise HTTPException(status_code=404, detail="opening suite not found")
        openings = list_suite_openings(connection, suite_id)
        return templates.TemplateResponse(
            request,
            "admin/opening_detail.html",
            _admin_context(
                request,
                "openings",
                suite=suite,
                openings=openings,
                positions_text="\n".join(
                    f"{opening.name}; {opening.fen}" if opening.name else opening.fen
                    for opening in openings
                ),
            ),
        )

    @app.post("/admin/openings/{suite_id:int}")
    async def admin_update_opening_suite(
        suite_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_opening_suite(connection, suite_id) is None:
            raise HTTPException(status_code=404, detail="opening suite not found")
        form, files = await read_form_with_files(request)
        name = form_value(form, "name")
        if not name:
            return RedirectResponse(
                url=f"/admin/openings/{suite_id}?error=" + quote("Suite name is required."),
                status_code=303,
            )
        try:
            update_opening_suite(
                connection,
                suite_id,
                name=name,
                description=form_value(form, "description"),
            )
            openings = parse_openings(form_value(form, "positions"))
            openings.extend(parse_opening_uploads(files))
            replace_suite_openings(connection, suite_id, openings)
            connection.commit()
        except (ValueError, sqlite3.IntegrityError) as exc:
            return RedirectResponse(
                url=f"/admin/openings/{suite_id}?error=" + quote(_friendly_error(exc)),
                status_code=303,
            )
        return RedirectResponse(
            url=f"/admin/openings/{suite_id}?notice=" + quote("Suite saved."),
            status_code=303,
        )

    @app.post("/admin/openings/{suite_id:int}/delete")
    def admin_delete_opening_suite(
        suite_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_opening_suite(connection, suite_id) is None:
            raise HTTPException(status_code=404, detail="opening suite not found")
        delete_opening_suite(connection, suite_id)
        connection.commit()
        return RedirectResponse(
            url="/admin/openings?notice=" + quote("Suite deleted."),
            status_code=303,
        )

    # ------------------------------------------------------------------
    # Admin: workers
    # ------------------------------------------------------------------

    @app.get("/admin/workers")
    def admin_workers(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        return templates.TemplateResponse(
            request,
            "admin/workers.html",
            _admin_context(
                request,
                "workers",
                worker_rows=_worker_admin_rows(connection),
                minted=None,
                minted_start_command=None,
            ),
        )

    @app.get("/admin/workers.json")
    def admin_workers_json(
        connection: sqlite3.Connection = Depends(_database),
    ):
        return JSONResponse(
            {
                "workers": [
                    _worker_admin_payload(row)
                    for row in _worker_admin_rows(connection)
                ]
            }
        )

    @app.get("/admin/workers/events")
    async def admin_workers_events(request: Request):
        hub: StreamHub = request.app.state.stream_hub
        hub.bind_loop()

        def snapshot() -> dict[str, Any]:
            connection = connect_database(request.app.state.db_path)
            try:
                return _workers_snapshot_payload(connection)
            finally:
                connection.close()

        async def stream():
            subscription = hub.subscribe("workers")
            try:
                yield sse_stream_event(
                    hub.make_private_event("workers", "workers.snapshot", snapshot(), source="web")
                )
                while True:
                    event = await subscription.queue.get()
                    if event is None:
                        break
                    yield sse_stream_event(event)
            finally:
                hub.unsubscribe(subscription)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/admin/workers/{worker_id:int}")
    def admin_worker_detail(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        row = _worker_admin_row(connection, worker_id)
        if row is None:
            raise HTTPException(status_code=404, detail="worker not found")
        return templates.TemplateResponse(
            request,
            "admin/worker_detail.html",
            _admin_context(
                request,
                "workers",
                row=row,
                worker=row["worker"],
                minted=None,
                minted_start_command=None,
                worker_launch_command=_worker_launch_command(
                    row["worker"],
                    request.app.state.worker_server_url,
                ),
            ),
        )

    @app.post("/admin/workers")
    async def admin_create_worker(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        label = form_value(form, "label") or "worker"
        worker_id = create_worker(connection, label=label)
        connection.commit()
        return RedirectResponse(
            url=f"/admin/workers/{worker_id}?notice=" + quote("Worker created."),
            status_code=303,
        )

    @app.get("/admin/workers/{worker_id:int}/token")
    def admin_worker_token_get(worker_id: int):
        return RedirectResponse(
            url=f"/admin/workers/{worker_id}?error="
            + quote("Use Generate one-time token from the worker page."),
            status_code=303,
        )

    @app.post("/admin/workers/{worker_id:int}/token")
    async def admin_generate_worker_token(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        worker = get_worker(connection, worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="worker not found")
        form = await read_form(request)
        raw_ttl = form_value(form, "ttl_seconds")
        ttl_seconds = int(raw_ttl) if raw_ttl.isdigit() and int(raw_ttl) > 0 else 7200
        try:
            minted = mint_worker_token_for_worker(
                connection,
                worker_id=worker_id,
                ttl_seconds=ttl_seconds,
            )
        except ValueError as exc:
            return RedirectResponse(
                url=f"/admin/workers/{worker_id}?error=" + quote(str(exc)),
                status_code=303,
            )
        connection.commit()
        row = _worker_admin_row(connection, worker_id)
        if row is None:
            raise HTTPException(status_code=404, detail="worker not found")
        response = templates.TemplateResponse(
            request,
            "admin/worker_detail.html",
            _admin_context(
                request,
                "workers",
                row=row,
                worker=row["worker"],
                minted=minted,
                minted_start_command=(
                    f"cope worker --server-url {_command_arg(request.app.state.worker_server_url)} "
                    f"--token {_command_arg(minted.token)}"
                ),
                worker_launch_command=None,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/admin/workers/{worker_id}/label")
    async def admin_update_worker_label(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="worker not found")
        form = await read_form(request)
        label = form_value(form, "label")
        if label:
            update_worker_label(connection, worker_id, label)
            connection.commit()
        next_url = _safe_redirect_target(form_value(form, "next"), "/admin/workers")
        return RedirectResponse(
            url=f"{next_url}?notice=" + quote("Worker renamed."),
            status_code=303,
        )

    @app.post("/admin/workers/{worker_id}/revoke")
    async def admin_revoke_worker(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="worker not found")
        form = await read_form(request)
        revoke_worker(connection, worker_id)
        connection.commit()
        next_url = _safe_redirect_target(form_value(form, "next"), "/admin/workers")
        return RedirectResponse(
            url=f"{next_url}?notice=" + quote("Worker revoked."),
            status_code=303,
        )

    @app.post("/admin/workers/{worker_id}/delete")
    def admin_delete_worker(
        worker_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="worker not found")
        try:
            delete_worker(connection, worker_id)
        except ValueError as exc:
            return RedirectResponse(
                url="/admin/workers?error=" + quote(str(exc)),
                status_code=303,
            )
        connection.commit()
        return RedirectResponse(
            url="/admin/workers?notice=" + quote("Worker deleted."),
            status_code=303,
        )

    # ------------------------------------------------------------------
    # Admin: chat moderation
    # ------------------------------------------------------------------

    @app.get("/admin/chat")
    def admin_chat(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        return templates.TemplateResponse(
            request,
            "admin/chat.html",
            _admin_context(
                request,
                "chat",
                messages=list_chat_messages(connection, limit=100),
                settings=get_chat_settings(connection),
            ),
        )

    @app.post("/admin/chat/settings")
    async def admin_update_chat_settings(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        settings = ChatSettingsRecord(
            enabled=form_flag(form, "enabled"),
            slowmode_seconds=max(0, _int_form_value(form, "slowmode_seconds", 0)),
            max_message_length=max(1, _int_form_value(form, "max_message_length", 300)),
            allow_anonymous_names=form_flag(form, "allow_anonymous_names"),
            retention_days=max(1, _int_form_value(form, "retention_days", 30)),
        )
        update_chat_settings(connection, settings)
        connection.commit()
        return RedirectResponse(
            url="/admin/chat?notice=" + quote("Chat settings saved."),
            status_code=303,
        )

    @app.post("/admin/chat/{message_id}/delete")
    def admin_delete_chat_message(
        message_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        delete_chat_message(connection, message_id)
        connection.commit()
        return RedirectResponse(
            url="/admin/chat?notice=" + quote("Message deleted."),
            status_code=303,
        )

    return app


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _database(request: Request) -> Iterator[sqlite3.Connection]:
    # check_same_thread=False: FastAPI runs sync dependencies in a threadpool
    # while async endpoints run on the event loop, so a request's connection
    # crosses threads. Each connection is still scoped to a single request.
    connection = connect_database(request.app.state.db_path, check_same_thread=False)
    try:
        yield connection
    finally:
        connection.close()


async def _receive_internal_stream(websocket: WebSocket, hub: StreamHub) -> None:
    while True:
        event = decode_stream_event(await websocket.receive_text())
        await _dispatch_internal_stream_event(websocket.app, event)


async def _send_internal_stream(
    websocket: WebSocket,
    queue: asyncio.Queue[StreamEnvelope | None],
) -> None:
    while True:
        event = await queue.get()
        if event is None:
            await websocket.close(code=4008, reason="stream client backlog exceeded")
            return
        await websocket.send_text(_stream_text(event))


async def _dispatch_internal_stream_event(app: FastAPI, event: StreamEnvelope) -> None:
    hub: StreamHub = app.state.stream_hub
    if event.topic == "workers" or event.type.startswith("worker"):
        connection = connect_database(app.state.db_path)
        try:
            payload = _workers_snapshot_payload(connection)
        finally:
            connection.close()
        hub.publish("workers", "workers.snapshot", payload, source=event.source)
        return

    tournament_id = _event_tournament_id(event)
    if tournament_id is None:
        hub.publish(event.topic, event.type, event.data, source=event.source)
        return

    topic = f"tournament.{tournament_id}"
    if event.type in {"engine.info", "clock.sync"}:
        hub.publish(topic, event.type, event.data, source=event.source)
        return

    if event.type == "tournament.live":
        hub.publish(topic, event.type, event.data, source=event.source)
        hub.publish(
            topic,
            "tournament.snapshot",
            _tournament_snapshot(app, tournament_id),
            source="web",
        )
        return

    if event.type == "game.move":
        hub.publish(topic, "game.move", event.data, source=event.source)

    hub.publish(
        topic,
        "tournament.snapshot",
        _tournament_snapshot(app, tournament_id),
        source="web",
    )


def _tournament_snapshot(app: FastAPI, tournament_id: int) -> dict[str, Any]:
    hub: StreamHub = app.state.stream_hub
    connection = connect_database(app.state.db_path)
    try:
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            return {"error": "tournament not found"}
        return _tournament_live_payload(connection, tournament, hub.tournament_live(tournament_id))
    finally:
        connection.close()


def _stream_text(event: StreamEnvelope) -> str:
    return encode_stream_event(event)


def _event_tournament_id(event: StreamEnvelope) -> int | None:
    value = event.data.get("tournament_id")
    if value is None and event.topic.startswith("tournament."):
        value = event.topic.removeprefix("tournament.")
    try:
        tournament_id = int(value)
    except (TypeError, ValueError):
        return None
    return tournament_id if tournament_id > 0 else None


def _workers_snapshot_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "workers": [
            _worker_admin_payload(row)
            for row in _worker_admin_rows(connection)
        ]
    }


def _publish_admin_post_streams(request: Request) -> None:
    hub: StreamHub = request.app.state.stream_hub
    path = request.url.path
    hub.publish_to_internal("runner.wake", {"reason": path})

    connection = connect_database(request.app.state.db_path)
    try:
        if path.startswith("/admin/workers"):
            hub.publish("workers", "workers.snapshot", _workers_snapshot_payload(connection), source="web")
        tournament_id = _admin_tournament_path_id(path)
        if tournament_id is not None:
            tournament = get_tournament(connection, tournament_id)
            payload = (
                _tournament_live_payload(
                    connection,
                    tournament,
                    hub.tournament_live(tournament_id),
                )
                if tournament is not None
                else {"error": "tournament not found"}
            )
            hub.publish(
                f"tournament.{tournament_id}",
                "tournament.snapshot",
                payload,
                source="web",
            )
    finally:
        connection.close()


def _admin_tournament_path_id(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "admin" or parts[1] != "tournaments":
        return None
    try:
        value = int(parts[2])
    except ValueError:
        return None
    return value if value > 0 else None


def _admin_context(request: Request, section: str, **extra: Any) -> dict[str, Any]:
    token = _admin_token(request)
    context: dict[str, Any] = {
        "active_nav": "admin",
        "admin_section": section,
        "notice": request.query_params.get("notice"),
        "error": request.query_params.get("error"),
        "errors": [],
        "csrf_token": _csrf_token(request, token) if token else "",
    }
    context.update(extra)
    return context


def _admin_token(request: Request) -> str | None:
    return getattr(request.app.state, "admin_token", None) or None


def _admin_session_valid(request: Request, token: str) -> bool:
    value = request.cookies.get("cope_admin_session", "")
    if not value:
        return False
    nonce = _signed_value_nonce(token, value)
    return nonce is not None


def _csrf_token(request: Request, token: str | None) -> str:
    if token is None:
        return ""
    nonce = _signed_value_nonce(token, request.cookies.get("cope_admin_session", ""))
    if nonce is None:
        return ""
    return _csrf_for_nonce(token, nonce)


def _csrf_token_valid(request: Request, token: str, supplied: str) -> bool:
    expected = _csrf_token(request, token)
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def _signed_value(token: str, nonce: str) -> str:
    signature = hmac.digest(token.encode("utf-8"), nonce.encode("utf-8"), "sha256").hex()
    return f"{nonce}.{signature}"


def _signed_value_nonce(token: str, value: str) -> str | None:
    if "." not in value:
        return None
    nonce, supplied = value.rsplit(".", 1)
    if not nonce or not supplied:
        return None
    expected = _signed_value(token, nonce).rsplit(".", 1)[1]
    if not hmac.compare_digest(supplied, expected):
        return None
    return nonce


def _csrf_for_nonce(token: str, nonce: str) -> str:
    return hmac.digest(
        token.encode("utf-8"),
        f"csrf:{nonce}".encode("utf-8"),
        "sha256",
    ).hex()


def _request_is_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",", 1)[0].strip() == "https"


def _request_is_secure_or_local(request: Request) -> bool:
    if _request_is_secure(request):
        return True
    if request.client is None:
        return True
    return request.client.host in LOCAL_EVENT_PUBLISHERS


def _internal_stream_peer_allowed(websocket: WebSocket) -> bool:
    if getattr(websocket.app.state, "event_token", None):
        return True
    return websocket.client is None or websocket.client.host in LOCAL_EVENT_PUBLISHERS


def _stream_hello_authorized(websocket: WebSocket, hello: StreamEnvelope) -> bool:
    expected = getattr(websocket.app.state, "event_token", None)
    if not expected:
        return websocket.client is None or websocket.client.host in LOCAL_EVENT_PUBLISHERS
    supplied = str(hello.data.get("token") or "")
    return bool(supplied and hmac.compare_digest(supplied, expected))


def _worker_admin_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    engines = _engine_names(connection)
    return [_worker_admin_view(connection, worker, engines) for worker in list_workers(connection)]


def _worker_admin_row(connection: sqlite3.Connection, worker_id: int) -> dict[str, Any] | None:
    worker = get_worker(connection, worker_id)
    if worker is None:
        return None
    return _worker_admin_view(connection, worker, _engine_names(connection))


def _worker_admin_view(
    connection: sqlite3.Connection,
    worker,
    engines: dict[int, str],
) -> dict[str, Any]:
    effective_status = _worker_effective_status(worker)
    activity = _worker_activity(connection, worker.id, engines)
    return {
        "worker": worker,
        "status": effective_status,
        "token": _worker_token_view(worker),
        "session": _worker_session_view(worker),
        "machine": _worker_machine_view(worker, effective_status),
        "work": activity or _worker_idle_activity(worker, effective_status),
    }


def _worker_admin_payload(row: dict[str, Any]) -> dict[str, Any]:
    worker = row["worker"]
    hardware = {
        "reported": False,
        "summary": "Not reported",
        "detail": "",
    }
    if worker.hw is not None:
        hardware = {
            "reported": True,
            "summary": f"{worker.hw.physical_cores} cores",
            "detail": f"{worker.hw.ram_gb}GB RAM",
            "cores": str(worker.hw.physical_cores),
            "memory": f"{worker.hw.ram_gb}GB",
        }
    return {
        "id": worker.id,
        "status": row["status"],
        "work": row["work"],
        "machine": row["machine"],
        "hardware": hardware,
    }


def _state_view(status: str, label: str, detail: str) -> dict[str, str]:
    return {"status": status, "label": label, "detail": detail}


def _worker_token_view(worker) -> dict[str, str]:
    if worker.token_expires_at is None:
        if worker.status == "revoked":
            return _state_view("revoked", "Revoked", "Token removed")
        if worker.status == "minted":
            return _state_view("pending", "Not generated", "Generate a token to register")
        return _state_view("consumed", "Consumed", "Registration complete")

    expires_at = _parse_utc_datetime(worker.token_expires_at)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return _state_view("expired", "Expired", f"Expired {worker.token_expires_at}")

    return _state_view("minted", "Minted", f"Expires {worker.token_expires_at}")


def _worker_session_view(worker) -> dict[str, str]:
    if worker.session_id:
        return _state_view("active", "Issued", _short_secret(worker.session_id))
    if worker.status == "minted":
        return _state_view("pending", "None", "Waiting for token use")
    return _state_view("inactive", "None", "No reconnect session")


def _worker_launch_command(worker, worker_server_url: str) -> str | None:
    if worker.session_id:
        return (
            f"cope worker --server-url {_command_arg(worker_server_url)} "
            f"--session-id {_command_arg(worker.session_id)}"
        )

    return None


def _command_arg(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _worker_effective_status(worker) -> str:
    if worker.status in CONNECTED_WORKER_STATUSES and not _worker_seen_recently(worker):
        return "stale"
    return worker.status


def _worker_seen_recently(worker) -> bool:
    if worker.last_seen is None:
        return False
    last_seen = _parse_utc_datetime(worker.last_seen)
    if last_seen is None:
        return False
    age = datetime.now(UTC) - last_seen
    return 0 <= age.total_seconds() <= WORKER_RECENT_SECONDS


def _worker_machine_view(worker, effective_status: str) -> dict[str, str]:
    seen_detail = f"Last worker event {worker.last_seen or 'unknown'}"
    if effective_status in CONNECTED_WORKER_STATUSES:
        return _state_view(effective_status, "Connected", seen_detail)
    states = {
        "stale": ("No active connection", seen_detail),
        "offline": ("Offline", f"Disconnected {worker.last_seen or 'unknown'}"),
        "minted": ("Not registered", "No machine yet"),
        "revoked": ("Revoked", "Cannot reconnect"),
    }
    label, detail = states.get(effective_status, (effective_status.title(), worker.last_seen or ""))
    return _state_view(effective_status, label, detail)


def _worker_activity(
    connection: sqlite3.Connection,
    worker_id: int,
    engines: dict[int, str],
) -> dict[str, Any] | None:
    activity = get_worker_activity(connection, worker_id)
    if activity is None:
        return None

    status = activity.assignment_status
    verb = "Playing" if status == "live" else "Assigned"
    white = engines.get(activity.white_engine_id, f"Engine {activity.white_engine_id}")
    black = engines.get(activity.black_engine_id, f"Engine {activity.black_engine_id}")
    return _activity_view(
        status,
        verb,
        f"Game #{activity.game_id} in round {activity.round}",
        f"{activity.tournament_name}: {white} vs {black}",
        href=f"/admin/tournaments/{activity.tournament_id}",
        meta=f"{activity.plies} plies recorded",
    )


def _worker_idle_activity(worker, effective_status: str) -> dict[str, Any]:
    if effective_status == "minted" and worker.token_expires_at is None:
        return _activity_view(
            "pending",
            "Needs token",
            "Awaiting token generation",
            "Generate a one-time token before starting the worker process.",
        )

    states = {
        "minted": ("pending", "Awaiting registration", "Token has not been used", "No worker process has connected with this token.", False),
        "ready": ("ready", "Idle", "Waiting for an eligible game", "The worker server is waiting for stream wake events or the next fallback scan.", False),
        "connected": ("connected", "Connected", "Preparing to accept work", "The machine is connected but has not started a game.", False),
        "building": ("building", "Building", "Preparing to accept work", "The machine is connected but has not started a game.", False),
        "stale": ("stale", "Stale", "No active machine connection", "The worker has not reported a recent connection event.", True),
        "busy": ("busy", "Busy", "Marked busy with no active assignment", "This can indicate a stale worker state after an interruption.", True),
        "offline": ("offline", "Offline", "Worker process is not connected", "The reconnect session remains issued unless the worker is revoked.", bool(worker.session_id)),
        "revoked": ("revoked", "Revoked", "Worker cannot reconnect", "Token and session credentials have been removed.", False),
    }
    if effective_status in states:
        status, label, summary, detail, abnormal = states[effective_status]
        return _activity_view(status, label, summary, detail, abnormal=abnormal)
    return _activity_view(
        effective_status,
        effective_status.title(),
        "No active assignment",
        "",
    )


def _activity_view(
    status: str,
    label: str,
    summary: str,
    detail: str,
    *,
    href: str = "",
    meta: str = "",
    abnormal: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "label": label,
        "summary": summary,
        "detail": detail,
        "meta": meta,
        "href": href,
        "abnormal": abnormal,
    }


def _parse_utc_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _short_secret(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"


def _tournament_form_context(
    request: Request,
    connection: sqlite3.Connection,
    *,
    tournament: TournamentRecord | None = None,
    form: dict[str, list[str]] | None = None,
    errors: list[str] | None = None,
    wrap: bool = True,
) -> dict[str, Any]:
    categories = list_categories(connection, active_only=True)
    if form is not None:
        values = forms.submitted_form_values(form)
        name = form_value(form, "name")
        participants = [int(v) for v in form.get("participants", []) if v.strip().isdigit()]
        category_id = int(form_value(form, "category_id") or 0) or (
            categories[0].id if categories else 1
        )
        linked = form_flag(form, "category_settings_linked")
    elif tournament is not None:
        values = forms.settings_form_values(tournament.config.model_dump(mode="json"))
        name = tournament.name
        participants = list(tournament.config.participants)
        category_id = tournament.category_id
        linked = tournament.config.category_settings_linked
    else:
        default_category = categories[0] if categories else None
        values = forms.settings_form_values(
            default_category.default_config if default_category else {}
        )
        name = ""
        participants = []
        category_id = default_category.id if default_category else 1
        linked = True

    form_fields = {
        "form_values": values,
        "form_name": name,
        "form_participants": participants,
        "form_category_id": category_id,
        "form_linked": linked,
        "categories": categories,
        "category_defaults": {
            category.id: forms.settings_form_values(category.default_config)
            for category in categories
        },
        "engine_options": [engine for engine in list_engine_records(connection) if engine.active],
        "opening_suites": list_opening_suites(connection),
        "editing": tournament is not None,
        "errors": errors or [],
    }
    if not wrap:
        return form_fields
    context = _admin_context(request, "tournaments", **form_fields)
    return context


def _category_form_context(
    request: Request,
    connection: sqlite3.Connection,
    *,
    category: Any = None,
    form: dict[str, list[str]] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    if form is not None:
        values = forms.submitted_form_values(form)
        name = form_value(form, "name")
        description = form_value(form, "description")
        active = form_flag(form, "active")
    elif category is not None:
        values = forms.settings_form_values(category.default_config)
        name = category.name
        description = category.description
        active = category.active
    else:
        values = forms.settings_form_values({})
        name = ""
        description = ""
        active = True

    return _admin_context(
        request,
        "categories",
        category=category,
        form_values=values,
        form_name=name,
        form_description=description,
        form_active=active,
        engine_options=[engine for engine in list_engine_records(connection) if engine.active],
        opening_suites=list_opening_suites(connection),
        tournaments=(
            _tournaments_for_category(connection, category.id) if category is not None else ()
        ),
        errors=errors or [],
    )


def _engine_form_values(
    form: dict[str, list[str]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    values = {
        "name": form_value(form, "name"),
        "author": form_value(form, "author"),
        "version": form_value(form, "version"),
        "git_url": form_value(form, "git_url"),
        "branch": form_value(form, "branch"),
        "commit": form_value(form, "commit").lower(),
        "build_cmd": form_value(form, "build_cmd"),
        "binary_path": form_value(form, "binary_path"),
        "active": form_flag(form, "active"),
    }
    errors = []
    if not values["name"]:
        errors.append("Engine name is required.")
    if not values["git_url"]:
        errors.append("Git URL is required.")
    if len(values["commit"]) != 40 or any(
        char not in "0123456789abcdef" for char in values["commit"]
    ):
        errors.append("Commit must be a full 40-character hex SHA.")
    if not values["build_cmd"]:
        errors.append("Build command is required.")
    if not values["binary_path"]:
        errors.append("Binary path is required.")

    uci_options: dict[str, Any] = {}
    for line in form_value(form, "uci_options").splitlines():
        line = line.strip()
        if not line:
            continue
        key, separator, raw = line.partition("=")
        if not separator or not key.strip():
            errors.append(f'UCI option "{line}" must use the form "Name = value".')
            continue
        raw = raw.strip()
        value: Any = raw
        if raw.lower() in {"true", "false"}:
            value = raw.lower() == "true"
        elif raw.lstrip("-").isdigit():
            value = int(raw)
        uci_options[key.strip()] = value

    return values, uci_options, errors


def _int_form_value(form: dict[str, list[str]], key: str, default: int) -> int:
    raw = form_value(form, key)
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if "UNIQUE constraint failed" in message:
        return "That name is already in use."
    return message


def _safe_redirect_target(value: str, fallback: str) -> str:
    if value.startswith("/") and not value.startswith("//"):
        return value
    return fallback


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _create_chat_message_from_form(
    connection: sqlite3.Connection,
    form: dict[str, list[str]],
) -> dict[str, str] | None:
    settings = get_chat_settings(connection)
    if not settings.enabled:
        return None

    display_name = form_value(form, "display_name")[:40].strip()
    if not display_name or not settings.allow_anonymous_names:
        display_name = "Anonymous"
    text = form_value(form, "text")[: settings.max_message_length].strip()
    if not text:
        return None

    message_id = create_chat_message(connection, display_name=display_name, text=text)
    connection.commit()
    return {
        "id": str(message_id),
        "display_name": display_name,
        "text": text,
    }


def _engine_names(connection: sqlite3.Connection) -> dict[int, str]:
    return {engine.engine_id: engine.name for engine in list_engines(connection)}


def _tournament_names(connection: sqlite3.Connection) -> dict[int, str]:
    return {tournament.id: tournament.name for tournament in list_tournaments(connection)}


def _selected_category_id(request: Request, categories: tuple[Any, ...]) -> int | None:
    if not categories:
        return None

    raw_category_id = request.query_params.get("category_id")
    if raw_category_id is not None:
        try:
            category_id = int(raw_category_id)
        except ValueError:
            category_id = categories[0].id
        else:
            if any(category.id == category_id for category in categories):
                return category_id

    return categories[0].id


def _selected_viewer_game(request: Request, games: tuple[GameRecord, ...]) -> GameRecord | None:
    raw_game_id = request.query_params.get("game_id")
    if raw_game_id is not None:
        try:
            game_id = int(raw_game_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="game not found") from None
        for game in games:
            if game.id == game_id:
                return game
        raise HTTPException(status_code=404, detail="game not found")

    return _tournament_viewer_game(games)


def _home_game_cards(
    connection: sqlite3.Connection,
    engines: dict[int, str],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for game in list_active_games(connection):
        tournament = get_tournament(connection, game.tournament_id)
        if tournament is None:
            continue
        tournament_games = list_games(connection, tournament.id)
        moves = list_moves(connection, game.id)
        cards.append(
            {
                "game": game,
                "tournament": tournament,
                "moves": moves,
                "opening": _opening_view(connection, game.opening_id),
                "summary": _summarize_games(tournament_games),
                "last_move": moves[-1] if moves else None,
                "white_name": engines.get(game.white_engine_id, f"Engine {game.white_engine_id}"),
                "black_name": engines.get(game.black_engine_id, f"Engine {game.black_engine_id}"),
                "time_control": _time_control_label(tournament.config.time_control),
                "format": tournament.config.format.value.replace("_", " ").title(),
            }
        )
    return cards


def _upcoming_rows(
    connection: sqlite3.Connection,
    engines: dict[int, str],
    *,
    limit: int,
) -> list[dict[str, str]]:
    pending_games = list_upcoming_games(connection, limit=limit)
    tournament_names = _tournament_names(connection)
    rows: list[dict[str, str]] = []
    for tournament in list_tournaments(connection):
        if tournament.status not in {"scheduled", "running", "paused"}:
            continue
        summary = _summarize_games(list_games(connection, tournament.id))
        rows.append(
            {
                "href": f"/tournaments/{tournament.id}",
                "tournament": tournament.name,
                "round": str(tournament.current_round or "-"),
                "white": "Tournament page",
                "black": f"{summary['finished']} / {summary['total']} complete",
                "status": tournament.status,
            }
        )

    rows.extend(
        {
            "href": f"/tournaments/{game.tournament_id}?game_id={game.id}",
            "tournament": tournament_names.get(game.tournament_id, f"Tournament {game.tournament_id}"),
            "round": str(game.round),
            "white": engines.get(game.white_engine_id, f"Engine {game.white_engine_id}"),
            "black": engines.get(game.black_engine_id, f"Engine {game.black_engine_id}"),
            "status": game.status,
        }
        for game in pending_games
    )

    return rows[:limit]


def _tournament_viewer_game(games: tuple[GameRecord, ...]) -> GameRecord | None:
    for status in ("live", "assigned", "pending"):
        for game in games:
            if game.status == status:
                return game
    return None


def _game_payload(
    game: GameRecord,
    engines: dict[int, str],
    *,
    live: bool = False,
) -> dict[str, Any]:
    payload = {
        "id": game.id,
        "tournament_id": game.tournament_id,
        "round": game.round,
        "status": game.status,
        "result": game.result,
        "white_name": engines.get(game.white_engine_id, f"Engine {game.white_engine_id}"),
        "black_name": engines.get(game.black_engine_id, f"Engine {game.black_engine_id}"),
    }
    if live:
        payload.update(
            {
                "termination": game.termination,
                "white_engine_id": game.white_engine_id,
                "black_engine_id": game.black_engine_id,
            }
        )
    return payload


def _move_payload(move: MoveRecord) -> dict[str, Any]:
    return {
        "ply": move.ply,
        "uci": move.uci,
        "san": move.san,
        "eval_cp": move.eval_cp,
        "eval_mate": move.eval_mate,
        "depth": move.depth,
        "nodes": move.nodes,
        "nps": move.nps,
        "pv": move.pv,
        "info_line": move.info_line,
        "time_ms": move.time_ms,
        "clock_after_ms": move.clock_after_ms,
    }


def _tournament_live_payload(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    engines = _engine_names(connection)
    games = list_games(connection, tournament.id)
    viewer_game = _tournament_viewer_game(games)
    viewer_moves = list_moves(connection, viewer_game.id) if viewer_game else ()
    opening = _opening_view(connection, viewer_game.opening_id) if viewer_game else None
    engine_data = _engine_data(viewer_game, viewer_moves)
    clocks = _clock_data(viewer_moves)
    if live is not None and viewer_game is not None and live.get("game_id") == viewer_game.id:
        engine_data = _merge_engine_data(engine_data, live.get("engine_data"))
        clocks = _merge_clock_data(clocks, live.get("clocks"))
    return {
        "tournament": {
            "id": tournament.id,
            "status": tournament.status,
            "current_round": tournament.current_round,
        },
        "game": _game_payload(viewer_game, engines, live=True) if viewer_game else None,
        "opening": opening or {"name": "Start position", "fen": "startpos"},
        "moves": [_move_payload(move) for move in viewer_moves],
        "engine_data": engine_data,
        "clocks": clocks,
        "standings": _standings(connection, tournament, games, engines),
        "games": [_game_payload(game, engines) for game in games],
    }


def _merge_engine_data(
    engine_data: dict[str, dict[str, str]],
    live_data: Any,
) -> dict[str, dict[str, str]]:
    if not isinstance(live_data, dict):
        return engine_data
    merged = {
        "white": dict(engine_data["white"]),
        "black": dict(engine_data["black"]),
    }
    for side in ("white", "black"):
        if isinstance(live_data.get(side), dict):
            merged[side].update(
                {
                    key: str(value)
                    for key, value in live_data[side].items()
                    if key in {"depth", "nps", "nodes", "eval", "pv", "info", "root_fen"}
                }
            )
    return merged


def _merge_clock_data(
    clocks: dict[str, str],
    live_clocks: Any,
) -> dict[str, str]:
    if not isinstance(live_clocks, dict):
        return clocks
    merged = dict(clocks)
    for side in ("white", "black"):
        if side in live_clocks:
            merged[side] = _clock_label(live_clocks[side])
    return merged


def _clock_data(moves: tuple[MoveRecord, ...]) -> dict[str, str]:
    clocks = {"white": "--:--", "black": "--:--"}
    for move in moves:
        side = "white" if move.ply % 2 == 1 else "black"
        clocks[side] = _clock_label(move.clock_after_ms)
    return clocks


def _clock_label(value: Any) -> str:
    if value is None:
        return "--:--"
    try:
        milliseconds = max(0, int(value))
    except (TypeError, ValueError):
        return "--:--"
    total_seconds = milliseconds // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _engine_data(
    game: GameRecord | None,
    moves: tuple[MoveRecord, ...],
) -> dict[str, dict[str, str]]:
    if game is None:
        return {
            "white": _engine_data_for_move(None),
            "black": _engine_data_for_move(None),
        }

    return {
        "white": _engine_data_for_move(_latest_move_for_side(moves, "white")),
        "black": _engine_data_for_move(_latest_move_for_side(moves, "black")),
    }


def _latest_move_for_side(moves: tuple[MoveRecord, ...], side: str) -> MoveRecord | None:
    white = side == "white"
    for move in reversed(moves):
        if (move.ply % 2 == 1) == white:
            return move
    return None


def _engine_data_for_move(move: MoveRecord | None) -> dict[str, str]:
    if move is None:
        return {
            "depth": "-",
            "nps": "-",
            "nodes": "-",
            "eval": "-",
            "info": "not recorded",
            "pv": "not recorded",
        }

    nps = f"{move.nps:,}" if move.nps is not None else "-"
    if move.nps is None and move.nodes is not None and move.time_ms > 0:
        nps = f"{int(move.nodes / (move.time_ms / 1000)):,}"

    return {
        "depth": str(move.depth) if move.depth is not None else "-",
        "nps": nps,
        "nodes": f"{move.nodes:,}" if move.nodes is not None else "-",
        "eval": _eval_label(move),
        "info": move.info_line or move.pv or "not recorded",
        "pv": move.pv or "not recorded",
    }


def _eval_label(move: MoveRecord) -> str:
    if move.eval_mate is not None:
        return f"#{move.eval_mate}"
    if move.eval_cp is not None:
        return f"{move.eval_cp / 100:+.2f}"
    return "-"


def _opening_view(connection: sqlite3.Connection, opening_id: int | None) -> dict[str, str] | None:
    opening = get_opening_position(connection, opening_id)
    if opening is None:
        return None
    return {
        "name": opening.name,
        "fen": opening.fen,
    }


def _engine_record_summary(games: tuple[GameRecord, ...], engine_id: int) -> dict[str, int]:
    record = {"wins": 0, "draws": 0, "losses": 0, "games": 0}
    for game in games:
        if game.result is None:
            continue
        record["games"] += 1
        if game.result == "1/2-1/2":
            record["draws"] += 1
        elif game.result == "1-0" and game.white_engine_id == engine_id:
            record["wins"] += 1
        elif game.result == "0-1" and game.black_engine_id == engine_id:
            record["wins"] += 1
        else:
            record["losses"] += 1
    return record


def _tournament_index_context(
    request: Request,
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    engines = _engine_names(connection)
    tournaments = [
        _tournament_summary(connection, tournament, engines)
        for tournament in list_tournaments(connection)
    ]
    return {
        "request": request,
        "active_nav": None,
        "tournaments": tournaments,
        "tournament_stats": _tournament_index_stats(tournaments),
    }


def _tournament_index_stats(tournaments: list[dict[str, Any]]) -> dict[str, int]:
    total_games = sum(item["summary"]["total"] for item in tournaments)
    finished_games = sum(item["summary"]["finished"] for item in tournaments)
    active_statuses = {"scheduled", "running", "paused"}
    return {
        "total": len(tournaments),
        "active": sum(1 for item in tournaments if item["record"].status in active_statuses),
        "live_games": sum(item["summary"]["live"] for item in tournaments),
        "completion_percent": round(finished_games / total_games * 100) if total_games else 0,
    }


def _standings(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    games: tuple[GameRecord, ...],
    engines: dict[int, str],
) -> list[dict[str, Any]]:
    points: dict[int, float] = {engine_id: 0.0 for engine_id in tournament.config.participants}
    played: dict[int, int] = {engine_id: 0 for engine_id in tournament.config.participants}
    for game in games:
        if game.result is None:
            continue
        for engine_id in (game.white_engine_id, game.black_engine_id):
            points.setdefault(engine_id, 0.0)
            played.setdefault(engine_id, 0)
            played[engine_id] += 1
        if game.result == "1-0":
            points[game.white_engine_id] += 1
        elif game.result == "0-1":
            points[game.black_engine_id] += 1
        else:
            points[game.white_engine_id] += 0.5
            points[game.black_engine_id] += 0.5

    matches = list_tournament_matches(connection, tournament.id)
    bye_points: dict[int, float] = {}
    if tournament.config.format == TournamentFormat.SWISS:
        for match in matches:
            if match.status == "bye":
                points[match.engine1_id] += 1.0
                bye_points[match.engine1_id] = bye_points.get(match.engine1_id, 0.0) + 1.0

    buchholz = {engine_id: 0.0 for engine_id in points}
    if tournament.config.format == TournamentFormat.SWISS:
        for game in games:
            if game.result is None:
                continue
            buchholz[game.white_engine_id] += points[game.black_engine_id]
            buchholz[game.black_engine_id] += points[game.white_engine_id]

    stage = {engine_id: 0 for engine_id in points}
    if tournament.config.format == TournamentFormat.KNOCKOUT:
        for match in matches:
            stage[match.engine1_id] = max(stage[match.engine1_id], match.round)
            if match.engine2_id is not None:
                stage[match.engine2_id] = max(stage[match.engine2_id], match.round)
            if match.winner_engine_id is not None:
                stage[match.winner_engine_id] = max(stage[match.winner_engine_id], match.round + 1)

    seed = {
        engine_id: index
        for index, engine_id in enumerate(tournament.config.participants)
    }
    rows = [
        {
            "engine_id": engine_id,
            "name": engines.get(engine_id, f"Engine {engine_id}"),
            "points": points[engine_id],
            "played": played[engine_id],
            "buchholz": buchholz[engine_id],
            "bye_points": bye_points.get(engine_id, 0.0),
            "stage": stage[engine_id],
        }
        for engine_id in points
    ]
    if tournament.config.format == TournamentFormat.KNOCKOUT:
        rows.sort(key=lambda row: (-row["stage"], -row["points"], seed[row["engine_id"]]))
    elif tournament.config.format == TournamentFormat.SWISS:
        rows.sort(
            key=lambda row: (
                -row["points"],
                -row["buchholz"],
                seed[row["engine_id"]],
            )
        )
    else:
        rows.sort(key=lambda row: (-row["points"], row["name"]))
    return rows


def _tournaments_for_category(
    connection: sqlite3.Connection,
    category_id: int,
) -> tuple[TournamentRecord, ...]:
    return tuple(
        tournament
        for tournament in list_tournaments(connection)
        if tournament.category_id == category_id
    )


def _tournament_summary(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    engines: dict[int, str],
) -> dict[str, Any]:
    games = list_games(connection, tournament.id)
    summary = _summarize_games(games)
    participant_names = [
        engines.get(engine_id, f"Engine {engine_id}")
        for engine_id in tournament.config.participants
    ]
    total_games = summary["total"]
    finished_games = summary["finished"]
    return {
        "record": tournament,
        "summary": summary,
        "participant_names": participant_names,
        "participant_preview": participant_names[:6],
        "participant_overflow": max(0, len(participant_names) - 6),
        "participant_count": len(participant_names),
        "progress_percent": round(finished_games / total_games * 100) if total_games else 0,
        "time_control": _time_control_label(tournament.config.time_control),
        "format": tournament.config.format.value.replace("_", " ").title(),
    }


def _summarize_games(games: tuple[GameRecord, ...]) -> dict[str, int]:
    summary = {
        "total": len(games),
        "pending": 0,
        "assigned": 0,
        "live": 0,
        "finished": 0,
        "abandoned": 0,
    }
    for game in games:
        summary[game.status] = summary.get(game.status, 0) + 1
    return summary


def _settings_view(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> list[tuple[str, str]]:
    """Human-readable label/value pairs describing a tournament's settings."""
    config = tournament.config
    engines = _engine_names(connection)

    rows: list[tuple[str, str]] = [
        ("Format", config.format.value.replace("_", " ").title()),
        ("Time control", _time_control_label(config.time_control)),
    ]

    options = config.format_options
    option_labels = {
        "double_rr": "Double round robin",
        "rounds": "Rounds",
        "games_per_match": "Games per match",
        "tiebreak": "Tiebreak",
        "games_per_opponent": "Games per opponent",
        "hero_engine_id": "Gauntlet hero",
    }
    for field, value in options.model_dump(mode="json").items():
        label = option_labels.get(field, field.replace("_", " ").title())
        if field == "hero_engine_id":
            value = engines.get(value, f"Engine {value}")
        elif isinstance(value, bool):
            value = "Yes" if value else "No"
        rows.append((label, str(value)))

    rows.extend(
        [
            ("Concurrency", str(config.concurrency)),
            ("Rated", "Yes" if config.rated else "No"),
            ("Lag compensation", f"{config.lag_compensation_ms}ms"),
        ]
    )

    if config.opening_suite_id:
        suite = get_opening_suite(connection, config.opening_suite_id)
        rows.append(("Opening suite", suite.name if suite else f"Suite {config.opening_suite_id}"))
    else:
        rows.append(("Opening suite", "None"))

    adjudication = config.adjudication
    if adjudication.draw:
        rows.append(
            (
                "Draw adjudication",
                f"after move {adjudication.draw.min_fullmove}, "
                f"within +/-{adjudication.draw.max_abs_cp}cp "
                f"for {adjudication.draw.consecutive_plies} plies",
            )
        )
    if adjudication.resign:
        rows.append(
            (
                "Resign adjudication",
                f"beyond +/-{adjudication.resign.min_abs_cp}cp "
                f"for {adjudication.resign.consecutive_plies} plies",
            )
        )
    if adjudication.syzygy:
        rows.append(("Syzygy adjudication", f"up to {adjudication.syzygy.max_pieces} pieces"))
    if adjudication.max_moves:
        rows.append(("Maximum moves", str(adjudication.max_moves)))

    return rows


def _engine_hardware_view(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> list[dict[str, str]]:
    engine_records = {engine.id: engine for engine in list_engine_records(connection)}
    active_hardware = active_engine_hardware_profiles(connection, tournament.id)
    rows: list[dict[str, str]] = []

    for engine_id in tournament.config.participants:
        engine = engine_records.get(engine_id)
        options = engine.uci_options if engine is not None else {}
        rows.append(
            {
                "engine_id": str(engine_id),
                "name": engine.name if engine is not None else f"Engine {engine_id}",
                "hash": _uci_option_label(options, "Hash", suffix="MB"),
                "threads": _uci_option_label(options, "Threads"),
                "hardware": _hardware_profiles_label(active_hardware.get(engine_id, ())),
            }
        )

    return rows


def _hardware_profiles_label(profiles: tuple[HardwareInfo, ...]) -> str:
    if not profiles:
        return "No active hardware"
    return " | ".join(_hardware_profile_label(profile) for profile in profiles)


def _hardware_profile_label(profile: HardwareInfo) -> str:
    return (
        f"{profile.cpu_model}, "
        f"{profile.physical_cores}P/{profile.logical_cores}T, "
        f"{profile.ram_gb}GB RAM"
    )


def _uci_option_label(
    options: dict[str, Any],
    name: str,
    *,
    suffix: str = "",
) -> str:
    value = _case_insensitive_option(options, name)
    if value is None or value == "":
        return "Not configured"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    label = str(value)
    if suffix and label[-len(suffix) :].lower() != suffix.lower():
        label = f"{label} {suffix}"
    return label


def _case_insensitive_option(options: dict[str, Any], name: str) -> Any:
    target = name.casefold()
    for option_name, value in options.items():
        if option_name.casefold() == target:
            return value
    return None


def _time_control_label(time_control: Any) -> str:
    category = time_control.category
    if category == "increment":
        return (
            f"{_milliseconds(time_control.initial_ms)}"
            f" + {_milliseconds(time_control.increment_ms)}"
        )
    if category == "movetime":
        return f"{_milliseconds(time_control.move_time_ms)} per move"
    if category == "movestogo":
        return f"{_milliseconds(time_control.initial_ms)} / {time_control.moves_to_go}"
    if category == "movenodes":
        return f"{time_control.nodes:,} nodes"
    return str(category)


def _milliseconds(value: int) -> str:
    if value >= 60_000 and value % 60_000 == 0:
        return f"{value // 60_000}m"
    if value >= 1_000 and value % 1_000 == 0:
        return f"{value // 1_000}s"
    return f"{value}ms"
