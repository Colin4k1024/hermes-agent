package controller

import (
	"context"
	"encoding/json"
	"time"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"

	"github.com/hermes-agent/state-service-go/internal/database"
	"github.com/hermes-agent/state-service-go/internal/storage"
)

// =============================================================================
// Request/Response types
// =============================================================================

type SessionCreateReq struct {
	SessionID        string                 `json:"session_id" v:"required"`
	UserID           string                 `json:"user_id"`
	Source           string                 `json:"source" v:"required"`
	Model            string                 `json:"model"`
	ModelConfigData  map[string]interface{} `json:"model_config_data"`
	ParentSessionID  string                 `json:"parent_session_id"`
	SystemPromptRef  string                 `json:"system_prompt_ref"`
}

// Session represents the state_sessions table for ORM operations
type Session struct {
	ID                string `json:"id"`
	TenantID          string `json:"tenant_id"`
	UserID            string `json:"user_id"`
	Source            string `json:"source"`
	Model             string `json:"model"`
	ModelConfig       string `json:"model_config"`
	SystemPromptRef   string `json:"system_prompt_ref"`
	ParentSessionID   string `json:"parent_session_id"`
	Title             string `json:"title"`
	StartedAt         string `json:"started_at"`
	EndedAt           string `json:"ended_at"`
	EndReason         string `json:"end_reason"`
	MessageCount      int    `json:"message_count"`
	ToolCallCount     int    `json:"tool_call_count"`
	InputTokens       int64  `json:"input_tokens"`
	OutputTokens      int64  `json:"output_tokens"`
	CacheReadTokens   int64  `json:"cache_read_tokens"`
	CacheWriteTokens  int64  `json:"cache_write_tokens"`
	ReasoningTokens   int64  `json:"reasoning_tokens"`
}

type MessageCreateReq struct {
	Role                string      `json:"role" v:"required"`
	Content             string      `json:"content"`
	ToolName            string      `json:"tool_name"`
	ToolCalls           interface{} `json:"tool_calls"`
	ToolCallID          string      `json:"tool_call_id"`
	TokenCount          int         `json:"token_count"`
	FinishReason        string      `json:"finish_reason"`
	Reasoning           string      `json:"reasoning"`
	ReasoningDetails    interface{} `json:"reasoning_details"`
	CodexReasoningItems interface{} `json:"codex_reasoning_items"`
}

type MemoryUpsertReq struct {
	Value     string                 `json:"value" v:"required"`
	Metadata  map[string]interface{} `json:"metadata"`
}

type ConfigUpsertReq struct {
	Scope string                 `json:"scope" v:"required"`
	Key   string                 `json:"key" v:"required"`
	Value map[string]interface{} `json:"value" v:"required"`
}

type UsageUpdateReq struct {
	InputTokens       int64 `json:"input_tokens"`
	OutputTokens      int64 `json:"output_tokens"`
	CacheReadTokens  int64 `json:"cache_read_tokens"`
	CacheWriteTokens int64 `json:"cache_write_tokens"`
	ReasoningTokens  int64 `json:"reasoning_tokens"`
}

// =============================================================================
// Session endpoints
// =============================================================================

