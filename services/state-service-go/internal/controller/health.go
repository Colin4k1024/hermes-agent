package controller

import (
	"context"
	"time"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"

	"github.com/hermes-agent/state-service-go/internal/database"
)

// HealthLive returns a simple liveness check
func HealthLive(r *ghttp.Request) {
	r.Response.WriteJson(g.Map{
		"service": "state-service",
		"version": "0.1.0",
	})
}

// HealthReady returns a readiness check with dependency status
func HealthReady(r *ghttp.Request) {
	ctx := context.Background()
	dbOK := true

	// Check database connection using a simple query
	if _, err := database.DB().Model("state_sessions").Limit(1).Fields("1").All(ctx); err != nil {
		dbOK = false
	}

	status := g.Map{
		"service": "state-service",
		"version":  "0.1.0",
		"db_ok":    dbOK,
		"time":     time.Now().Format(time.RFC3339),
	}

	if !dbOK {
		r.Response.WriteStatus(503)
		r.Response.WriteJson(status)
		return
	}

	r.Response.WriteJson(status)
}
