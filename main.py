import os
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ---------- Your assigned values ----------
EMAIL = os.environ.get("EMAIL")
if not EMAIL:
    raise RuntimeError("Set the EMAIL environment variable before starting the server")       # <-- CHANGE THIS
ALLOWED_ORIGINS = [
    "https://app-0b7aov.example.com",             # your assigned origin
    "https://exam.sanand.workers.dev",            # the exam page (needed for grading)
]
BUCKET_SIZE = 13        # B requests...
WINDOW_SECONDS = 10     # ...per 10 seconds
# ------------------------------------------

app = FastAPI()


# ---------- Middleware 3: rate limiter (innermost) ----------
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        # one "notebook" per client: a list of timestamps of recent requests
        self.history = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        # Who is asking? Use X-Client-Id; fall back to IP if it's missing.
        client_id = request.headers.get("x-client-id") or (
            request.client.host if request.client else "unknown"
        )

        now = time.monotonic()
        timestamps = self.history[client_id]

        # Forget requests older than 10 seconds
        while timestamps and now - timestamps[0] > WINDOW_SECONDS:
            timestamps.popleft()

        # Already used up the bucket? Reject.
        if len(timestamps) >= BUCKET_SIZE:
            retry_after = max(1, int(WINDOW_SECONDS - (now - timestamps[0])) + 1)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )

        # Otherwise write down this request and let it through.
        timestamps.append(now)
        return await call_next(request)


# ---------- Middleware 1: request context ----------
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reuse the caller's ID if given, otherwise make a new one
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id          # so /ping can read it

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id  # always send it back
        return response


# ---------- Add middleware: LAST ADDED = OUTERMOST ----------
app.add_middleware(RateLimitMiddleware)          # innermost
app.add_middleware(RequestContextMiddleware)     # middle
app.add_middleware(                              # Middleware 2: CORS (outermost)
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,               # explicit list, NO "*"
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-Request-ID", "X-Client-Id", "Content-Type"],
    expose_headers=["X-Request-ID"],             # lets browser JS read this header
)


# ---------- The endpoint ----------
@app.get("/ping")
async def ping(request: Request):
    return {"email": EMAIL, "request_id": request.state.request_id}
