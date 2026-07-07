from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from cope.db import (
    DEFAULT_DB_PATH,
    ChatSettingsRecord,
    GameRecord,
    MoveRecord,
    TournamentRecord,
    category_tournament_count,
    connect_database,
    create_category,
    create_chat_message,
    create_engine,
    create_opening_suite,
    create_tournament,
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
    get_game,
    get_opening_suite,
    get_tournament,
    get_tournament_rating_commit,
    get_worker,
    list_categories,
    list_chat_messages,
    list_engine_records,
    list_engines,
    list_games,
    list_moves,
    list_opening_suites,
    list_suite_openings,
    list_tournaments,
    list_workers,
    mint_worker_token,
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
from cope.core.models import EngineSpec, HardwareInfo
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


class TournamentEventHub:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[None]]] = {}
        self._live: dict[int, dict[str, Any]] = {}

    def subscribe(self, tournament_id: int) -> asyncio.Queue[None]:
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=16)
        self._subscribers.setdefault(tournament_id, set()).add(queue)
        return queue

    def unsubscribe(self, tournament_id: int, queue: asyncio.Queue[None]) -> None:
        queues = self._subscribers.get(tournament_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(tournament_id, None)

    def publish(self, tournament_id: int, live: dict[str, Any] | None = None) -> None:
        if live is not None:
            if live.get("clear"):
                self._live.pop(tournament_id, None)
            else:
                self._live[tournament_id] = live
        for queue in tuple(self._subscribers.get(tournament_id, ())):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(None)

    def live(self, tournament_id: int) -> dict[str, Any] | None:
        return self._live.get(tournament_id)


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    app = FastAPI(title="COPE Chess")
    app.state.db_path = Path(db_path)
    app.state.tournament_events = TournamentEventHub()
    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_DIR / "static")),
        name="static",
    )

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
                "recent_games": _games_by_status(connection, "finished", limit=16),
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
        viewer_game = _tournament_viewer_game(games)
        viewer_moves = list_moves(connection, viewer_game.id) if viewer_game else ()
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
                "engine_data": _engine_data(viewer_game, viewer_moves),
                "clocks": _clock_data(viewer_moves),
                "standings": _standings(tournament, games, engines),
                "settings": _settings_view(connection, tournament),
                "engine_hardware": _engine_hardware_view(connection, tournament),
                "chat_messages": chat_messages,
                "opening": _opening_view(connection, viewer_game.opening_id) if viewer_game else None,
            },
        )

    @app.get("/tournaments/{tournament_id}/live.json")
    def tournament_live_snapshot(
        tournament_id: int,
        connection: sqlite3.Connection = Depends(_database),
    ):
        tournament = get_tournament(connection, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="tournament not found")

        return JSONResponse(_tournament_live_payload(connection, tournament))

    @app.get("/tournaments/{tournament_id}/events")
    async def tournament_events(tournament_id: int, request: Request):
        hub: TournamentEventHub = request.app.state.tournament_events

        def snapshot() -> dict[str, Any]:
            connection = connect_database(request.app.state.db_path)
            try:
                tournament = get_tournament(connection, tournament_id)
                if tournament is None:
                    return {"error": "tournament not found"}
                live = request.app.state.tournament_events.live(tournament_id)
                return _tournament_live_payload(connection, tournament, live)
            finally:
                connection.close()

        async def stream():
            queue = hub.subscribe(tournament_id)
            try:
                while True:
                    yield _sse_event("snapshot", snapshot())
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(queue.get(), timeout=15)
            finally:
                hub.unsubscribe(tournament_id, queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/internal/tournament-events")
    async def publish_tournament_event(request: Request):
        if request.client is not None and request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=403, detail="local event publisher required")

        payload = await request.json()
        tournament_id = int(payload["tournament_id"])
        live = payload.get("live")
        request.app.state.tournament_events.publish(tournament_id, live)
        return JSONResponse({"ok": True})

    @app.get("/games/{game_id}")
    def game_detail(
        game_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        game = get_game(connection, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")

        tournament = get_tournament(connection, game.tournament_id)
        moves = list_moves(connection, game.id)
        opening = _opening_view(connection, game.opening_id)
        return templates.TemplateResponse(
            request,
            "game_detail.html",
            {
                "active_nav": "archive",
                "game": game,
                "tournament": tournament,
                "moves": moves,
                "uci_moves": " ".join(move.uci for move in moves),
                "engines": _engine_names(connection),
                "opening": opening,
            },
        )

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
                "ratings": _rating_rows(connection, category.id) if category else [],
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

        games = _engine_games(connection, engine_id)
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
                "games": _games_by_status(connection, "finished", limit=50),
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
                workers=list_workers(connection),
                live_games=_games_by_status(connection, "live", limit=8),
                engines=_engine_names(connection),
                db_stats=_db_stats(connection),
                running_tournaments=[t for t in tournaments if t.status in {"scheduled", "running", "paused"}],
                complete_tournaments=_complete_uncommitted_tournaments(connection),
                recent_games=_games_by_status(connection, "finished", limit=6),
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

        delete_tournament(connection, tournament_id)
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

        request_tournament_rating_commit(connection, tournament)
        connection.commit()
        return RedirectResponse(
            url=f"/admin/tournaments/{tournament_id}?notice=" + quote("Rating commit requested."),
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
            ),
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
            ),
        )

    @app.post("/admin/workers/mint")
    async def admin_mint_worker(
        request: Request,
        connection: sqlite3.Connection = Depends(_database),
    ):
        form = await read_form(request)
        label = form_value(form, "label") or "worker"
        raw_ttl = form_value(form, "ttl_seconds")
        ttl_seconds = int(raw_ttl) if raw_ttl.isdigit() and int(raw_ttl) > 0 else 7200
        minted = mint_worker_token(connection, label=label, ttl_seconds=ttl_seconds)
        connection.commit()
        return templates.TemplateResponse(
            request,
            "admin/workers.html",
            _admin_context(
                request,
                "workers",
                worker_rows=_worker_admin_rows(connection),
                minted=minted,
                notice="Worker token minted. Copy it now - it will not be shown again.",
            ),
        )

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


