package middleware

import (
	"context"

	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"
	"github.com/redis/go-redis/v9"
)

// RateLimiter implements per-user rate limiting using Redis
func RateLimiter(r *ghttp.Request) {
	ctx := context.Background()

	// Get Redis client
	redisHost := g.Cfg().MustGet(ctx, "redis.default.host").String()
	if redisHost == "" {
		redisHost = "localhost"
	}
	redisDB := g.Cfg().MustGet(ctx, "redis.default.db").Int()
	if redisDB == 0 {
		redisDB = 0
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:     redisHost,
		Password: "",
		DB:       redisDB,
	})
	defer rdb.Close()

	// Build rate limit key
	tenantID := r.Header.Get("X-Tenant-ID")
	userID := r.Header.Get("X-User-ID")
	endpoint := r.Request.URL.Path
	key := "rl:" + tenantID + ":" + userID + ":" + endpoint

	// Increment counter
	count, err := rdb.Incr(ctx, key).Result()
	if err != nil {
		// Fail open on Redis error
		r.Middleware.Next()
		return
	}

	// Set TTL on first request
	if count == 1 {
		rdb.Expire(ctx, key, 60)
	}

	// Check limit
	limit := 100 // default
	if endpoint == "/state/sessions" && r.Method == "POST" {
		limit = 30
	}

	if count > int64(limit) {
		r.Response.WriteStatus(429)
		r.Response.WriteJson(g.Map{
			"detail": "Rate limit exceeded — please slow down",
		})
		return
	}

	r.Middleware.Next()
}
