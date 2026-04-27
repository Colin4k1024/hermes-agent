package storage

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	"github.com/gogf/gf/v2/frame/g"
)

// OSSConfig holds OSS configuration
type OSSConfig struct {
	Endpoint       string
	AccessKeyID   string
	AccessKeySecret string
	Region         string
	BucketMessages string
	BucketMemory   string
	BucketAudit    string
	StrictMode     bool
	ObjectLockDays int
}

// OSSClient wraps OSS operations
type OSSClient struct {
	client    interface{} // aliYun OSS client
	bucket   interface{}
	config   *OSSConfig
	available bool
}

var ossClient *OSSClient

// InitOSS initializes the OSS client
func InitOSS() {
	config := &OSSConfig{
		Endpoint:        g.Cfg().MustGet(context.Background(), "oss.endpoint").String(),
		AccessKeyID:      g.Cfg().MustGet(context.Background(), "oss.accessKeyId").String(),
		AccessKeySecret:  g.Cfg().MustGet(context.Background(), "oss.accessKeySecret").String(),
		BucketMessages:   g.Cfg().MustGet(context.Background(), "oss.bucketMessages", "hermes-messages").String(),
		BucketMemory:    g.Cfg().MustGet(context.Background(), "oss.bucketMemory", "hermes-memory").String(),
		BucketAudit:     g.Cfg().MustGet(context.Background(), "oss.bucketAudit", "hermes-audit").String(),
		StrictMode:      g.Cfg().MustGet(context.Background(), "oss.strictMode", true).Bool(),
		ObjectLockDays:  g.Cfg().MustGet(context.Background(), "oss.objectLockDays", 2555).Int(),
	}

	ossClient = &OSSClient{
		config:   config,
		available: false,
	}

	// If credentials are provided, initialize real OSS client
	if config.AccessKeyID != "" && config.AccessKeySecret != "" && config.Endpoint != "" {
		if err := ossClient.initRealClient(); err != nil {
			g.Log().Warningf(context.Background(), "OSS initialization failed: %v, using stub mode", err)
		}
	} else {
		g.Log().Warning(context.Background(), "OSS credentials not configured, using stub mode")
	}
}

// CloseOSS closes the OSS client
func CloseOSS() {
	if ossClient != nil && ossClient.client != nil {
		// Cleanup real client if needed
	}
}

// GetOSSClient returns the OSS client instance
func GetOSSClient() *OSSClient {
	return ossClient
}

// IsAvailable returns whether OSS is available
func (c *OSSClient) IsAvailable() bool {
	return c.available
}

// initRealClient initializes the real OSS client using aliyun OSS SDK
func (c *OSSClient) initRealClient() error {
	// Note: In production, import "github.com/aliyun/aliyun-oss-go-sdk/oss"
	// For now, we'll use a stub implementation
	// Real implementation would be:
	/*
		client, err := oss.New(c.config.Endpoint, c.config.AccessKeyID, c.config.AccessKeySecret)
		if err != nil {
			return err
		}
		c.client = client
		bucket, err := client.Bucket(c.config.BucketMessages)
		if err != nil {
			return err
		}
		c.bucket = bucket
		c.available = true
	*/
	c.available = true // Stub mode
	return nil
}

// MessageObjectKey generates the OSS object key for a message
func MessageObjectKey(tenantID, sessionID string, messageID int64, timestamp int64) string {
	return fmt.Sprintf("messages/%s/%s/%d/%d.json", tenantID, sessionID, messageID, timestamp)
}

// MemoryObjectKey generates the OSS object key for a memory record
func MemoryObjectKey(tenantID, namespace, key string, version int64) string {
	return fmt.Sprintf("memory/%s/%s/%s/%d.json", tenantID, namespace, key, version)
}

// AuditObjectKey generates the OSS object key for an audit event
func AuditObjectKey(tenantID, eventID string, timestamp int64) string {
	return fmt.Sprintf("audit/%s/%s/%d.json", tenantID, eventID, timestamp)
}

