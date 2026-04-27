package middleware

import (
	"github.com/gogf/gf/v2/frame/g"
	"github.com/gogf/gf/v2/net/ghttp"
)

// RequestContext holds the authenticated request context
type RequestContext struct {
	TenantID  string
	UserID   string
	SessionID string
	RequestID string
}

// Auth validates the request authentication headers
func Auth(r *ghttp.Request) {
	tenantID := r.Header.Get("X-Tenant-ID")
	userID := r.Header.Get("X-User-ID")
	sessionID := r.Header.Get("X-Session-ID")
	requestID := r.Header.Get("X-Request-ID")

	if tenantID == "" {
		tenantID = "default"
	}
	if userID == "" {
		r.Response.WriteStatus(401)
		r.Response.WriteJson(g.Map{
			"detail": "X-User-ID header is required",
		})
		return
	}

	// Store context for later use
	r.SetParam("tenantID", tenantID)
	r.SetParam("userID", userID)
	r.SetParam("sessionID", sessionID)
	r.SetParam("requestID", requestID)

	r.Middleware.Next()
}
