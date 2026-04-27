package middleware

import (
	"github.com/gogf/gf/v2/net/ghttp"
)

// CORS handles Cross-Origin Resource Sharing
func CORS(r *ghttp.Request) {
	r.Response.CORS(ghttp.CORSOptions{
		AllowOrigin:  "*",
		AllowMethods: "GET,POST,PUT,PATCH,DELETE,OPTIONS",
		AllowHeaders: "Authorization,X-Tenant-ID,X-User-ID,X-Session-ID,X-Request-ID,Content-Type",
		ExposeHeaders: "",
	})
	r.Middleware.Next()
}