// CreateSession creates a new session
func CreateSession(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.Header.Get("X-Tenant-ID")
	if tenantID == "" {
		tenantID = "default"
	}
	userID := r.Header.Get("X-User-ID")

	var req SessionCreateReq
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	// Check if session already exists using raw SQL
	existing, err := database.DB().Model("state_sessions").Raw(
		`SELECT id, user_id FROM state_sessions WHERE id = $1 AND tenant_id = $2`,
		req.SessionID, tenantID).One()

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "database error"})
		return
	}

	if !existing.IsEmpty() {
		// Session exists, check ownership
		if existing["user_id"].String() != userID {
			r.Response.WriteStatus(403)
			r.Response.WriteJson(g.Map{"detail": "Session belongs to another user"})
			return
		}
		r.Response.WriteJson(g.Map{"id": req.SessionID})
		return
	}

	// Create new session using raw SQL with PostgreSQL placeholders
	now := time.Now()
	modelConfigJSON := "{}"
	if req.ModelConfigData != nil {
		if jsonBytes, jsonErr := json.Marshal(req.ModelConfigData); jsonErr == nil {
			modelConfigJSON = string(jsonBytes)
		}
	}

	var insertErr error
	_, insertErr = database.DB().Exec(ctx,
		`INSERT INTO state_sessions (id, tenant_id, user_id, source, model, model_config, parent_session_id, started_at, message_count, tool_call_count)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
		req.SessionID, tenantID, userID, req.Source, req.Model, modelConfigJSON, req.ParentSessionID, now, 0, 0)
	g.Log().Infof(ctx, "CreateSession raw SQL result, err: %v", insertErr)

	if insertErr != nil {
		g.Log().Errorf(ctx, "CreateSession insert error: %v", insertErr)
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to create session"})
		return
	}

	r.Response.WriteJson(g.Map{"id": req.SessionID})
}

// GetSession retrieves a session by ID
func GetSession(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	sessionID := r.Get("sessionId").String()

	result, err := database.DB().Model("state_sessions").Raw(
		`SELECT id, tenant_id, user_id, source, model, model_config, system_prompt_ref,
		        parent_session_id, title, started_at, ended_at, end_reason,
		        message_count, tool_call_count, input_tokens, output_tokens,
		        cache_read_tokens, cache_write_tokens, reasoning_tokens
		 FROM state_sessions
		 WHERE id = $1 AND tenant_id = $2 AND user_id = $3`,
		sessionID, tenantID, userID).One()

	if err != nil || result.IsEmpty() {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Session not found"})
		return
	}

	r.Response.WriteJson(result)
}

// GetSessionMetadata retrieves session metadata
func GetSessionMetadata(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	sessionID := r.Get("sessionId").String()

	session, err := database.DB().Model("state_sessions").Raw(
		`SELECT id, tenant_id, user_id, source, model, parent_session_id, title,
		        started_at, ended_at, end_reason, message_count, tool_call_count
		 FROM state_sessions
		 WHERE id = $1 AND tenant_id = $2 AND user_id = $3`,
		sessionID, tenantID, userID).One()

	if err != nil || session.IsEmpty() {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Session not found"})
		return
	}

	r.Response.WriteJson(session)
}

// ListSessions lists all sessions for the current user
func ListSessions(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()

	limit := r.Get("limit", 50).Int()
	offset := r.Get("offset", 0).Int()

	result, err := database.DB().Model("state_sessions").Raw(
		`SELECT id, tenant_id, user_id, source, model, parent_session_id, title,
		        started_at, ended_at, end_reason, message_count, tool_call_count,
		        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens
		 FROM state_sessions
		 WHERE tenant_id = $1 AND user_id = $2
		 ORDER BY started_at DESC
		 LIMIT $3 OFFSET $4`,
		tenantID, userID, limit, offset).All()

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "database error"})
		return
	}

	r.Response.WriteJson(g.Map{"sessions": result})
}

// PatchSession updates session fields
func PatchSession(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	sessionID := r.Get("sessionId").String()

	var req map[string]interface{}
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	// Only allow updating certain fields
	title := ""
	if t, ok := req["title"].(string); ok {
		title = t
	}

	if title == "" {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": "no valid fields to update"})
		return
	}

	result, err := database.DB().Exec(ctx,
		`UPDATE state_sessions SET title = $1 WHERE id = $2 AND tenant_id = $3 AND user_id = $4`,
		title, sessionID, tenantID, userID)

	if err != nil {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Session not found"})
		return
	}
	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Session not found"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}

// EndSession marks a session as ended
func EndSession(r *ghttp.Request) {
	ctx := context.Background()
	sessionID := r.Get("sessionId").String()

	var req map[string]interface{}
	if err := r.Parse(&req); err != nil {
		req = make(map[string]interface{})
	}

	endReason := ""
	if er, ok := req["end_reason"].(string); ok {
		endReason = er
	}

	_, err := database.DB().Exec(ctx,
		`UPDATE state_sessions SET ended_at = $1, end_reason = $2 WHERE id = $3`,
		time.Now(), endReason, sessionID)

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to end session"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}

// ReopenSession reopens an ended session
func ReopenSession(r *ghttp.Request) {
	ctx := context.Background()
	sessionID := r.Get("sessionId").String()

	_, err := database.DB().Exec(ctx,
		`UPDATE state_sessions SET ended_at = NULL, end_reason = NULL WHERE id = $1`,
		sessionID)

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to reopen session"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}

// =============================================================================
// Message endpoints
// =============================================================================

// AppendMessage appends a message to a session
func AppendMessage(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	sessionID := r.Get("sessionId").String()

	// Verify session ownership using raw SQL
	sessionResult, err := database.DB().Model("state_sessions").Raw(
		`SELECT id FROM state_sessions WHERE id = $1 AND tenant_id = $2 AND user_id = $3`,
		sessionID, tenantID, userID).One()

	if err != nil || sessionResult.IsEmpty() {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Session not found"})
		return
	}

	var req MessageCreateReq
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	// Dual-write: store content in OSS first
	ossClient := storage.GetOSSClient()
	objectURI := ""
	contentSize := 0

	if req.Content != "" && ossClient.IsAvailable() {
		uri, err := ossClient.PutMessageContent(tenantID, sessionID, 0, req.Content)
		if err != nil {
			// Fall back to PG-only in non-strict mode
		} else {
			objectURI = uri
			contentSize = len(req.Content)
		}
	}

	// Insert message using raw SQL
	now := time.Now()
	toolCallsJSON := "{}"
	if req.ToolCalls != nil {
		if jsonBytes, err := json.Marshal(req.ToolCalls); err == nil {
			toolCallsJSON = string(jsonBytes)
		}
	}

	reasoningDetailsJSON := "{}"
	if req.ReasoningDetails != nil {
		if jsonBytes, err := json.Marshal(req.ReasoningDetails); err == nil {
			reasoningDetailsJSON = string(jsonBytes)
		}
	}

	codexItemsJSON := "[]"
	if req.CodexReasoningItems != nil {
		if jsonBytes, err := json.Marshal(req.CodexReasoningItems); err == nil {
			codexItemsJSON = string(jsonBytes)
		}
	}

	execResult, err := database.DB().Exec(ctx,
		`INSERT INTO state_messages (tenant_id, user_id, session_id, role, content, tool_name, tool_calls, tool_call_id, token_count, finish_reason, reasoning, reasoning_details, codex_reasoning_items, timestamp, object_uri, content_size)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`,
		tenantID, userID, sessionID, req.Role, req.Content, req.ToolName, toolCallsJSON, req.ToolCallID, req.TokenCount, req.FinishReason, req.Reasoning, reasoningDetailsJSON, codexItemsJSON, now, objectURI, contentSize)

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to insert message"})
		return
	}

	// Get the inserted ID
	messageID, _ := execResult.LastInsertId()

	// Update OSS with actual message ID
	if objectURI != "" && messageID > 0 {
		storage.GetOSSClient().PutMessageContent(tenantID, sessionID, messageID, req.Content)
	}

	// Update session message count using raw SQL
	database.DB().Exec(ctx,
		`UPDATE state_sessions SET message_count = message_count + 1 WHERE id = $1`,
		sessionID)

	r.Response.WriteJson(g.Map{"id": messageID})
}

// GetMessages retrieves all messages for a session
func GetMessages(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	sessionID := r.Get("sessionId").String()

	// Verify session ownership using raw SQL
	sessionResult, err := database.DB().Model("state_sessions").Raw(
		`SELECT id FROM state_sessions WHERE id = $1 AND tenant_id = $2 AND user_id = $3`,
		sessionID, tenantID, userID).One()

	if err != nil || sessionResult.IsEmpty() {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Session not found"})
		return
	}

	// Get messages using raw SQL
	messages, err := database.DB().Model("state_messages").Raw(
		`SELECT id, tenant_id, user_id, session_id, role, content, tool_name, tool_calls,
		        tool_call_id, token_count, finish_reason, reasoning, reasoning_details,
		        codex_reasoning_items, timestamp, object_uri, content_size
		 FROM state_messages
		 WHERE tenant_id = $1 AND user_id = $2 AND session_id = $3
		 ORDER BY timestamp, id`,
		tenantID, userID, sessionID).All()

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "database error"})
		return
	}

	r.Response.WriteJson(g.Map{"messages": messages})
}

// SearchMessages searches messages by content
func SearchMessages(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	query := r.Get("query").String()
	limit := r.Get("limit", 20).Int()
	offset := r.Get("offset", 0).Int()

	messages, err := database.DB().Model("state_messages").Raw(
		`SELECT id, tenant_id, user_id, session_id, role, content, tool_name, tool_calls,
		        tool_call_id, token_count, finish_reason, reasoning, reasoning_details,
		        codex_reasoning_items, timestamp, object_uri, content_size
		 FROM state_messages
		 WHERE tenant_id = $1 AND user_id = $2 AND content LIKE '%' || $3 || '%'
		 ORDER BY timestamp DESC
		 LIMIT $4 OFFSET $5`,
		tenantID, userID, query, limit, offset).All()

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "database error"})
		return
	}

	r.Response.WriteJson(g.Map{"results": messages})
}

// =============================================================================
// Memory endpoints
// =============================================================================

// ListMemory lists all memory records for the current user
func ListMemory(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	namespace := r.Get("namespace", "memory").String()

	records, err := database.DB().Model("state_memory").Raw(
		`SELECT id, tenant_id, user_id, namespace, key, value, metadata_json, is_deleted,
		        created_at, updated_at, object_uri
		 FROM state_memory
		 WHERE tenant_id = $1 AND user_id = $2 AND namespace = $3 AND is_deleted = false
		 ORDER BY updated_at DESC`,
		tenantID, userID, namespace).All()

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "database error"})
		return
	}

	r.Response.WriteJson(g.Map{"items": records})
}

// UpsertMemory creates or updates a memory record
func UpsertMemory(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	namespace := r.Get("namespace").String()
	key := r.Get("key").String()

	var req MemoryUpsertReq
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	if req.Metadata == nil {
		req.Metadata = make(map[string]interface{})
	}

	// Dual-write: store value in OSS first
	ossClient := storage.GetOSSClient()
	objectURI := ""

	if req.Value != "" && ossClient.IsAvailable() {
		version := time.Now().Unix()
		uri, err := ossClient.PutMemoryContent(tenantID, namespace, key, req.Value, version)
		if err == nil {
			objectURI = uri
		}
	}

	now := time.Now()
	metadataJSON := "{}"
	if jsonBytes, err := json.Marshal(req.Metadata); err == nil {
		metadataJSON = string(jsonBytes)
	}

	// Check if record exists using raw SQL
	existing, err := database.DB().Model("state_memory").Raw(
		`SELECT id FROM state_memory WHERE tenant_id = $1 AND user_id = $2 AND namespace = $3 AND key = $4`,
		tenantID, userID, namespace, key).One()

	if err != nil || existing.IsEmpty() {
		// Create new record using raw SQL
		_, err = database.DB().Exec(ctx,
			`INSERT INTO state_memory (tenant_id, user_id, namespace, key, value, metadata_json, object_uri, is_deleted, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, false, $8, $8)`,
			tenantID, userID, namespace, key, req.Value, metadataJSON, objectURI, now)
	} else {
		// Update existing record using raw SQL
		_, err = database.DB().Exec(ctx,
			`UPDATE state_memory SET value = $1, metadata_json = $2, object_uri = $3, is_deleted = false, updated_at = $4
			 WHERE tenant_id = $5 AND user_id = $6 AND namespace = $7 AND key = $8`,
			req.Value, metadataJSON, objectURI, now, tenantID, userID, namespace, key)
	}

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to upsert memory"})
		return
	}

	r.Response.WriteJson(g.Map{
		"namespace": namespace,
		"key":       key,
		"value":     req.Value,
		"metadata":  req.Metadata,
	})
}

// DeleteMemory soft-deletes a memory record
func DeleteMemory(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	namespace := r.Get("namespace").String()
	key := r.Get("key").String()

	_, err := database.DB().Exec(ctx,
		`UPDATE state_memory SET is_deleted = true WHERE tenant_id = $1 AND user_id = $2 AND namespace = $3 AND key = $4`,
		tenantID, userID, namespace, key)

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to delete memory"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}

// =============================================================================
// Config endpoints
// =============================================================================

// GetEffectiveConfig returns merged platform/tenant/user config
func GetEffectiveConfig(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()

	configs, err := database.DB().Model("state_user_configs").Raw(
		`SELECT scope, key, value FROM state_user_configs
		 WHERE tenant_id = $1 AND (user_id = $2 OR user_id = '*')
		 ORDER BY CASE scope WHEN 'platform' THEN 0 WHEN 'tenant' THEN 1 WHEN 'user' THEN 2 END`,
		tenantID, userID).All()

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "database error"})
		return
	}

	// Merge configs
	merged := make(map[string]interface{})

	for _, cfg := range configs {
		rec := cfg.Map()
		keyVal := rec["key"]
		if keyStr, ok := keyVal.(string); ok && keyStr != "" {
			if _, exists := merged[keyStr]; !exists {
				merged[keyStr] = rec["value"]
			}
		}
	}

	r.Response.WriteJson(g.Map{
		"tenant_id": tenantID,
		"user_id":  userID,
		"config":   merged,
	})
}

// UpsertConfig creates or updates a user config
func UpsertConfig(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()

	var req ConfigUpsertReq
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	now := time.Now()
	valueJSON := "{}"
	if jsonBytes, err := json.Marshal(req.Value); err == nil {
		valueJSON = string(jsonBytes)
	}

	// Check if exists using raw SQL
	existing, err := database.DB().Model("state_user_configs").Raw(
		`SELECT id FROM state_user_configs WHERE tenant_id = $1 AND user_id = $2 AND scope = $3 AND key = $4`,
		tenantID, userID, req.Scope, req.Key).One()

	if err != nil || existing.IsEmpty() {
		// Create new using raw SQL
		_, err = database.DB().Exec(ctx,
			`INSERT INTO state_user_configs (tenant_id, user_id, scope, key, value, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $6)`,
			tenantID, userID, req.Scope, req.Key, valueJSON, now)
	} else {
		// Update existing using raw SQL
		_, err = database.DB().Exec(ctx,
			`UPDATE state_user_configs SET value = $1, updated_at = $2 WHERE tenant_id = $3 AND user_id = $4 AND scope = $5 AND key = $6`,
			valueJSON, now, tenantID, userID, req.Scope, req.Key)
	}

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to upsert config"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}

// =============================================================================
// Cache endpoints
// =============================================================================

// PutCacheMetadata stores cache metadata
func PutCacheMetadata(r *ghttp.Request) {
	ctx := context.Background()
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	cacheKey := r.Get("cacheKey").String()

	var req map[string]interface{}
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	now := time.Now()
	kind := req["kind"].(string)
	metadataJSON := "{}"
	if metadata, ok := req["metadata"].(map[string]interface{}); ok {
		if jsonBytes, err := json.Marshal(metadata); err == nil {
			metadataJSON = string(jsonBytes)
		}
	}

	// Check if exists using raw SQL
	existing, err := database.DB().Model("state_cache_metadata").Raw(
		`SELECT id FROM state_cache_metadata WHERE tenant_id = $1 AND user_id = $2 AND cache_key = $3`,
		tenantID, userID, cacheKey).One()

	if err != nil || existing.IsEmpty() {
		_, err = database.DB().Exec(ctx,
			`INSERT INTO state_cache_metadata (tenant_id, user_id, cache_key, kind, metadata_json, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $6)`,
			tenantID, userID, cacheKey, kind, metadataJSON, now)
	} else {
		_, err = database.DB().Exec(ctx,
			`UPDATE state_cache_metadata SET kind = $1, metadata_json = $2, updated_at = $3 WHERE tenant_id = $4 AND user_id = $5 AND cache_key = $6`,
			kind, metadataJSON, now, tenantID, userID, cacheKey)
	}

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to store cache metadata"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}

// GetCacheMetadata retrieves cache metadata
func GetCacheMetadata(r *ghttp.Request) {
	tenantID := r.GetParam("tenantID").String()
	userID := r.GetParam("userID").String()
	cacheKey := r.Get("cacheKey").String()

	record, err := database.DB().Model("state_cache_metadata").Raw(
		`SELECT id, tenant_id, user_id, session_id, cache_key, kind, object_uri, content_sha256, size_bytes, metadata_json, created_at, updated_at
		 FROM state_cache_metadata
		 WHERE tenant_id = $1 AND user_id = $2 AND cache_key = $3`,
		tenantID, userID, cacheKey).One()

	if err != nil || record.IsEmpty() {
		r.Response.WriteStatus(404)
		r.Response.WriteJson(g.Map{"detail": "Cache metadata not found"})
		return
	}

	r.Response.WriteJson(record)
}

// =============================================================================
// Usage endpoints
// =============================================================================

// UpdateUsage updates session token usage counters
func UpdateUsage(r *ghttp.Request) {
	ctx := context.Background()
	sessionID := r.Get("sessionId").String()

	var req UsageUpdateReq
	if err := r.Parse(&req); err != nil {
		r.Response.WriteStatus(400)
		r.Response.WriteJson(g.Map{"detail": err.Error()})
		return
	}

	_, err := database.DB().Exec(ctx,
		`UPDATE state_sessions SET
			input_tokens = input_tokens + $1,
			output_tokens = output_tokens + $2,
			cache_read_tokens = cache_read_tokens + $3,
			cache_write_tokens = cache_write_tokens + $4,
			reasoning_tokens = reasoning_tokens + $5
		 WHERE id = $6`,
		req.InputTokens, req.OutputTokens, req.CacheReadTokens, req.CacheWriteTokens, req.ReasoningTokens, sessionID)

	if err != nil {
		r.Response.WriteStatus(500)
		r.Response.WriteJson(g.Map{"detail": "failed to update usage"})
		return
	}

	r.Response.WriteJson(g.Map{"ok": true})
}
