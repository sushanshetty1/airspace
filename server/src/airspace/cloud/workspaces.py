"""Workspaces for the signed-in user, and Tower for each one at /api/w/{workspace_id}/...

The Tower routes are the same ones the demo serves at /api (api.app.tower_routes); only the engine differs. Here it
is the engine on the workspace's own graph, after checking the session owns the workspace. A workspace someone
else owns answers 404, the same as one that does not exist, so ids cannot be probed.
"""

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from airspace.api import preflight_routes
from airspace.api.app import ApiError, tower_routes
from airspace.cloud.accounts import LimitReached
from airspace.cloud.auth import require_user

_WORKSPACE_ID = re.compile(r"[0-9a-f]{12}")
NOT_FOUND = "No such workspace."


class NewWorkspace(BaseModel):
    name: str = ""


def owned_workspace(cloud, request: Request, workspace_id: str) -> dict:
    """The workspace the session owns, or ApiError 401, 403 or 404."""
    user_id = require_user(cloud, request)
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise ApiError(404, NOT_FOUND)
    workspace = cloud.accounts().workspace(user_id, workspace_id)
    if workspace is None:
        raise ApiError(404, NOT_FOUND)
    return workspace


def router(cloud) -> APIRouter:
    r = APIRouter()

    @r.post("/api/workspaces")
    def create(request: Request, body: NewWorkspace):
        user_id = require_user(cloud, request)
        try:
            made = cloud.accounts().create_workspace(user_id, body.name)
        except LimitReached as e:
            return JSONResponse(status_code=409, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=422, content={"error": str(e)})
        if made is None:
            raise ApiError(401, "Sign in first.")
        workspace, key = made
        return {"workspace": workspace, "key": key}

    @r.post("/api/workspaces/{workspace_id}/key")
    def rotate(request: Request, workspace_id: str):
        user_id = require_user(cloud, request)
        key = cloud.accounts().rotate_key(user_id, workspace_id) if _WORKSPACE_ID.fullmatch(workspace_id) else None
        if key is None:
            raise ApiError(404, NOT_FOUND)
        return {"key": key}

    @r.delete("/api/workspaces/{workspace_id}")
    def delete(request: Request, workspace_id: str):
        user_id = require_user(cloud, request)
        if not _WORKSPACE_ID.fullmatch(workspace_id) or not cloud.accounts().delete_workspace(user_id, workspace_id):
            raise ApiError(404, NOT_FOUND)
        cloud.forget(workspace_id)
        return {"ok": True}

    return r


def tower_router(cloud, **timing) -> APIRouter:
    """Tower for one workspace, mounted at /api/w/{workspace_id}."""

    def engine(request: Request):
        workspace_id = request.path_params["workspace_id"]
        owned_workspace(cloud, request, workspace_id)
        return cloud.engine(workspace_id)

    r = tower_routes(engine, **timing)
    preflight_routes.workspace_routes(r, cloud)

    @r.get("/mode")
    def mode(request: Request, workspace_id: str) -> dict:
        # A workspace has no recording to play: Tower always shows it live.
        owned_workspace(cloud, request, workspace_id)
        return {"mode": "live"}

    return r
