"""Hermes State Service — remote user state for stateless Agent pods."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, desc, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from state_service.database import close_db, get_session, health_check, init_db, readiness_check
from state_service.models import AuditEvent, CacheMetadata, MemoryRecord, Message, Session, UserConfig, now_utc
from state_service.schemas import (
    CacheMetadataRequest,
    CacheMetadataResponse,
    ConfigUpsertRequest,
    EffectiveConfigResponse,
    EndSessionRequest,
    MemoryItem,
    MemoryListResponse,
    MemoryUpsertRequest,
    MessageCreateRequest,
    MessageSearchResponse,
    MessagesResponse,
    RequestContext,
    SessionCreateRequest,
    SessionPatchRequest,
    SessionResponse,
    SessionsListResponse,
    UsageUpdateRequest,
)
from state_service.security import get_request_context


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Hermes State Service",
    description="Remote user state for stateless Hermes Agent runtimes.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "X-Tenant-ID", "X-User-ID", "X-Session-ID", "X-Request-ID"],
)


async def db_dep():
    async with get_session() as session:
        yield session


def _session_to_response(session: Session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        source=session.source,
        model=session.model,
        model_config_data=session.model_config,
        parent_session_id=session.parent_session_id,
        title=session.title,
        started_at=session.started_at,
        ended_at=session.ended_at,
        end_reason=session.end_reason,
        message_count=session.message_count,
        tool_call_count=session.tool_call_count,
    )


async def _audit(
    db: AsyncSession,
    ctx: RequestContext,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    *,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Record a sanitized audit event for state access."""
    db.add(
        AuditEvent(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=session_id or ctx.session_id,
            request_id=ctx.request_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata or {},
        )
    )


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"service": "state-service", "version": "0.1.0", "db_ok": await health_check()}


@app.get("/ready", tags=["Health"])
async def ready() -> dict:
    checks = await readiness_check()
    if not checks["db_ok"] or not checks["migration_ok"]:
        raise HTTPException(status_code=503, detail=checks)
    return {"service": "state-service", "version": "0.1.0", **checks}