def _admin_context(request: Request, section: str, **extra: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "active_nav": "admin",
        "admin_section": section,
        "notice": request.query_params.get("notice"),
        "error": request.query_params.get("error"),
        "errors": [],
    }
    context.update(extra)
    return context


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


def _state_view(status: str, label: str, detail: str) -> dict[str, str]:
    return {"status": status, "label": label, "detail": detail}


def _worker_token_view(worker) -> dict[str, str]:
    if worker.token_expires_at is None:
        if worker.status == "revoked":
            return _state_view("revoked", "Revoked", "Token removed")
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
    row = connection.execute(
        """
        SELECT
          game_assignments.status AS assignment_status,
          games.id AS game_id,
          games.round,
          games.white_engine_id,
          games.black_engine_id,
          tournaments.id AS tournament_id,
          tournaments.name AS tournament_name,
          COUNT(moves.ply) AS plies
        FROM game_assignments
        JOIN games ON games.id = game_assignments.game_id
        JOIN tournaments ON tournaments.id = games.tournament_id
        LEFT JOIN moves ON moves.game_id = games.id
        WHERE (game_assignments.white_worker_id = ? OR game_assignments.black_worker_id = ?)
          AND game_assignments.status IN ('assigned', 'acked', 'live')
          AND games.status IN ('assigned', 'live')
        GROUP BY game_assignments.id
        ORDER BY game_assignments.sent_at DESC, game_assignments.id DESC
        LIMIT 1
        """,
        (worker_id, worker_id),
    ).fetchone()
    if row is None:
        return None

    status = row["assignment_status"]
    verb = "Playing" if status == "live" else "Assigned"
    white = engines.get(row["white_engine_id"], f"Engine {row['white_engine_id']}")
    black = engines.get(row["black_engine_id"], f"Engine {row['black_engine_id']}")
    return _activity_view(
        status,
        verb,
        f"Game #{row['game_id']} in round {row['round']}",
        f"{row['tournament_name']}: {white} vs {black}",
        href=f"/admin/tournaments/{row['tournament_id']}",
        meta=f"{row['plies']} plies recorded",
    )


