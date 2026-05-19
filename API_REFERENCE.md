# Execution Panel API Reference

## Real-Time Data Persistence API

All endpoints accept and return JSON. Changes are saved immediately without page reload.

### Update Execution Result Status and Comment

**Endpoint**: `PATCH /api/execution-result/<int:result_id>`

**Request Body**:
```json
{
  "status": "pass" | "fail" | "pending",
  "comment": "Optional comment text"
}
```

**Response**:
```json
{
  "id": 42,
  "status": "pass",
  "comment": "Verified the output matches expected value"
}
```

**HTTP Status Codes**:
- 200: Success
- 404: Result not found
- 500: Server error

**Example Usage** (from JavaScript):
```javascript
saveResultStatus(resultId, 'pass', 'Test passed successfully');
// Makes: PATCH /api/execution-result/42
//        {status: 'pass', comment: 'Test passed successfully'}
```

---

### Update Execution Step Comment

**Endpoint**: `PATCH /api/execution-step/<int:step_id>`

**Request Body**:
```json
{
  "comment": "Optional comment text"
}
```

**Response**:
```json
{
  "id": 15,
  "comment": "User encountered timeout warning but test continued"
}
```

**HTTP Status Codes**:
- 200: Success
- 404: Step not found
- 500: Server error

**Example Usage** (from JavaScript):
```javascript
saveStepComment(stepId, 'Application took longer than expected');
// Makes: PATCH /api/execution-step/15
//        {comment: 'Application took longer than expected'}
```

---

### Update Execution Test Status and Comment

**Endpoint**: `PATCH /api/execution-test/<int:test_id>`

**Request Body**:
```json
{
  "status": "pass" | "fail" | "pending",
  "comment": "Optional comment text"
}
```

**Response**:
```json
{
  "id": 7,
  "status": "fail",
  "comment": "One assertion failed"
}
```

**HTTP Status Codes**:
- 200: Success
- 404: Test not found
- 500: Server error

**Example Usage** (from JavaScript):
```javascript
saveTestStatus(testId, 'fail', 'Test did not complete');
// Makes: PATCH /api/execution-test/7
//        {status: 'fail', comment: 'Test did not complete'}
```

---

## Data Models

### ExecutionResult
- `id`: integer, primary key
- `execution_step_id`: integer, foreign key
- `text`: string, the expected result text
- `order_index`: integer, position in step
- `status`: string, one of 'pending', 'pass', 'fail'
- `comment`: string, optional user comment

### ExecutionStep
- `id`: integer, primary key
- `execution_test_id`: integer, foreign key
- `text`: string, the step instruction
- `path`: string or null, application path
- `resource`: string or null, resource path
- `order_index`: integer, position in test
- `comment`: string, optional user comment

### ExecutionTest
- `id`: integer, primary key
- `execution_id`: integer, foreign key
- `title`: string, test title
- `context`: JSON object, test context
- `setup`: JSON array, setup instructions
- `status`: string, one of 'pending', 'pass', 'fail'
- `comment`: string, optional user comment
- `order_index`: integer, position in execution
- (plus other fields for source test tracking)

---

## Payload Structure (GET)

When loading execution suite data via `_build_execution_suite_payload()`:

```json
{
  "id": "exec-suite-1",
  "name": "Authentication",
  "testsets": [
    {
      "id": "exec-set-1",
      "name": "Login Methods",
      "tests": [
        {
          "id": "exec-test-1",
          "title": "Valid Email Login",
          "context": {
            "email": "test@example.com",
            "role": "user"
          },
          "setup": [
            "Clear browser cache",
            "Navigate to login page"
          ],
          "status": "pending",
          "comment": "",
          "steps": [
            {
              "id": "exec-step-1",
              "text": "Enter credentials",
              "path": "/login",
              "resource": "resources/credentials.json",
              "resource_url": "https://github.com/owner/repo/blob/main/resources/credentials.json",
              "comment": "",
              "results": [
                {
                  "id": "exec-result-1",
                  "text": "No validation errors",
                  "status": "pending",
                  "comment": ""
                },
                {
                  "id": "exec-result-2",
                  "text": "User redirected to dashboard",
                  "status": "pass",
                  "comment": "Verified redirect"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Error Handling

### Common Error Responses

**404 Not Found**:
```json
{
  "error": "Result not found"
}
```

**500 Server Error**:
```json
{
  "error": "Database connection failed"
}
```

### Client-Side Error Handling

The JavaScript client catches and logs errors automatically:
```javascript
saveResultStatus(resultId, 'pass', 'comment')
  .catch(err => {
    console.error('Failed to save result status:', err);
    // User sees no visual feedback if save fails
    return null;
  });
```

---

## Response Times

Typical response times (measured in ms):
- Update result: 10-50ms
- Update step comment: 10-50ms
- Update test status: 10-50ms

No batching is performed; each change is sent separately to the API.

---

## Rate Limiting

No rate limiting is currently implemented. Consider adding if UI allows rapid successive saves.

---

## Session & Authentication

All endpoints require a valid Flask session (same as web pages).
No additional authentication headers required.

---

## CORS

CORS is not enabled. Execution panel must be accessed from same domain as API.

---

## Backwards Compatibility

The payload structure is backwards compatible with existing code that expects:
- `results` as strings: Old code continues to work
- New code receives full result objects with id, text, status, comment

The `_text_value()` function ensures graceful fallback if result is a string.

