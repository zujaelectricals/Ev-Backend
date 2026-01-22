# Access and Refresh Token Expiry - Frontend Integration Guide

## Overview

This document explains how access and refresh token expiry works in the EV Backend API and provides guidance for frontend integration to ensure seamless user authentication.

## Token Configuration

### Default Expiry Times

- **Access Token**: 60 minutes (1 hour)
- **Refresh Token**: 1440 minutes (24 hours)

> **Note**: These values are configurable via environment variables (`ACCESS_TOKEN_LIFETIME` and `REFRESH_TOKEN_LIFETIME`). The frontend should handle these dynamically or be aware that they may change.

### Token Rotation

The system uses **token rotation** with **blacklisting**:
- When a refresh token is used, it is immediately blacklisted
- A new access token AND a new refresh token are issued
- The old refresh token cannot be reused

## Token Lifecycle

### 1. Initial Login/Signup

When a user logs in or signs up, they receive both tokens:

```json
{
  "user": { ... },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
  }
}
```

**Frontend Action**: Store both tokens securely (localStorage, sessionStorage, or secure cookies).

### 2. Making Authenticated Requests

Include the access token in the Authorization header:

```
Authorization: Bearer <access_token>
```

**Frontend Action**: 
- Add the access token to all API requests
- Monitor for 401 Unauthorized responses (indicates expired access token)

### 3. Access Token Expiry (60 minutes)

When the access token expires:
- API requests will return `401 Unauthorized`
- The refresh token is still valid (if within 24 hours)

**Frontend Action**: 
- Detect 401 responses
- Automatically attempt to refresh the token
- Retry the original request with the new access token

### 4. Token Refresh

**Endpoint**: `POST /api/auth/refresh/`

**Request**:
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Response** (200 OK):
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Important Notes**:
- The old refresh token is **immediately blacklisted** after use
- You **MUST** update both tokens in storage
- If you try to use the old refresh token again, you'll get an error

**Error Response** (400 Bad Request):
```json
{
  "detail": "This refresh token has already been used. Please login again to get a new token."
}
```

**Frontend Action**:
- Always replace both tokens after a successful refresh
- Handle refresh token reuse errors by redirecting to login

### 5. Refresh Token Expiry (24 hours)

When the refresh token expires:
- Token refresh requests will fail
- User must log in again

**Frontend Action**:
- Detect refresh token expiry
- Clear stored tokens
- Redirect user to login page

## Frontend Implementation Recommendations

### 1. Token Storage

```javascript
// Recommended: Use secure storage
const TOKEN_STORAGE_KEY = 'auth_tokens';

function saveTokens(tokens) {
  localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens));
}

function getTokens() {
  const tokens = localStorage.getItem(TOKEN_STORAGE_KEY);
  return tokens ? JSON.parse(tokens) : null;
}

function clearTokens() {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}
```

### 2. Token Expiry Detection

```javascript
// Decode JWT to check expiry (without verification)
function isTokenExpired(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const exp = payload.exp * 1000; // Convert to milliseconds
    return Date.now() >= exp;
  } catch (e) {
    return true; // Treat invalid tokens as expired
  }
}

// Check if access token is expired or expiring soon (within 5 minutes)
function shouldRefreshToken(accessToken) {
  if (!accessToken) return true;
  
  try {
    const payload = JSON.parse(atob(accessToken.split('.')[1]));
    const exp = payload.exp * 1000;
    const now = Date.now();
    const buffer = 5 * 60 * 1000; // 5 minutes buffer
    
    return (exp - now) < buffer;
  } catch (e) {
    return true;
  }
}
```

### 3. Automatic Token Refresh

```javascript
let isRefreshing = false;
let refreshPromise = null;

async function refreshAccessToken() {
  // Prevent multiple simultaneous refresh requests
  if (isRefreshing) {
    return refreshPromise;
  }
  
  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const tokens = getTokens();
      if (!tokens || !tokens.refresh) {
        throw new Error('No refresh token available');
      }
      
      const response = await fetch('/api/auth/refresh/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          refresh: tokens.refresh
        })
      });
      
      if (!response.ok) {
        // Refresh token expired or invalid
        clearTokens();
        throw new Error('Refresh token expired');
      }
      
      const data = await response.json();
      
      // IMPORTANT: Update both tokens
      const newTokens = {
        access: data.access,
        refresh: data.refresh
      };
      saveTokens(newTokens);
      
      return newTokens;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();
  
  return refreshPromise;
}
```

### 4. API Request Interceptor

```javascript
async function makeAuthenticatedRequest(url, options = {}) {
  let tokens = getTokens();
  
  // Check if access token needs refresh
  if (!tokens || shouldRefreshToken(tokens.access)) {
    try {
      tokens = await refreshAccessToken();
    } catch (error) {
      // Refresh failed, redirect to login
      clearTokens();
      window.location.href = '/login';
      throw error;
    }
  }
  
  // Add access token to request
  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${tokens.access}`
  };
  
  let response = await fetch(url, {
    ...options,
    headers
  });
  
  // If 401, try refreshing once more
  if (response.status === 401) {
    try {
      tokens = await refreshAccessToken();
      headers['Authorization'] = `Bearer ${tokens.access}`;
      response = await fetch(url, {
        ...options,
        headers
      });
    } catch (error) {
      clearTokens();
      window.location.href = '/login';
      throw error;
    }
  }
  
  return response;
}
```

### 5. Axios Interceptor Example (React/Next.js)

```javascript
import axios from 'axios';

