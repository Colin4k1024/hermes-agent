package main

import (
	"context"
	"fmt"
	"os"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"
	"github.com/gogf/gf/v2/os/gcmd"

	"github.com/hermes-agent/state-service-go/internal/controller"
	"github.com/hermes-agent/state-service-go/internal/database"
	"github.com/hermes-agent/state-service-go/internal/middleware"
	"github.com/hermes-agent/state-service-go/internal/storage"
)

var (
	MainCmd = gcmd.Command{
		Name:  "hermes-state-service",
		Usage: "hermes-state-service",
		Brief: "Hermes State Service - Remote user state for stateless Agent runtimes",
		Func: func(ctx context.Context, parser *gcmd.Parser) (err error) {
			// Initialize database
			if err = database.Init(); err != nil {
				g.Log().Errorf(ctx, "failed to initialize database: %v", err)
				os.Exit(1)
			}
			defer database.Close()

			// Initialize OSS storage
			storage.InitOSS()
			defer storage.CloseOSS()

			// Start compensation task goroutine
			go storage.RunCompensationLoop(ctx)

			// Create HTTP server
			s := g.Server("hermes-state-service")

			// Global middleware
			s.Use(middleware.CORS)
			s.Use(middleware.RateLimiter)
			s.Use(ghttp.MiddlewareHandlerResponse)

			// Health endpoints
			s.Group("/health", func(group *ghttp.RouterGroup) {
				group.GET("/live", controller.HealthLive)
				group.GET("/ready", controller.HealthReady)
			})

			// State API v1
			stateGroup := s.Group("/state")
			stateGroup.Middleware(middleware.Auth)

			// Config endpoints
			stateGroup.GET("/config/effective", controller.GetEffectiveConfig)
			stateGroup.PUT("/config", controller.UpsertConfig)

			// Session endpoints
			stateGroup.POST("/sessions", controller.CreateSession)
			stateGroup.GET("/sessions", controller.ListSessions)
			stateGroup.GET("/sessions/{sessionId}", controller.GetSession)
			stateGroup.GET("/sessions/{sessionId}/metadata", controller.GetSessionMetadata)
			stateGroup.PATCH("/sessions/{sessionId}", controller.PatchSession)
			stateGroup.POST("/sessions/{sessionId}/end", controller.EndSession)
			stateGroup.POST("/sessions/{sessionId}/reopen", controller.ReopenSession)

			// Message endpoints (with rate limiting)
			stateGroup.POST("/sessions/{sessionId}/messages", controller.AppendMessage)
			stateGroup.GET("/sessions/{sessionId}/messages", controller.GetMessages)

			// Message search
			stateGroup.GET("/messages/search", controller.SearchMessages)

			// Memory endpoints
			stateGroup.GET("/memory", controller.ListMemory)
			stateGroup.PUT("/memory/{namespace}/{key}", controller.UpsertMemory)
			stateGroup.DELETE("/memory/{namespace}/{key}", controller.DeleteMemory)

			// Cache endpoints
			stateGroup.PUT("/cache/{cacheKey}", controller.PutCacheMetadata)
			stateGroup.GET("/cache/{cacheKey}", controller.GetCacheMetadata)

			// Usage update
			stateGroup.POST("/sessions/{sessionId}/usage", controller.UpdateUsage)

			// Start server
			bindAddr := fmt.Sprintf("%s:%d", os.Getenv("STATE_HOST"), 8006)
			if bindAddr == ":" {
				bindAddr = ":8006"
			}
			s.SetPort(8006)
			s.Run()
			return nil
		},
	}
)

func main() {
	MainCmd.Run(context.Background())
}
