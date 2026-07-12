from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import chess
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.datastructures import UploadFile

from cope.core.models import TournamentConfig
from cope.db import (
    ChatSettingsRecord,
    category_tournament_count,
    create_category,
    create_engine,
    create_engine_version,
    create_opening_suite,
    create_tournament,
    create_worker,
    create_worker_pool,
    database_stats,
    database_schema_version,
    delete_category,
    delete_chat_message,
    delete_engine,
    delete_engine_version,
    delete_opening_suite,
    delete_tournament,
    delete_worker,
    engine_game_count,
    get_category,
    get_chat_settings,
    get_engine_record,
    get_engine_family,
    get_engine_version_record,
    get_game,
    get_opening_suite,
    get_tournament,
    get_tournament_rating_commit,
    get_worker,
    get_worker_by_session_id,
    get_worker_pool,
    list_categories,
    list_chat_messages,
    list_engine_games,
    list_engine_records,
    list_engine_families,
    list_engine_versions,
    list_games,
    list_games_by_status,
    list_opening_suites,
    list_rating_rows,
    list_service_heartbeats,
    list_suite_openings,
    list_tournaments,
    list_uncommitted_finished_tournaments,
    list_workers,
    mint_worker_pool_token,
    mint_worker_token_for_worker,
    replace_suite_openings,
    request_tournament_rating_commit,
    revoke_worker,
    revoke_worker_pool,
    set_tournament_status,
    suite_opening_count,
    update_category,
    update_chat_settings,
    update_engine,
    update_engine_version,
    update_opening_suite,
    update_tournament,
    update_worker_label,
)
from cope.web import forms
from cope.web.openings import parse_opening_uploads, parse_openings
from cope.web.requests import read_form
from cope.version import app_version


LOG = logging.getLogger("cope.web.api")
ENGINE_UPLOAD_CHUNK_BYTES = 1024 * 1024


def _engine_binary_root() -> Path:
    return Path(os.environ.get("COPE_ENGINE_BINARY_DIR", "/var/lib/cope/engine-binaries")).expanduser().resolve()


async def _store_engine_upload(upload: UploadFile) -> tuple[str, int]:
    root = _engine_binary_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    maximum = int(os.environ.get("COPE_ENGINE_BINARY_MAX_BYTES", str(1024 * 1024 * 1024)))
    temporary = root / f".upload-{uuid.uuid4().hex}"
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("xb") as output:
            while True:
                chunk = await upload.read(ENGINE_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(status_code=413, detail=f"Engine binary exceeds the {maximum}-byte upload limit.")
                digest.update(chunk)
                output.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="The uploaded engine binary is empty.")
            output.flush()
            os.fsync(output.fileno())
        sha256 = digest.hexdigest()
        destination = root / sha256
        if destination.exists():
            temporary.unlink()
            if destination.stat().st_size != size:
                raise HTTPException(status_code=500, detail="Stored engine artifact failed an integrity check.")
        else:
            os.replace(temporary, destination)
            destination.chmod(0o600)
        return sha256, size
    finally:
        await upload.close()
        if temporary.exists():
            temporary.unlink()


def _remove_unreferenced_artifact(connection: sqlite3.Connection, storage_key: str) -> None:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM engine_versions WHERE storage_key = ?", (storage_key,)
    ).fetchone()
    if row is not None and int(row["count"]) == 0:
        try:
            (_engine_binary_root() / storage_key).unlink(missing_ok=True)
        except OSError:
            LOG.exception("could not remove unreferenced engine artifact storage_key=%s", storage_key)


def _engine_version_admin_payload(version) -> dict[str, Any]:
    payload = jsonable_encoder(version)
    payload["active"] = version.version_active
    payload["storage_status"] = _engine_artifact_status(version)
    return payload


def _engine_artifact_status(version) -> str:
    path = _engine_binary_root() / version.storage_key
    if not path.is_file():
        return "missing"
    if path.stat().st_size != version.binary_size:
        return "corrupt"
    return "ready"


class TournamentPayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    config: TournamentConfig

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class TournamentStatusPayload(BaseModel):
    action: str = Field(min_length=1, max_length=20)


class EnginePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    author: str = Field(default="", max_length=120)
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_engine_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("engine name cannot be blank")
        return value

    @field_validator("author")
    @classmethod
    def strip_engine_author(cls, value: str) -> str:
        return value.strip()