// Create axios instance
const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
});

// Request interceptor - add access token
apiClient.interceptors.request.use(
  async (config) => {
    const tokens = getTokens();
    
    if (tokens && tokens.access) {
      // Check if token needs refresh
      if (shouldRefreshToken(tokens.access)) {
        try {
          const newTokens = await refreshAccessToken();
          config.headers.Authorization = `Bearer ${newTokens.access}`;
        } catch (error) {
          clearTokens();
          window.location.href = '/login';
          return Promise.reject(error);
        }
      } else {
        config.headers.Authorization = `Bearer ${tokens.access}`;
      }
    }
    
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - handle 401 errors
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    // If 401 and haven't retried yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      
      try {
        const tokens = await refreshAccessToken();
        originalRequest.headers.Authorization = `Bearer ${tokens.access}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        clearTokens();
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }
    
    return Promise.reject(error);
  }
);
```

### 6. Logout Implementation

```javascript
async function logout() {
  const tokens = getTokens();
  
  if (tokens && tokens.refresh) {
    try {
      await fetch('/api/auth/logout/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${tokens.access}`
        },
        body: JSON.stringify({
          refresh: tokens.refresh
        })
      });
    } catch (error) {
      console.error('Logout error:', error);
      // Continue with local cleanup even if API call fails
    }
  }
  
  clearTokens();
  window.location.href = '/login';
}
```

## Error Handling

### Common Error Scenarios

1. **Access Token Expired (401)**
   - **Action**: Automatically refresh token and retry request
   - **User Impact**: None (transparent refresh)

2. **Refresh Token Expired (400)**
   - **Error**: `"This refresh token has already been used"` or `"Invalid token"`
   - **Action**: Clear tokens, redirect to login
   - **User Impact**: User must log in again

3. **Refresh Token Already Used (400)**
   - **Error**: `"This refresh token has already been used. Please login again to get a new token."`
   - **Action**: Clear tokens, redirect to login
   - **User Impact**: User must log in again
   - **Note**: This can happen if multiple tabs/windows try to refresh simultaneously

4. **No Tokens Available**
   - **Action**: Redirect to login
   - **User Impact**: User must log in

## Best Practices

### 1. Proactive Token Refresh
- Refresh the access token **before** it expires (e.g., 5 minutes before expiry)
- This prevents failed API requests

### 2. Prevent Concurrent Refreshes
- Use a flag or promise to prevent multiple simultaneous refresh requests
- Share the refresh result across concurrent requests

### 3. Secure Token Storage
- Consider using `httpOnly` cookies for tokens (if supported by your setup)
- If using localStorage, ensure your app is served over HTTPS
- Never log or expose tokens in console/debug output

### 4. Handle Multiple Tabs
- If multiple tabs are open, coordinate token refresh
- Consider using `BroadcastChannel` or `localStorage` events to sync tokens across tabs

### 5. Network Error Handling
- If refresh fails due to network error, retry with exponential backoff
- Don't immediately redirect to login on network errors

## Testing Checklist

- [ ] Access token is automatically refreshed before expiry
- [ ] 401 errors trigger automatic token refresh
- [ ] Failed requests are retried after token refresh
- [ ] Refresh token rotation works correctly (old token is replaced)
- [ ] Using old refresh token after refresh fails appropriately
- [ ] Refresh token expiry redirects to login
- [ ] Logout properly blacklists refresh token
- [ ] Multiple concurrent requests don't cause multiple refresh attempts
- [ ] Network errors during refresh are handled gracefully
- [ ] Tokens are cleared on logout

## API Endpoints Summary

| Endpoint | Method | Auth Required | Purpose |
|----------|--------|---------------|---------|
| `/api/auth/refresh/` | POST | No (needs refresh token) | Get new access and refresh tokens |
| `/api/auth/logout/` | POST | Yes (access token) | Blacklist refresh token and logout |

## Token Refresh Request/Response

**Request**:
```http
POST /api/auth/refresh/
Content-Type: application/json

{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Success Response** (200):
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Error Response** (400):
```json
{
  "detail": "This refresh token has already been used. Please login again to get a new token."
}
```

or

```json
{
  "detail": "Invalid token: Token is blacklisted"
}
```

## Security Considerations

1. **Token Rotation**: The system automatically rotates refresh tokens to prevent token reuse attacks
2. **Blacklisting**: Used refresh tokens are blacklisted and cannot be reused
3. **HTTPS**: Always use HTTPS in production to protect tokens in transit
4. **Token Storage**: Choose secure storage mechanism based on your security requirements

## Support

For questions or issues related to token management, please contact the backend team or refer to the main API documentation (`apidoc.txt`).

---

**Last Updated**: Based on backend configuration as of current date
**Backend Version**: EV Backend (Django REST Framework + Simple JWT)