def _worker_idle_activity(worker, effective_status: str) -> dict[str, Any]:
    states = {
        "minted": ("pending", "Awaiting registration", "Token has not been used", "No worker process has connected with this token.", False),
        "ready": ("ready", "Idle", "Waiting for an eligible game", "The worker server is polling for tournament work.", False),
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


def _home_game_cards(
    connection: sqlite3.Connection,
    engines: dict[int, str],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for game in _active_games(connection):
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


def _active_games(connection: sqlite3.Connection) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE status IN ('live', 'assigned')
        ORDER BY CASE status WHEN 'live' THEN 0 ELSE 1 END, id DESC
        """
    )
    return tuple(_game_from_row(row) for row in rows)


def _upcoming_rows(
    connection: sqlite3.Connection,
    engines: dict[int, str],
    *,
    limit: int,
) -> list[dict[str, str]]:
    pending_games = _upcoming_games(connection, limit=limit)
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
            "href": f"/games/{game.id}",
            "tournament": tournament_names.get(game.tournament_id, f"Tournament {game.tournament_id}"),
            "round": str(game.round),
            "white": engines.get(game.white_engine_id, f"Engine {game.white_engine_id}"),
            "black": engines.get(game.black_engine_id, f"Engine {game.black_engine_id}"),
            "status": game.status,
        }
        for game in pending_games
    )

    return rows[:limit]


def _upcoming_games(connection: sqlite3.Connection, *, limit: int) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE status = 'pending'
        ORDER BY id ASC
        LIMIT ?
        """,
        (limit,),
    )
    return tuple(_game_from_row(row) for row in rows)


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
        "standings": _standings(tournament, games, engines),
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
                    if key in {"depth", "nps", "nodes", "eval", "pv"}
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


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


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
            "pv": "not recorded",
        }

    nps = "-"
    if move.nodes is not None and move.time_ms > 0:
        nps = f"{int(move.nodes / (move.time_ms / 1000)):,}"

    return {
        "depth": str(move.depth) if move.depth is not None else "-",
        "nps": nps,
        "nodes": f"{move.nodes:,}" if move.nodes is not None else "-",
        "eval": _eval_label(move),
        "pv": "not recorded",
    }


def _eval_label(move: MoveRecord) -> str:
    if move.eval_mate is not None:
        return f"#{move.eval_mate}"
    if move.eval_cp is not None:
        return f"{move.eval_cp / 100:+.2f}"
    return "-"


def _opening_view(connection: sqlite3.Connection, opening_id: int | None) -> dict[str, str] | None:
    if opening_id is None:
        return None
    row = connection.execute(
        "SELECT name, fen FROM openings WHERE id = ?",
        (opening_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "name": row["name"] or "Opening",
        "fen": row["fen"],
    }


def _games_by_status(
    connection: sqlite3.Connection,
    status: str,
    *,
    limit: int,
) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE status = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (status, limit),
    )
    return tuple(_game_from_row(row) for row in rows)