@app.get("/state/config/effective", response_model=EffectiveConfigResponse, tags=["Config"])
async def get_effective_config(
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> EffectiveConfigResponse:
    """Return merged platform/tenant/user config for the current user."""
    stmt = select(UserConfig).where(
        and_(
            UserConfig.tenant_id == ctx.tenant_id,
            UserConfig.user_id.in_(["*", ctx.user_id]),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    merged: dict = {}
    scope_rank = {"platform": 0, "tenant": 1, "user": 2}
    for row in sorted(rows, key=lambda r: (scope_rank.get(r.scope, 99), r.user_id != "*")):
        target = merged
        parts = row.key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = row.value
    await _audit(db, ctx, "read", "config", "effective")
    return EffectiveConfigResponse(tenant_id=ctx.tenant_id, user_id=ctx.user_id, config=merged)


@app.put("/state/config", tags=["Config"])
async def upsert_config(
    req: ConfigUpsertRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> dict:
    stmt = select(UserConfig).where(
        and_(
            UserConfig.tenant_id == ctx.tenant_id,
            UserConfig.user_id == ctx.user_id,
            UserConfig.scope == req.scope,
            UserConfig.key == req.key,
        )
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = UserConfig(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            scope=req.scope,
            key=req.key,
            value=req.value,
        )
        db.add(row)
    else:
        row.value = req.value
        row.updated_at = now_utc()
    await db.flush()
    await _audit(db, ctx, "write", "config", req.key, metadata={"scope": req.scope})
    return {"ok": True}


@app.post("/state/sessions", response_model=SessionResponse, tags=["Sessions"])
async def create_session(
    req: SessionCreateRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> SessionResponse:
    user_id = req.user_id or ctx.user_id
    if user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Cannot create a session for another user")
    session = await db.get(Session, req.session_id)
    if session is None:
        session = Session(
            id=req.session_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            source=req.source,
            model=req.model,
            model_config=req.model_config_data,
            parent_session_id=req.parent_session_id,
        )
        db.add(session)
        await db.flush()
    elif session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="Session belongs to another user")
    await _audit(db, ctx, "write", "session", session.id, session_id=session.id, metadata={"source": session.source})
    return _session_to_response(session)


@app.get("/state/sessions", response_model=SessionsListResponse, tags=["Sessions"])
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    exclude_sources: str | None = Query(default=None),
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> SessionsListResponse:
    if not isinstance(limit, int):
        limit = 50
    if not isinstance(offset, int):
        offset = 0
    if not isinstance(source, str):
        source = None
    if not isinstance(exclude_sources, str):
        exclude_sources = None
    excluded = {s.strip() for s in (exclude_sources or "").split(",") if s.strip()}
    stmt = select(Session).where(
        and_(Session.tenant_id == ctx.tenant_id, Session.user_id == ctx.user_id)
    )
    if source:
        stmt = stmt.where(Session.source == source)
    if excluded:
        stmt = stmt.where(not_(Session.source.in_(excluded)))
    stmt = stmt.order_by(desc(Session.started_at)).offset(offset).limit(limit)
    sessions = (await db.execute(stmt)).scalars().all()

    results = []
    for session in sessions:
        first_msg_stmt = (
            select(Message.content, Message.timestamp)
            .where(
                and_(
                    Message.tenant_id == ctx.tenant_id,
                    Message.user_id == ctx.user_id,
                    Message.session_id == session.id,
                    Message.role == "user",
                )
            )
            .order_by(Message.timestamp, Message.id)
            .limit(1)
        )
        first_msg = (await db.execute(first_msg_stmt)).first()
        last_ts_stmt = select(func.max(Message.timestamp)).where(
            and_(
                Message.tenant_id == ctx.tenant_id,
                Message.user_id == ctx.user_id,
                Message.session_id == session.id,
            )
        )
        last_ts = (await db.execute(last_ts_stmt)).scalar_one_or_none()
        preview = ""
        if first_msg and first_msg[0]:
            raw = str(first_msg[0]).replace("\n", " ")
            preview = raw[:60] + ("..." if len(raw) > 60 else "")
        results.append({
            "id": session.id,
            "title": session.title,
            "source": session.source,
            "started_at": session.started_at.timestamp(),
            "last_active": (last_ts or session.started_at).timestamp(),
            "message_count": session.message_count,
            "tool_call_count": session.tool_call_count,
            "parent_session_id": session.parent_session_id,
            "preview": preview,
        })
    await _audit(db, ctx, "read", "session_list", metadata={"count": len(results), "source": source})
    return SessionsListResponse(sessions=results)


@app.get("/state/sessions/{session_id}", response_model=SessionResponse, tags=["Sessions"])
async def get_session_by_id(
    session_id: str,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> SessionResponse:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    await _audit(db, ctx, "read", "session", session_id, session_id=session_id)
    return _session_to_response(session)


@app.patch("/state/sessions/{session_id}", response_model=SessionResponse, tags=["Sessions"])
async def patch_session(
    session_id: str,
    req: SessionPatchRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> SessionResponse:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if req.title is not None:
        session.title = req.title[:200]
    await db.flush()
    await _audit(db, ctx, "write", "session", session_id, session_id=session_id, metadata={"field": "title"})
    return _session_to_response(session)


@app.post("/state/sessions/{session_id}/messages", tags=["Sessions"])
async def append_message(
    session_id: str,
    req: MessageCreateRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> dict:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    msg = Message(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=session_id,
        role=req.role,
        content=req.content,
        tool_name=req.tool_name,
        tool_calls=req.tool_calls,
        tool_call_id=req.tool_call_id,
        token_count=req.token_count,
        finish_reason=req.finish_reason,
        reasoning=req.reasoning,
        reasoning_details=req.reasoning_details,
        codex_reasoning_items=req.codex_reasoning_items,
    )
    session.message_count += 1
    if req.tool_calls:
        session.tool_call_count += len(req.tool_calls) if isinstance(req.tool_calls, list) else 1
    db.add(msg)
    await db.flush()
    await _audit(
        db,
        ctx,
        "write",
        "message",
        str(msg.id),
        session_id=session_id,
        metadata={"role": req.role, "has_content": req.content is not None, "tool_name": req.tool_name},
    )
    return {"id": msg.id}


@app.get("/state/sessions/{session_id}/messages", response_model=MessagesResponse, tags=["Sessions"])
async def get_messages(
    session_id: str,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> MessagesResponse:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    stmt = select(Message).where(
        and_(
            Message.tenant_id == ctx.tenant_id,
            Message.user_id == ctx.user_id,
            Message.session_id == session_id,
        )
    ).order_by(Message.timestamp, Message.id)
    rows = (await db.execute(stmt)).scalars().all()
    messages = []
    for row in rows:
        msg = {"role": row.role, "content": row.content}
        if row.tool_call_id:
            msg["tool_call_id"] = row.tool_call_id
        if row.tool_name:
            msg["tool_name"] = row.tool_name
        if row.tool_calls:
            msg["tool_calls"] = row.tool_calls
        if row.role == "assistant":
            if row.reasoning:
                msg["reasoning"] = row.reasoning
            if row.reasoning_details:
                msg["reasoning_details"] = row.reasoning_details
            if row.codex_reasoning_items:
                msg["codex_reasoning_items"] = row.codex_reasoning_items
        messages.append(msg)
    await _audit(db, ctx, "read", "messages", session_id, session_id=session_id, metadata={"count": len(messages)})
    return MessagesResponse(messages=messages)


@app.get("/state/messages/search", response_model=MessageSearchResponse, tags=["Sessions"])
async def search_messages(
    query: str = Query(..., min_length=1),
    role_filter: str | None = Query(default=None),
    exclude_sources: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> MessageSearchResponse:
    if not isinstance(role_filter, str):
        role_filter = None
    if not isinstance(exclude_sources, str):
        exclude_sources = None
    if not isinstance(limit, int):
        limit = 20
    if not isinstance(offset, int):
        offset = 0
    roles = {r.strip() for r in (role_filter or "").split(",") if r.strip()}
    excluded = {s.strip() for s in (exclude_sources or "").split(",") if s.strip()}
    pattern = f"%{query}%"
    stmt = (
        select(Message, Session)
        .join(Session, Message.session_id == Session.id)
        .where(
            and_(
                Message.tenant_id == ctx.tenant_id,
                Message.user_id == ctx.user_id,
                Session.tenant_id == ctx.tenant_id,
                Session.user_id == ctx.user_id,
                Message.content.ilike(pattern),
            )
        )
        .order_by(desc(Message.timestamp))
        .offset(offset)
        .limit(limit)
    )
    if roles:
        stmt = stmt.where(Message.role.in_(roles))
    if excluded:
        stmt = stmt.where(not_(Session.source.in_(excluded)))

    rows = (await db.execute(stmt)).all()
    results = [
        {
            "session_id": msg.session_id,
            "message_id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "snippet": (msg.content or "")[:500],
            "timestamp": msg.timestamp.timestamp(),
            "source": session.source,
            "started_at": session.started_at.timestamp(),
            "title": session.title,
            "parent_session_id": session.parent_session_id,
        }
        for msg, session in rows
    ]
    await _audit(db, ctx, "search", "messages", metadata={"count": len(results), "roles": sorted(roles)})
    return MessageSearchResponse(results=results)


@app.post("/state/sessions/{session_id}/usage", tags=["Sessions"])
async def update_usage(
    session_id: str,
    req: UsageUpdateRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> dict:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if req.absolute:
        session.input_tokens = req.input_tokens
        session.output_tokens = req.output_tokens
        session.cache_read_tokens = req.cache_read_tokens
        session.cache_write_tokens = req.cache_write_tokens
        session.reasoning_tokens = req.reasoning_tokens
    else:
        session.input_tokens += req.input_tokens
        session.output_tokens += req.output_tokens
        session.cache_read_tokens += req.cache_read_tokens
        session.cache_write_tokens += req.cache_write_tokens
        session.reasoning_tokens += req.reasoning_tokens
    if req.model and not session.model:
        session.model = req.model
    await db.flush()
    await _audit(
        db,
        ctx,
        "write",
        "session_usage",
        session_id,
        session_id=session_id,
        metadata={"absolute": req.absolute, "model": req.model},
    )
    return {"ok": True}


@app.post("/state/sessions/{session_id}/end", tags=["Sessions"])
async def end_session(
    session_id: str,
    req: EndSessionRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> dict:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    session.ended_at = now_utc()
    session.end_reason = req.end_reason
    await db.flush()
    await _audit(db, ctx, "write", "session", session_id, session_id=session_id, metadata={"end_reason": req.end_reason})
    return {"ok": True}


@app.post("/state/sessions/{session_id}/reopen", tags=["Sessions"])
async def reopen_session(
    session_id: str,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> dict:
    session = await db.get(Session, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    session.ended_at = None
    session.end_reason = None
    await db.flush()
    await _audit(db, ctx, "write", "session", session_id, session_id=session_id, metadata={"reopened": True})
    return {"ok": True}


@app.get("/state/memory", response_model=MemoryListResponse, tags=["Memory"])
async def list_memory(
    namespace: str = Query(default="memory"),
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> MemoryListResponse:
    if not isinstance(namespace, str):
        namespace = "memory"
    stmt = select(MemoryRecord).where(
        and_(
            MemoryRecord.tenant_id == ctx.tenant_id,
            MemoryRecord.user_id == ctx.user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.is_deleted == False,
        )
    ).order_by(MemoryRecord.updated_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    await _audit(db, ctx, "read", "memory", namespace, metadata={"count": len(rows)})
    return MemoryListResponse(items=[
        MemoryItem(
            namespace=row.namespace,
            key=row.key,
            value=row.value,
            metadata=row.metadata_json or {},
            updated_at=row.updated_at,
        )
        for row in rows
    ])


@app.put("/state/memory/{namespace}/{key}", response_model=MemoryItem, tags=["Memory"])
async def upsert_memory(
    namespace: str,
    key: str,
    req: MemoryUpsertRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> MemoryItem:
    stmt = select(MemoryRecord).where(
        and_(
            MemoryRecord.tenant_id == ctx.tenant_id,
            MemoryRecord.user_id == ctx.user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.key == key,
        )
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = MemoryRecord(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            namespace=namespace,
            key=key,
            value=req.value,
            metadata_json=req.metadata,
        )
        db.add(row)
    else:
        row.value = req.value
        row.metadata_json = req.metadata
        row.is_deleted = False
        row.updated_at = now_utc()
    await db.flush()
    await _audit(db, ctx, "write", "memory", f"{namespace}/{key}", metadata={"metadata_keys": sorted(req.metadata)})
    return MemoryItem(
        namespace=row.namespace,
        key=row.key,
        value=row.value,
        metadata=row.metadata_json or {},
        updated_at=row.updated_at,
    )


@app.delete("/state/memory/{namespace}/{key}", tags=["Memory"])
async def delete_memory(
    namespace: str,
    key: str,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> dict:
    stmt = select(MemoryRecord).where(
        and_(
            MemoryRecord.tenant_id == ctx.tenant_id,
            MemoryRecord.user_id == ctx.user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.key == key,
        )
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Memory record not found")
    row.is_deleted = True
    row.updated_at = now_utc()
    await db.flush()
    await _audit(db, ctx, "delete", "memory", f"{namespace}/{key}")
    return {"ok": True}


@app.put("/state/cache/{cache_key:path}", response_model=CacheMetadataResponse, tags=["Cache"])
async def put_cache_metadata(
    cache_key: str,
    req: CacheMetadataRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> CacheMetadataResponse:
    stmt = select(CacheMetadata).where(
        and_(
            CacheMetadata.tenant_id == ctx.tenant_id,
            CacheMetadata.user_id == ctx.user_id,
            CacheMetadata.cache_key == cache_key,
        )
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = CacheMetadata(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            cache_key=cache_key,
            kind=req.kind,
            object_uri=req.object_uri,
            content_sha256=req.content_sha256,
            size_bytes=req.size_bytes,
            metadata_json=req.metadata,
        )
        db.add(row)
    else:
        row.kind = req.kind
        row.session_id = ctx.session_id
        row.object_uri = req.object_uri
        row.content_sha256 = req.content_sha256
        row.size_bytes = req.size_bytes
        row.metadata_json = req.metadata
        row.updated_at = now_utc()
    await db.flush()
    await _audit(
        db,
        ctx,
        "write",
        "cache_metadata",
        cache_key,
        metadata={"kind": req.kind, "size_bytes": req.size_bytes},
    )
    return CacheMetadataResponse(
        cache_key=row.cache_key,
        kind=row.kind,
        object_uri=row.object_uri,
        content_sha256=row.content_sha256,
        size_bytes=row.size_bytes,
        metadata=row.metadata_json or {},
    )


@app.get("/state/cache/{cache_key:path}", response_model=CacheMetadataResponse, tags=["Cache"])
async def get_cache_metadata(
    cache_key: str,
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(db_dep),
) -> CacheMetadataResponse:
    stmt = select(CacheMetadata).where(
        and_(
            CacheMetadata.tenant_id == ctx.tenant_id,
            CacheMetadata.user_id == ctx.user_id,
            CacheMetadata.cache_key == cache_key,
        )
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Cache metadata not found")
    await _audit(db, ctx, "read", "cache_metadata", cache_key, metadata={"kind": row.kind})
    return CacheMetadataResponse(
        cache_key=row.cache_key,
        kind=row.kind,
        object_uri=row.object_uri,
        content_sha256=row.content_sha256,
        size_bytes=row.size_bytes,
        metadata=row.metadata_json or {},
    )