class EngineVersionUpdatePayload(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    uci_options: dict[str, str | int | bool] = Field(default_factory=dict)
    active: bool = True

    @field_validator("version")
    @classmethod
    def strip_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("version cannot be blank")
        return value


class CategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    default_config: dict[str, Any]
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class WorkerPayload(BaseModel):
    label: str = Field(default="worker", min_length=1, max_length=80)
    assigned_threads: int = Field(default=1, gt=0)
    assigned_hash_mb: int = Field(default=32, gt=0)


class WorkerTokenPayload(BaseModel):
    ttl_seconds: int = Field(default=7200, ge=60, le=86_400)


class WorkerPoolPayload(BaseModel):
    label: str = Field(default="machine pool", min_length=1, max_length=80)
    slot_count: int = Field(ge=1, le=512)
    assigned_threads: int = Field(default=1, gt=0)
    assigned_hash_mb: int = Field(default=32, gt=0)
    ttl_seconds: int = Field(default=900, ge=60, le=7200)

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Pool label is required.")
        return stripped


class WorkerPoolTokenPayload(BaseModel):
    ttl_seconds: int = Field(default=900, ge=60, le=7200)


class ChatSettingsPayload(BaseModel):
    enabled: bool
    max_message_length: int = Field(ge=1, le=2_000)
    allow_anonymous_names: bool


def register_api_routes(app: FastAPI) -> None:
    from cope.web import app as web_app

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    @app.get("/api/session")
    def session(request: Request):
        token = web_app._admin_token(request)
        authenticated = bool(token and web_app._admin_session_valid(request, token))
        response = _json(
            {
                "admin_configured": bool(token),
                "authenticated": authenticated,
                "secure_context": web_app._request_is_secure_or_local(request),
                "csrf_token": (
                    web_app._csrf_token(request, token)
                    if token and authenticated
                    else ""
                ),
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/session")
    async def create_session(request: Request):
        token = web_app._admin_token(request)
        if not token:
            raise HTTPException(
                status_code=503,
                detail="Admin access is not configured.",
            )
        if not web_app._request_is_secure_or_local(request):
            raise HTTPException(status_code=403, detail="Admin access requires HTTPS.")

        form = await read_form(request)
        supplied = forms.form_value(form, "token")
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Invalid admin token.")

        nonce = secrets.token_urlsafe(32)
        response = _json(
            {
                "authenticated": True,
                "csrf_token": web_app._csrf_for_nonce(token, nonce),
                "message": "Signed in.",
            }
        )
        response.set_cookie(
            "cope_admin_session",
            web_app._signed_value(token, nonce),
            httponly=True,
            secure=web_app._request_is_secure(request),
            samesite="lax",
            max_age=web_app.ADMIN_SESSION_MAX_AGE_SECONDS,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.delete("/api/session")
    def delete_session():
        response = _json({"authenticated": False, "message": "Signed out."})
        response.delete_cookie("cope_admin_session")
        response.headers["Cache-Control"] = "no-store"
        return response

    # ------------------------------------------------------------------
    # Public reads
    # ------------------------------------------------------------------

    @app.get("/api/home")
    def public_home(connection: sqlite3.Connection = Depends(web_app._database)):
        engines = web_app._engine_names(connection)
        return _json(
            {
                "running_tournaments": web_app._home_tournament_cards(connection, engines),
                "upcoming_rows": web_app._upcoming_rows(connection, engines, limit=16),
                "recent_games": list_games_by_status(connection, "finished", limit=16),
                "engines": engines,
                "tournament_names": web_app._tournament_names(connection),
            }
        )

    @app.get("/api/tournaments")
    def public_tournaments(connection: sqlite3.Connection = Depends(web_app._database)):
        engines = web_app._engine_names(connection)
        items = [
            web_app._tournament_summary(connection, tournament, engines)
            for tournament in list_tournaments(connection)
            if tournament.status != "draft"
        ]
        return _json(
            {
                "tournaments": items,
                "tournament_stats": web_app._tournament_index_stats(items),
            }
        )

    @app.get("/api/tournaments/{tournament_id}")
    def public_tournament(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        tournament = _require_tournament(connection, tournament_id)
        if tournament.status == "draft":
            raise HTTPException(status_code=404, detail="Tournament not found.")
        engines = web_app._engine_names(connection)
        games = list_games(connection, tournament.id)
        viewer_game = web_app._selected_viewer_game(request, games)
        viewer_moves = (
            web_app.list_moves(connection, viewer_game.id) if viewer_game else ()
        )
        viewer_locked = bool(
            request.query_params.get("game_id") is not None
            and viewer_game is not None
            and viewer_game.status not in {"assigned", "live"}
        )
        chat_settings = get_chat_settings(connection)
        game_live = (
            request.app.state.stream_hub.tournament_live(tournament.id, viewer_game.id)
            if viewer_game
            else None
        )
        engine_data = web_app._engine_data(viewer_game, viewer_moves)
        clocks = web_app._clock_data(viewer_moves)
        clock_state = web_app._persisted_clock_state(viewer_game, viewer_moves)
        if isinstance(game_live, dict):
            engine_data = web_app._merge_engine_data(
                engine_data,
                game_live.get("engine_data"),
            )
            clocks = web_app._merge_clock_data(clocks, game_live.get("clocks"))
            if isinstance(game_live.get("clock_state"), dict):
                clock_state = game_live["clock_state"]
        return _json(
            {
                "tournament": tournament,
                "games": games,
                "engines": engines,
                "viewer_game": viewer_game,
                "viewer_moves": [web_app._move_payload(move) for move in viewer_moves],
                "viewer_locked": viewer_locked,
                "engine_data": engine_data,
                "clocks": clocks,
                "clock_state": clock_state,
                "standings": web_app._standings(connection, tournament, games, engines),
                "settings": _settings_rows(web_app._settings_view(connection, tournament)),
                "engine_hardware": web_app._engine_hardware_view(connection, tournament),
                "chat_messages": list_chat_messages(
                    connection,
                    limit=30,
                    tournament_id=tournament_id,
                ),
                "chat_settings": chat_settings,
                "opening": (
                    web_app._opening_view(connection, viewer_game.opening_id)
                    if viewer_game
                    else None
                ),
            }
        )

    @app.get("/api/ratings")
    def public_ratings(
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        categories = list_categories(connection, active_only=True)
        category_id = web_app._selected_category_id(request, categories)
        category = get_category(connection, category_id) if category_id else None
        return _json(
            {
                "category": category,
                "categories": categories,
                "ratings": list_rating_rows(connection, category.id) if category else [],
            }
        )

    @app.get("/api/engines/{engine_id}")
    def public_engine(
        engine_id: int,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        engine = get_engine_record(connection, engine_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="Engine not found.")
        games = list_engine_games(connection, engine_id)
        return _json(
            {
                "engine": engine,
                "games": games,
                "engines": web_app._engine_names(connection),
                "record": web_app._engine_record_summary(games, engine_id),
            }
        )

    @app.get("/api/archive")
    def public_archive(connection: sqlite3.Connection = Depends(web_app._database)):
        engines = web_app._engine_names(connection)
        tournaments = [
            web_app._tournament_summary(connection, tournament, engines)
            for tournament in list_tournaments(connection)
            if tournament.status in {"finished", "aborted"}
        ]
        return _json(
            {
                "tournaments": tournaments,
                "games": list_games_by_status(connection, "finished", limit=50),
                "engines": engines,
            }
        )

    @app.post("/api/tournaments/{tournament_id}/chat")
    async def public_chat(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        form = await read_form(request)
        web_app._require_public_chat_tournament(connection, tournament_id)
        message = web_app._create_chat_message_from_form(
            connection,
            form,
            tournament_id=tournament_id,
        )
        if message is not None:
            web_app._publish_chat_message(request, tournament_id, message)
        return _json(
            {"message": message},
            status_code=201,
        )

    @app.get("/api/games/{game_id}/pgn")
    def public_game_pgn(
        game_id: int,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        game = get_game(connection, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found.")
        tournament = get_tournament(connection, game.tournament_id)
        if tournament is None or tournament.status == "draft":
            raise HTTPException(status_code=404, detail="Game not found.")
        if game.status != "finished" or not game.pgn:
            raise HTTPException(status_code=409, detail="PGN is not available until the game finishes.")
        return Response(
            content=game.pgn,
            media_type="application/x-chess-pgn; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="cope-game-{game.id}.pgn"',
            },
        )

    # ------------------------------------------------------------------
    # Admin reads and writes
    # ------------------------------------------------------------------

    @app.get("/api/admin/dashboard")
    def admin_dashboard(connection: sqlite3.Connection = Depends(web_app._database)):
        tournaments = list_tournaments(connection)
        return _json(
            {
                "workers": web_app._worker_admin_rows(connection, limit=20),
                "live_games": list_games_by_status(connection, "live", limit=8),
                "engines": web_app._engine_names(connection),
                "db_stats": database_stats(connection),
                "running_tournaments": [
                    tournament
                    for tournament in tournaments
                    if tournament.status in {"scheduled", "running", "paused"}
                ],
                "complete_tournaments": list_uncommitted_finished_tournaments(connection),
                "recent_games": list_games_by_status(connection, "finished", limit=6),
                "system": {
                    "version": app_version(),
                    "schema_version": database_schema_version(connection),
                    "services": list_service_heartbeats(connection),
                },
            }
        )

    @app.get("/api/admin/tournaments/form")
    def admin_tournament_form(
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        return _json(_tournament_form_payload(web_app, request, connection))

    @app.get("/api/admin/tournaments")
    def admin_tournaments(
        status: str = "",
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        engines = web_app._engine_names(connection)
        items = [
            web_app._tournament_summary(connection, tournament, engines)
            for tournament in list_tournaments(connection)
            if not status or tournament.status == status
        ]
        return _json(
            {
                "tournaments": items,
                "status_filter": status,
                "statuses": [
                    "draft",
                    "scheduled",
                    "running",
                    "paused",
                    "finished",
                    "aborted",
                ],
            }
        )

    @app.post("/api/admin/tournaments")
    def admin_create_tournament(
        payload: TournamentPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        config = _validated_tournament_config(connection, payload.config)
        tournament_id = create_tournament(connection, payload.name, config)
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json(
            {
                "id": tournament_id,
                "message": "Tournament draft created.",
            },
            status_code=201,
        )

    @app.get("/api/admin/tournaments/{tournament_id}")
    def admin_tournament(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        tournament = _require_tournament(connection, tournament_id)
        payload: dict[str, Any] = {
            "tournament": tournament,
            "games": list_games(connection, tournament.id),
            "engines": web_app._engine_names(connection),
            "category": (
                get_category(connection, tournament.category_id)
                if tournament.category_id is not None
                else None
            ),
            "settings": _settings_rows(web_app._settings_view(connection, tournament)),
            "commit": get_tournament_rating_commit(connection, tournament.id),
            "actions": web_app.TOURNAMENT_ACTIONS.get(tournament.status, {}),
            "capabilities": {
                "editable": tournament.status == "draft",
                "deletable": tournament.status not in {"scheduled", "running"},
                "can_commit_ratings": (
                    tournament.status == "finished"
                    and tournament.config.rated
                    and tournament.category_id is not None
                ),
            },
        }
        if tournament.status == "draft":
            payload["form"] = _tournament_form_payload(
                web_app,
                request,
                connection,
                tournament=tournament,
            )
        return _json(payload)

    @app.put("/api/admin/tournaments/{tournament_id}")
    def admin_update_tournament(
        tournament_id: int,
        payload: TournamentPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        tournament = _require_tournament(connection, tournament_id)
        if tournament.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft tournaments can be edited.",
            )
        config = _validated_tournament_config(connection, payload.config)
        update_tournament(connection, tournament_id, name=payload.name, config=config)
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"id": tournament_id, "message": "Tournament updated."})

    @app.post("/api/admin/tournaments/{tournament_id}/status")
    def admin_tournament_status(
        tournament_id: int,
        payload: TournamentStatusPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        tournament = _require_tournament(connection, tournament_id)
        action = payload.action
        allowed = web_app.TOURNAMENT_ACTIONS.get(tournament.status, {})
        if action not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot {action or 'change'} a {tournament.status} tournament.",
            )
        target = allowed[action]
        set_tournament_status(connection, tournament_id, target)
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json(
            {
                "status": target,
                "message": f"Tournament {target}.",
            }
        )

    @app.post("/api/admin/tournaments/{tournament_id}/commit-results")
    def admin_commit_tournament_results(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        tournament = _require_tournament(connection, tournament_id)
        if tournament.status != "finished":
            raise HTTPException(status_code=409, detail="Tournament is not complete.")
        try:
            requested = request_tournament_rating_commit(connection, tournament)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json(
            {
                "message": (
                    "Rating commit requested."
                    if requested
                    else "Rating commit is already queued or applied."
                )
            }
        )

    @app.delete("/api/admin/tournaments/{tournament_id}")
    def admin_delete_tournament(
        tournament_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        tournament = _require_tournament(connection, tournament_id)
        if tournament.status in {"scheduled", "running"}:
            raise HTTPException(
                status_code=409,
                detail="Abort the tournament before deleting it.",
            )
        try:
            delete_tournament(connection, tournament_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Tournament deleted."})

    # Engines

    @app.get("/api/admin/engines")
    def admin_engines(connection: sqlite3.Connection = Depends(web_app._database)):
        engines = list_engine_families(connection)
        return _json(
            {
                "engines": [
                    {
                        **jsonable_encoder(engine),
                        "versions": [_engine_version_admin_payload(version) for version in list_engine_versions(connection, engine.id)],
                    }
                    for engine in engines
                ],
                "game_counts": {version.id: engine_game_count(connection, version.id)
                                for version in list_engine_records(connection)},
            }
        )

    @app.get("/api/admin/engines/form")
    def admin_engine_form():
        return _json(
            {
                "engine": None,
                "defaults": {
                    "name": "",
                    "author": "",
                    "active": True,
                },
            }
        )

    @app.get("/api/admin/engines/{engine_id}")
    def admin_engine(
        engine_id: int,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        engine = get_engine_family(connection, engine_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="Engine not found.")
        return _json(
            {
                "engine": engine,
                "versions": [_engine_version_admin_payload(version) for version in list_engine_versions(connection, engine_id)],
            }
        )

    @app.post("/api/admin/engines")
    def admin_create_engine(
        payload: EnginePayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        try:
            engine_id = create_engine(
                connection, name=payload.name.strip(), author=payload.author.strip(), active=payload.active
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json(
            {"id": engine_id, "message": "Engine registered."},
            status_code=201,
        )

    @app.put("/api/admin/engines/{engine_id}")
    def admin_update_engine(
        engine_id: int,
        payload: EnginePayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_engine_family(connection, engine_id) is None:
            raise HTTPException(status_code=404, detail="Engine not found.")
        try:
            update_engine(
                connection,
                engine_id,
                name=payload.name.strip(),
                author=payload.author.strip(),
                active=payload.active,
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json({"id": engine_id, "message": "Engine updated."})

    @app.delete("/api/admin/engines/{engine_id}")
    def admin_delete_engine(
        engine_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_engine_family(connection, engine_id) is None:
            raise HTTPException(status_code=404, detail="Engine not found.")
        try:
            delete_engine(connection, engine_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Engine deleted."})

    @app.post("/api/admin/engines/{engine_id}/versions")
    async def admin_create_engine_version(
        engine_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_engine_family(connection, engine_id) is None:
            raise HTTPException(status_code=404, detail="Engine not found.")
        form = await request.form()
        upload = form.get("binary")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(status_code=422, detail="Choose an engine binary to upload.")
        version = str(form.get("version") or "").strip()
        if not version or len(version) > 80:
            raise HTTPException(status_code=422, detail="Version is required and must be at most 80 characters.")
        try:
            options = json.loads(str(form.get("uci_options") or "{}"))
            if not isinstance(options, dict) or any(not str(name).strip() for name in options):
                raise ValueError
            if any(not isinstance(value, (str, int, bool)) for value in options.values()):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=422, detail="Default UCI options must be a JSON object.")
        active = str(form.get("active") or "true").lower() in {"1", "true", "yes", "on"}
        binary_filename = upload.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not binary_filename or len(binary_filename) > 255 or any(ord(char) < 32 for char in binary_filename):
            raise HTTPException(status_code=422, detail="The uploaded binary filename is invalid.")
        artifact = await _store_engine_upload(upload)
        try:
            version_id = create_engine_version(
                connection,
                engine_id=engine_id,
                version=version,
                binary_filename=binary_filename,
                binary_sha256=artifact[0],
                binary_size=artifact[1],
                storage_key=artifact[0],
                uci_options=options,
                active=active,
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            _remove_unreferenced_artifact(connection, artifact[0])
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        except Exception:
            connection.rollback()
            _remove_unreferenced_artifact(connection, artifact[0])
            raise
        _publish_admin_change(web_app, request)
        return _json({"id": version_id, "message": f"Version {version} uploaded and verified."}, status_code=201)

    @app.put("/api/admin/engine-versions/{version_id}")
    def admin_update_engine_version(
        version_id: int,
        payload: EngineVersionUpdatePayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_engine_version_record(connection, version_id) is None:
            raise HTTPException(status_code=404, detail="Engine version not found.")
        options = payload.uci_options
        if any(not str(name).strip() for name in options):
            raise HTTPException(status_code=422, detail="Default UCI options must be an object with non-empty names.")
        try:
            update_engine_version(
                connection,
                version_id,
                version=payload.version,
                uci_options=options,
                active=payload.active,
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json({"id": version_id, "message": "Engine version updated."})

    @app.delete("/api/admin/engine-versions/{version_id}")
    def admin_delete_engine_version(
        version_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        try:
            storage_key = delete_engine_version(connection, version_id)
            connection.commit()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _remove_unreferenced_artifact(connection, storage_key)
        _publish_admin_change(web_app, request)
        return _json({"message": "Engine version deleted."})

    @app.get("/api/worker/engine-binaries/{version_id}")
    def worker_engine_binary(
        version_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        authorization = request.headers.get("authorization", "")
        scheme, _, credential = authorization.partition(" ")
        worker = get_worker_by_session_id(connection, credential) if scheme.lower() == "bearer" and credential else None
        if worker is None or worker.status not in {"connected", "downloading", "ready", "busy"}:
            raise HTTPException(status_code=401, detail="A current worker session is required.")
        version = get_engine_version_record(connection, version_id)
        if version is None or not version.active:
            raise HTTPException(status_code=404, detail="Engine version is unavailable.")
        path = _engine_binary_root() / version.storage_key
        if not path.is_file():
            LOG.error("registered engine binary is missing version_id=%s path=%s", version_id, path)
            raise HTTPException(status_code=503, detail="Engine binary is missing from server storage.")
        response = FileResponse(
            path,
            media_type="application/octet-stream",
            filename=version.binary_filename,
        )
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        response.headers["X-Engine-SHA256"] = version.binary_sha256
        return response

    # Categories

    @app.get("/api/admin/categories")
    def admin_categories(connection: sqlite3.Connection = Depends(web_app._database)):
        categories = list_categories(connection)
        return _json(
            {
                "categories": categories,
                "tournament_counts": {
                    category.id: category_tournament_count(connection, category.id)
                    for category in categories
                },
            }
        )

    @app.get("/api/admin/categories/form")
    def admin_category_form(
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        return _json(
            {
                "category": None,
                "default_config": _category_settings({}),
                "engine_options": [
                    engine for engine in list_engine_records(connection) if engine.active
                ],
                "opening_suites": list_opening_suites(connection),
                "tournaments": [],
            }
        )

    @app.get("/api/admin/categories/{category_id}")
    def admin_category(
        category_id: int,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        category = get_category(connection, category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="Category not found.")
        return _json(
            {
                "category": category,
                "default_config": _category_settings(category.default_config),
                "engine_options": [
                    engine for engine in list_engine_records(connection) if engine.active
                ],
                "opening_suites": list_opening_suites(connection),
                "tournaments": [
                    tournament
                    for tournament in list_tournaments(connection)
                    if tournament.category_id == category_id
                ],
            }
        )

    @app.post("/api/admin/categories")
    def admin_create_category(
        payload: CategoryPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        defaults = _category_settings(payload.default_config)
        _validate_opening_suite_reference(connection, defaults.get("opening_suite_id"))
        try:
            category_id = create_category(
                connection,
                name=payload.name,
                description=payload.description,
                default_config=defaults,
                active=payload.active,
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json(
            {"id": category_id, "message": "Category created."},
            status_code=201,
        )

    @app.put("/api/admin/categories/{category_id}")
    def admin_update_category(
        category_id: int,
        payload: CategoryPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_category(connection, category_id) is None:
            raise HTTPException(status_code=404, detail="Category not found.")
        defaults = _category_settings(payload.default_config)
        _validate_opening_suite_reference(connection, defaults.get("opening_suite_id"))
        try:
            update_category(
                connection,
                category_id,
                name=payload.name,
                description=payload.description,
                default_config=defaults,
                active=payload.active,
            )
            _propagate_category_defaults(connection, category_id, defaults)
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json({"id": category_id, "message": "Category updated."})

    @app.delete("/api/admin/categories/{category_id}")
    def admin_delete_category(
        category_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_category(connection, category_id) is None:
            raise HTTPException(status_code=404, detail="Category not found.")
        try:
            delete_category(connection, category_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Category deleted."})

    # Opening suites

    @app.get("/api/admin/openings")
    def admin_openings(connection: sqlite3.Connection = Depends(web_app._database)):
        suites = list_opening_suites(connection)
        tournaments = list_tournaments(connection)
        return _json(
            {
                "suites": suites,
                "opening_counts": {
                    suite.id: suite_opening_count(connection, suite.id) for suite in suites
                },
                "usage_counts": {
                    suite.id: sum(
                        tournament.config.opening_suite_id == suite.id
                        for tournament in tournaments
                    )
                    for suite in suites
                },
            }
        )

    @app.get("/api/admin/openings/form")
    def admin_opening_form():
        return _json(
            {
                "suite": None,
                "openings": [],
                "positions_text": "",
                "usage_count": 0,
                "limits": {
                    "accepted_extensions": [".pgn", ".epd", ".fen", ".txt"],
                },
            }
        )

    @app.get("/api/admin/openings/{suite_id}")
    def admin_opening(
        suite_id: int,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        suite = get_opening_suite(connection, suite_id)
        if suite is None:
            raise HTTPException(status_code=404, detail="Opening suite not found.")
        openings = list_suite_openings(connection, suite_id)
        return _json(
            {
                "suite": suite,
                "openings": openings,
                "positions_text": "\n".join(
                    f"{opening.name}; {opening.fen}" if opening.name else opening.fen
                    for opening in openings
                ),
                "usage_count": sum(
                    tournament.config.opening_suite_id == suite_id
                    for tournament in list_tournaments(connection)
                ),
            }
        )

    @app.post("/api/admin/openings")
    async def admin_create_opening(
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        values, files = await _read_opening_form(request)
        name = values.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Suite name is required.")
        openings = _opening_values(values.get("positions", ""), files)
        try:
            suite_id = create_opening_suite(
                connection,
                name=name,
                description=values.get("description", "").strip(),
            )
            replace_suite_openings(connection, suite_id, openings)
            connection.commit()
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json(
            {
                "id": suite_id,
                "position_count": len(openings),
                "message": "Opening suite created.",
            },
            status_code=201,
        )

    @app.put("/api/admin/openings/{suite_id}")
    async def admin_update_opening(
        suite_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_opening_suite(connection, suite_id) is None:
            raise HTTPException(status_code=404, detail="Opening suite not found.")
        values, files = await _read_opening_form(request)
        name = values.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Suite name is required.")
        mode = values.get("mode", "replace")
        if mode not in {"replace", "append", "keep"}:
            raise HTTPException(status_code=422, detail="Choose a valid import mode.")
        existing = [
            (opening.name, opening.fen)
            for opening in list_suite_openings(connection, suite_id)
        ]
        incoming = _opening_values(
            values.get("positions", ""),
            files,
            allow_empty=mode == "keep",
        )
        if mode == "keep":
            openings = existing
        elif mode == "append":
            openings = _deduplicate_openings(existing + incoming)
        else:
            openings = incoming
        try:
            update_opening_suite(
                connection,
                suite_id,
                name=name,
                description=values.get("description", "").strip(),
            )
            replace_suite_openings(connection, suite_id, openings)
            connection.commit()
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=409, detail=web_app._friendly_error(exc)) from exc
        _publish_admin_change(web_app, request)
        return _json(
            {
                "id": suite_id,
                "position_count": len(openings),
                "message": "Opening suite updated.",
            }
        )

    @app.delete("/api/admin/openings/{suite_id}")
    def admin_delete_opening(
        suite_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_opening_suite(connection, suite_id) is None:
            raise HTTPException(status_code=404, detail="Opening suite not found.")
        if any(
            tournament.config.opening_suite_id == suite_id
            for tournament in list_tournaments(connection)
        ):
            raise HTTPException(
                status_code=409,
                detail="This opening suite is used by a tournament.",
            )
        delete_opening_suite(connection, suite_id)
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Opening suite deleted."})

    # Workers

    @app.get("/api/admin/workers")
    def admin_workers(
        request: Request,
        page: int = 1,
        per_page: int = 100,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        page = max(page, 1)
        per_page = min(max(per_page, 1), 200)
        return _json(
            web_app._workers_snapshot_payload(
                connection,
                worker_server_url=web_app._request_worker_server_url(request, connection),
                worker_limit=per_page,
                worker_offset=(page - 1) * per_page,
            )
        )

    @app.post("/api/admin/worker-pools")
    def admin_create_worker_pool(
        payload: WorkerPoolPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        enrollment = create_worker_pool(
            connection,
            label=payload.label.strip(),
            slot_count=payload.slot_count,
            assigned_threads=payload.assigned_threads,
            assigned_hash_mb=payload.assigned_hash_mb,
            ttl_seconds=payload.ttl_seconds,
        )
        connection.commit()
        _publish_admin_change(web_app, request)
        response = _json(
            _worker_pool_enrollment_payload(web_app, request, connection, enrollment),
            status_code=201,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/admin/worker-pools/{pool_id}/token")
    def admin_worker_pool_token(
        pool_id: int,
        payload: WorkerPoolTokenPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_worker_pool(connection, pool_id) is None:
            raise HTTPException(status_code=404, detail="Worker pool not found.")
        try:
            enrollment = mint_worker_pool_token(
                connection,
                pool_id=pool_id,
                ttl_seconds=payload.ttl_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        response = _json(
            _worker_pool_enrollment_payload(web_app, request, connection, enrollment)
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/admin/worker-pools/{pool_id}/revoke")
    def admin_worker_pool_revoke(
        pool_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_worker_pool(connection, pool_id) is None:
            raise HTTPException(status_code=404, detail="Worker pool not found.")
        revoke_worker_pool(connection, pool_id)
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Worker pool revoked and its workers removed."})

    @app.post("/api/admin/workers")
    def admin_create_worker(
        payload: WorkerPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        worker_id = create_worker(
            connection,
            label=payload.label.strip(),
            assigned_threads=payload.assigned_threads,
            assigned_hash_mb=payload.assigned_hash_mb,
        )
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json(
            {"id": worker_id, "message": "Worker created."},
            status_code=201,
        )

    @app.get("/api/admin/workers/{worker_id}")
    def admin_worker(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        row = web_app._worker_admin_row(connection, worker_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        return _json(
            web_app._worker_admin_api_payload(
                row,
                worker_server_url=web_app._request_worker_server_url(request, connection),
            )
        )

    @app.post("/api/admin/workers/{worker_id}/token")
    def admin_worker_token(
        worker_id: int,
        payload: WorkerTokenPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        try:
            minted = mint_worker_token_for_worker(
                connection,
                worker_id=worker_id,
                ttl_seconds=payload.ttl_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        worker = get_worker(connection, worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        command = (
            f"cope worker --server-url "
            f"{web_app._command_arg(web_app._request_worker_server_url(request, connection))} "
            f"--token {web_app._command_arg(minted.token)} "
            f"--threads {worker.assigned_threads} "
            f"--hash-mb {worker.assigned_hash_mb}"
        )
        response = _json(
            {
                "token": minted.token,
                "expires_at": minted.expires_at,
                "start_command": command,
                "message": "One-time worker token generated.",
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.put("/api/admin/workers/{worker_id}/label")
    def admin_worker_label(
        worker_id: int,
        payload: WorkerPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        update_worker_label(connection, worker_id, payload.label.strip())
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Worker renamed."})

    @app.post("/api/admin/workers/{worker_id}/revoke")
    def admin_worker_revoke(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        revoke_worker(connection, worker_id)
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Worker revoked and removed."})

    @app.delete("/api/admin/workers/{worker_id}")
    def admin_worker_delete(
        worker_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        if get_worker(connection, worker_id) is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        try:
            delete_worker(connection, worker_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        connection.commit()
        _publish_admin_change(web_app, request)
        return _json({"message": "Worker deleted."})

    # Chat moderation

    @app.get("/api/admin/chat")
    def admin_chat(connection: sqlite3.Connection = Depends(web_app._database)):
        return _json(
            {
                "messages": list_chat_messages(connection, limit=100),
                "tournament_names": web_app._tournament_names(connection),
                "settings": get_chat_settings(connection),
            }
        )

    @app.put("/api/admin/chat/settings")
    def admin_chat_settings(
        payload: ChatSettingsPayload,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        current = get_chat_settings(connection)
        settings = ChatSettingsRecord(
            enabled=payload.enabled,
            slowmode_seconds=current.slowmode_seconds,
            max_message_length=payload.max_message_length,
            allow_anonymous_names=payload.allow_anonymous_names,
            retention_days=current.retention_days,
        )
        update_chat_settings(connection, settings)
        connection.commit()
        web_app._publish_chat_settings_change(request, connection, settings)
        _publish_admin_change(web_app, request)
        return _json({"settings": settings, "message": "Chat settings updated."})

    @app.delete("/api/admin/chat/messages/{message_id}")
    def admin_chat_delete(
        message_id: int,
        request: Request,
        connection: sqlite3.Connection = Depends(web_app._database),
    ):
        deleted = delete_chat_message(connection, message_id)
        if deleted is None:
            raise HTTPException(status_code=404, detail="Message not found.")
        connection.commit()
        web_app._publish_chat_deletion(
            request,
            deleted.tournament_id,
            deleted.id,
        )
        _publish_admin_change(web_app, request)
        return _json({"message": "Message deleted."})


def _worker_pool_enrollment_payload(
    web_app,
    request: Request,
    connection: sqlite3.Connection,
    enrollment,
) -> dict[str, Any]:
    pool = get_worker_pool(connection, enrollment.pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Worker pool not found.")
    server_url = web_app._request_worker_server_url(request, connection)
    state_file = f".cope-worker/pool-{pool.id}.json"
    return {
        "pool_id": pool.id,
        "token": enrollment.token,
        "expires_at": enrollment.expires_at,
        "start_command": (
            f"cope worker-pool --server-url {web_app._command_arg(server_url)} "
            f"--state-file {web_app._command_arg(state_file)}"
        ),
        "message": "One-time machine pool enrollment token generated.",
    }


def _json(
    payload: Any,
    *,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(jsonable_encoder(payload), status_code=status_code)


def _settings_rows(rows: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"label": label, "value": value} for label, value in rows]


def _positive_form_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _require_tournament(connection: sqlite3.Connection, tournament_id: int):
    tournament = get_tournament(connection, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Tournament not found.")
    return tournament


def _category_settings(value: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "format": "round_robin",
        "format_options": {"games_per_pairing": 2},
        "time_control": {
            "category": "increment",
            "initial_ms": 60_000,
            "increment_ms": 1_000,
        },
        "concurrency": 1,
        "opening_suite_id": None,
        "adjudication": {
            "draw": None,
            "resign": None,
            "syzygy": None,
            "max_moves": None,
        },
        "rated": True,
        "lag_compensation_ms": 50,
        "engine_threads": 1,
        "engine_hash_mb": 16,
    }
    category_keys = {
        "time_control",
        "adjudication",
        "rated",
        "lag_compensation_ms",
        "engine_threads",
        "engine_hash_mb",
    }
    merged = {**defaults, **{key: item for key, item in value.items() if key in category_keys}}
    try:
        config = TournamentConfig(
            category_id=1,
            category_settings_linked=True,
            participants=[1, 2],
            **merged,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[error["msg"] for error in exc.errors()],
        ) from exc
    serialized = config.model_dump(mode="json")
    for key in (
        "category_id",
        "category_settings_linked",
        "participants",
        "uci_options",
    ):
        serialized.pop(key, None)
    return serialized


def _validated_tournament_config(
    connection: sqlite3.Connection,
    submitted: TournamentConfig,
) -> TournamentConfig:
    records = {engine.id: engine for engine in list_engine_records(connection)}
    missing = [engine_id for engine_id in submitted.participants if engine_id not in records]
    if missing:
        raise HTTPException(status_code=422, detail="One or more selected engines no longer exist.")
    unavailable = [
        engine_id for engine_id in submitted.participants
        if not records[engine_id].active or _engine_artifact_status(records[engine_id]) != "ready"
    ]
    if unavailable:
        raise HTTPException(status_code=422, detail="Every participant must be active with a healthy binary artifact on the main server.")

    if submitted.category_id is None:
        _validate_opening_suite_reference(connection, submitted.opening_suite_id)
        return submitted.model_copy(update={"rated": False})

    category = get_category(connection, submitted.category_id)
    if category is None or not category.active:
        raise HTTPException(status_code=422, detail="Choose an active rating category.")
    settings = _category_settings(category.default_config)
    _validate_opening_suite_reference(connection, submitted.opening_suite_id)
    settings.update(
        format=submitted.format,
        format_options=submitted.format_options,
        concurrency=submitted.concurrency,
        opening_suite_id=submitted.opening_suite_id,
    )
    try:
        return TournamentConfig(
            category_id=submitted.category_id,
            category_settings_linked=True,
            participants=submitted.participants,
            **settings,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[error["msg"] for error in exc.errors()],
        ) from exc


def _validate_opening_suite_reference(
    connection: sqlite3.Connection,
    suite_id: int | None,
) -> None:
    if suite_id is not None and get_opening_suite(connection, suite_id) is None:
        raise HTTPException(status_code=422, detail="Choose an existing opening suite.")


def _propagate_category_defaults(
    connection: sqlite3.Connection,
    category_id: int,
    defaults: dict[str, Any],
) -> None:
    for tournament in list_tournaments(connection):
        if (
            tournament.category_id != category_id
            or not tournament.config.category_settings_linked
            or tournament.status != "draft"
        ):
            continue
        config = TournamentConfig(
            category_id=category_id,
            category_settings_linked=True,
            participants=tournament.config.participants,
            **{
                **defaults,
                "format": tournament.config.format,
                "format_options": tournament.config.format_options,
                "concurrency": tournament.config.concurrency,
                "opening_suite_id": tournament.config.opening_suite_id,
            },
        )
        update_tournament(
            connection,
            tournament.id,
            name=tournament.name,
            config=config,
        )


def _tournament_form_payload(
    web_app,
    request: Request,
    connection: sqlite3.Connection,
    *,
    tournament=None,
) -> dict[str, Any]:
    categories = list_categories(connection, active_only=True)
    default_category = categories[0] if categories else None
    if tournament is not None:
        config = tournament.config.model_dump(mode="json")
        name = tournament.name
        participants = list(tournament.config.participants)
        category_id = tournament.category_id
        linked = tournament.config.category_settings_linked
    else:
        default_settings = _category_settings(
            default_category.default_config if default_category else {}
        )
        config = {
            "category_id": default_category.id if default_category else None,
            "category_settings_linked": default_category is not None,
            "participants": [],
            "engine_threads": 1,
            "engine_hash_mb": 16,
            "uci_options": {},
            **default_settings,
        }
        name = ""
        participants = []
        category_id = default_category.id if default_category else None
        linked = default_category is not None

    participant_ids = set(participants)
    engines = [
        engine
        for engine in list_engine_records(connection)
        if (engine.active and _engine_artifact_status(engine) == "ready") or engine.id in participant_ids
    ]
    category_defaults = {
        str(category.id): _category_settings(category.default_config)
        for category in categories
    }
    return {
        "name": name,
        "config": config,
        "participants": participants,
        "category_id": category_id,
        "linked": linked,
        "categories": categories,
        "category_defaults": category_defaults,
        "engine_options": engines,
        "opening_suites": list_opening_suites(connection),
        "editing": tournament is not None,
        # Compatibility aliases for feature components that still consume
        # the old flattened form context while migrating.
        "form_name": name,
        "form_participants": participants,
        "form_category_id": category_id,
        "form_linked": linked,
        "form_values": forms.settings_form_values(config),
    }


async def _read_opening_form(
    request: Request,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    form = await request.form()
    values: dict[str, str] = {}
    files: list[tuple[str, str]] = []
    for key, value in form.multi_items():
        if not isinstance(value, UploadFile):
            values[key] = str(value)
            continue
        if not value.filename:
            continue
        content = await value.read()
        files.append(
            (
                value.filename,
                content.decode("utf-8-sig", errors="replace"),
            )
        )
    return values, files


def _opening_values(
    positions: str,
    files: list[tuple[str, str]],
    *,
    allow_empty: bool = False,
) -> list[tuple[str, str]]:
    try:
        openings = parse_openings(positions)
        openings.extend(parse_opening_uploads(files))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    openings = _deduplicate_openings(openings)
    if not openings and not allow_empty:
        raise HTTPException(
            status_code=422,
            detail="Add at least one valid opening position.",
        )
    errors: list[str] = []
    validated: list[tuple[str, str]] = []
    for index, (name, fen) in enumerate(openings, start=1):
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            errors.append(f"Position {index}: {exc}")
            continue
        validated.append((name.strip(), board.fen()))
    if errors:
        raise HTTPException(status_code=422, detail=errors[:20])
    return validated


def _deduplicate_openings(
    openings: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, fen in openings:
        normalized = fen.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append((name.strip(), normalized))
    return result


def _publish_admin_change(web_app, request: Request) -> None:
    try:
        web_app._publish_admin_post_streams(request)
    except Exception:
        LOG.exception("admin change committed but live publication failed path=%s", request.url.path)