def _engine_games(
    connection: sqlite3.Connection,
    engine_id: int,
) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE white_engine_id = ? OR black_engine_id = ?
        ORDER BY id DESC
        LIMIT 50
        """,
        (engine_id, engine_id),
    )
    return tuple(_game_from_row(row) for row in rows)


def _rating_rows(connection: sqlite3.Connection, category_id: int) -> list[dict[str, Any]]:
    if not _table_exists(connection, "ratings"):
        return []

    rows = connection.execute(
        """
        SELECT engines.*, ratings.elo, ratings.games_played, ratings.updated_at
        FROM ratings
        JOIN engines ON engines.id = ratings.engine_id
        WHERE ratings.category_id = ?
        ORDER BY ratings.elo DESC, engines.name
        """,
        (category_id,),
    )
    return [
        {
            "engine": _engine_spec_from_row(row),
            "elo": row["elo"],
            "games_played": row["games_played"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


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

    rows = [
        {
            "engine_id": engine_id,
            "name": engines.get(engine_id, f"Engine {engine_id}"),
            "points": points[engine_id],
            "played": played[engine_id],
        }
        for engine_id in points
    ]
    rows.sort(key=lambda row: (-row["points"], row["name"]))
    return rows


def _db_stats(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "categories": _count_rows(connection, "categories"),
        "engines": _count_rows(connection, "engines"),
        "tournaments": _count_rows(connection, "tournaments"),
        "games": _count_rows(connection, "games"),
        "workers": _count_rows(connection, "workers"),
        "opening_suites": _count_rows(connection, "opening_suites"),
    }


def _complete_uncommitted_tournaments(
    connection: sqlite3.Connection,
) -> tuple[TournamentRecord, ...]:
    committed_ids = {
        row["tournament_id"]
        for row in connection.execute("SELECT tournament_id FROM tournament_rating_commits")
    }
    return tuple(
        tournament
        for tournament in list_tournaments(connection)
        if tournament.status == "finished" and tournament.id not in committed_ids
    )


def _tournaments_for_category(
    connection: sqlite3.Connection,
    category_id: int,
) -> tuple[TournamentRecord, ...]:
    return tuple(
        tournament
        for tournament in list_tournaments(connection)
        if tournament.category_id == category_id
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(connection, table_name):
        return 0
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"])


def _game_from_row(row: sqlite3.Row) -> GameRecord:
    return GameRecord(
        id=row["id"],
        tournament_id=row["tournament_id"],
        round=row["round"],
        pair_index=row["pair_index"],
        white_engine_id=row["white_engine_id"],
        black_engine_id=row["black_engine_id"],
        opening_id=row["opening_id"],
        status=row["status"],
        result=row["result"],
        termination=row["termination"],
        pgn=row["pgn"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _engine_spec_from_row(row: sqlite3.Row) -> EngineSpec:
    return EngineSpec(
        engine_id=row["id"],
        name=row["name"],
        git_url=row["git_url"],
        branch=row["branch"],
        commit=row["commit_hash"],
        build_cmd=row["build_cmd"],
        binary_path=row["binary_path"],
        uci_options=json.loads(row["uci_options"]),
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
            ("Hardware", config.hardware_mode.value.title()),
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
    active_hardware = _active_engine_hardware(connection, tournament.id)
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


def _active_engine_hardware(
    connection: sqlite3.Connection,
    tournament_id: int,
) -> dict[int, tuple[HardwareInfo, ...]]:
    rows = connection.execute(
        """
        SELECT
          games.white_engine_id,
          games.black_engine_id,
          game_assignments.hardware_mode,
          white_workers.hw AS white_hw,
          black_workers.hw AS black_hw
        FROM game_assignments
        JOIN games ON games.id = game_assignments.game_id
        LEFT JOIN workers AS white_workers
          ON white_workers.id = game_assignments.white_worker_id
          AND white_workers.status IN ('connected', 'building', 'ready', 'busy')
        LEFT JOIN workers AS black_workers
          ON black_workers.id = game_assignments.black_worker_id
          AND black_workers.status IN ('connected', 'building', 'ready', 'busy')
        WHERE games.tournament_id = ?
          AND games.status IN ('assigned', 'live')
          AND game_assignments.status IN ('assigned', 'acked', 'live')
        """,
        (tournament_id,),
    )

    hardware_by_engine: dict[int, list[HardwareInfo]] = {}
    seen: dict[int, set[str]] = {}
    for row in rows:
        white_hw = _hardware_from_json(row["white_hw"])
        black_hw = _hardware_from_json(row["black_hw"])

        if row["hardware_mode"] == "shared":
            white_hw = white_hw or black_hw
            black_hw = black_hw or white_hw

        for engine_id, hw in (
            (row["white_engine_id"], white_hw),
            (row["black_engine_id"], black_hw),
        ):
            if hw is None:
                continue
            profile_key = hw.model_dump_json()
            engine_seen = seen.setdefault(engine_id, set())
            if profile_key in engine_seen:
                continue
            engine_seen.add(profile_key)
            hardware_by_engine.setdefault(engine_id, []).append(hw)

    return {
        engine_id: tuple(profiles)
        for engine_id, profiles in hardware_by_engine.items()
    }


def _hardware_from_json(value: str | None) -> HardwareInfo | None:
    if value is None:
        return None
    try:
        return HardwareInfo.model_validate_json(value)
    except ValueError:
        return None


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