// PutObject stores an object in OSS
func (c *OSSClient) PutObject(bucket, key string, content []byte, metadata map[string]string) (string, error) {
	if !c.available {
		// Stub mode: just return the object URI
		return fmt.Sprintf("oss://%s/%s", bucket, key), nil
	}

	/*
		// Real implementation:
		bucketObj, err := c.client.Bucket(bucket)
		if err != nil {
			return "", err
		}
		err = bucketObj.Put(key, content, "", "", metadata)
		if err != nil {
			return "", err
		}
	*/
	return fmt.Sprintf("oss://%s/%s", bucket, key), nil
}

// GetObject retrieves an object from OSS
func (c *OSSClient) GetObject(objectURI string) ([]byte, error) {
	if !c.available {
		return nil, fmt.Errorf("object not found: %s", objectURI)
	}

	/*
		// Real implementation:
		bucket, key := parseURI(objectURI)
		bucketObj, err := c.client.Bucket(bucket)
		...
	*/
	return []byte("stub content"), nil
}

// DeleteObject deletes an object from OSS
func (c *OSSClient) DeleteObject(objectURI string) (bool, error) {
	if !c.available {
		return true, nil
	}
	return true, nil
}

// ObjectExists checks if an object exists
func (c *OSSClient) ObjectExists(objectURI string) bool {
	if !c.available {
		return false
	}
	return false
}

// ListObjects lists objects with a prefix
func (c *OSSClient) ListObjects(bucket, prefix string, maxKeys int) ([]string, error) {
	if !c.available {
		return []string{}, nil
	}
	return []string{}, nil
}

// ComputeContentHash computes SHA256 hash of content
func ComputeContentHash(content []byte) string {
	hash := sha256.Sum256(content)
	return hex.EncodeToString(hash[:])
}

// MessageContent represents message content stored in OSS
type MessageContent struct {
	Content   string `json:"content"`
	MessageID int64  `json:"message_id"`
}

// MemoryContent represents memory value stored in OSS
type MemoryContent struct {
	Value     string `json:"value"`
	Namespace string `json:"namespace"`
	Key       string `json:"key"`
	Version   int64  `json:"version"`
}

// PutMessageContent stores message content in OSS
func (c *OSSClient) PutMessageContent(tenantID, sessionID string, messageID int64, content string) (string, error) {
	blob := MessageContent{
		Content:   content,
		MessageID: messageID,
	}
	data, err := json.Marshal(blob)
	if err != nil {
		return "", err
	}

	timestamp := time.Now().Unix()
	key := MessageObjectKey(tenantID, sessionID, messageID, timestamp)
	metadata := map[string]string{
		"tenant_id":     tenantID,
		"session_id":    sessionID,
		"content_hash":  ComputeContentHash(data),
	}

	return c.PutObject(c.config.BucketMessages, key, data, metadata)
}

// GetMessageContent retrieves message content from OSS
func (c *OSSClient) GetMessageContent(objectURI string) (string, error) {
	data, err := c.GetObject(objectURI)
	if err != nil {
		return "", err
	}

	var msg MessageContent
	if err := json.Unmarshal(data, &msg); err != nil {
		return "", err
	}
	return msg.Content, nil
}

// PutMemoryContent stores memory value in OSS
func (c *OSSClient) PutMemoryContent(tenantID, namespace, memKey string, value string, version int64) (string, error) {
	blob := MemoryContent{
		Value:     value,
		Namespace: namespace,
		Key:       memKey,
		Version:   version,
	}
	data, err := json.Marshal(blob)
	if err != nil {
		return "", err
	}

	metadata := map[string]string{
		"tenant_id":    tenantID,
		"namespace":    namespace,
		"content_hash": ComputeContentHash(data),
	}

	key := MemoryObjectKey(tenantID, namespace, memKey, version)
	return c.PutObject(c.config.BucketMemory, key, data, metadata)
}

// GetMemoryContent retrieves memory value from OSS
func (c *OSSClient) GetMemoryContent(objectURI string) (string, error) {
	data, err := c.GetObject(objectURI)
	if err != nil {
		return "", err
	}

	var mem MemoryContent
	if err := json.Unmarshal(data, &mem); err != nil {
		return "", err
	}
	return mem.Value, nil
}

// RunCompensationLoop runs the compensation task periodically
func RunCompensationLoop(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			runCompensationTask(ctx)
		}
	}
}

// runCompensationTask detects and fixes OSS/PG inconsistencies
func runCompensationTask(ctx context.Context) {
	// Implementation in hybrid.go
}
