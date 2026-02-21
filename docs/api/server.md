# Server Module

The server module provides an OpenAI-compatible API server built on FastAPI
and uvicorn. It exposes `POST /v1/chat/completions` (with streaming via SSE),
`GET /v1/models`, and `GET /health` endpoints. Pydantic models ensure
request/response validation matching the OpenAI API format.

## Application Factory

### create_app

::: openjarvis.server.app.create_app
    options:
      show_source: true

---

## Route Handlers

### chat_completions

::: openjarvis.server.routes.chat_completions
    options:
      show_source: true

### list_models

::: openjarvis.server.routes.list_models
    options:
      show_source: true

### health

::: openjarvis.server.routes.health
    options:
      show_source: true

---

## Pydantic Request/Response Models

### ChatMessage

::: openjarvis.server.models.ChatMessage
    options:
      show_source: true
      members_order: source

### ChatCompletionRequest

::: openjarvis.server.models.ChatCompletionRequest
    options:
      show_source: true
      members_order: source

### ChatCompletionResponse

::: openjarvis.server.models.ChatCompletionResponse
    options:
      show_source: true
      members_order: source

### Choice

::: openjarvis.server.models.Choice
    options:
      show_source: true
      members_order: source

### ChoiceMessage

::: openjarvis.server.models.ChoiceMessage
    options:
      show_source: true
      members_order: source

### UsageInfo

::: openjarvis.server.models.UsageInfo
    options:
      show_source: true
      members_order: source

### ChatCompletionChunk

::: openjarvis.server.models.ChatCompletionChunk
    options:
      show_source: true
      members_order: source

### DeltaMessage

::: openjarvis.server.models.DeltaMessage
    options:
      show_source: true
      members_order: source

### StreamChoice

::: openjarvis.server.models.StreamChoice
    options:
      show_source: true
      members_order: source

### ModelObject

::: openjarvis.server.models.ModelObject
    options:
      show_source: true
      members_order: source

### ModelListResponse

::: openjarvis.server.models.ModelListResponse
    options:
      show_source: true
      members_order: source
