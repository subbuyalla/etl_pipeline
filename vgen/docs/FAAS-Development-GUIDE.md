# VGen FaaS Functions Developer Guide

This comprehensive guide covers developing FaaS (Function as a Service) tools for the VGen platform. It includes runtime SDKs, available services (Prajna, Smriti, Kriya), handler patterns, error handling, and complete function references.

---

## Table of Contents

1. [FaaS Overview](#faas-overview)
2. [Handler Function Pattern](#handler-function-pattern)
3. [Context Object Structure](#context-object-structure)
4. [Error Handling Best Practices](#error-handling-best-practices)
5. [Using NPM Modules](#using-npm-modules)
6. [Runtime SDKs](#runtime-sdks)
7. [Smriti Service (Data Layer)](#smriti-service-data-layer)
8. [Prajna Service (LLM Layer)](#prajna-service-llm-layer)
9. [Kriya Service (Tool Execution Engine)](#kriya-service-tool-execution-engine)
10. [Complete Examples](#complete-examples)

---

## FaaS Overview

**FaaS (Function as a Service)** tools are containerized JavaScript/TypeScript functions that run in a dedicated Node.js runtime environment. They provide:

- Full Node.js runtime with npm package support
- Pre-configured SDKs for internal services (Prajna, Smriti, Kriya)
- Access to database, vector search, secrets management, and LLM capabilities
- Isolated execution environment with proper error handling

### When to Use FaaS

- **Use FaaS when you need:**
  - External npm package dependencies
  - Database operations (CRUD, vector search)
  - Secrets management (API keys, credentials)
  - LLM interactions with structured outputs
  - Complex business logic requiring multiple service calls
- **Use JS (fast services) when you need:**
  - Simple data transformations
  - Quick API calls
  - Platform API usage only (no external dependencies)

---

## Handler Function Pattern

Every FaaS function **must** export an `async function handler(event)` as the entry point. The platform invokes this function and passes the execution context.

### Basic Structure

```javascript
// Import any required SDK
import { smriti } from '/runtime/runtime-sdks/smriti.js';
import { prajna } from '/runtime/runtime-sdks/prajna.js';
import { kriya } from '/runtime/runtime-sdks/kriya.js';

// Import npm packages (if needed)
const _ = require('lodash');

/**
 * Handler function - entry point for FaaS execution
 * @param {object} event - Event object containing context
 * @returns {object} - Result object
 */
async function handler(event) {
    const context = event.context;
    
    try {
        // Your function logic here
        const input = context.input;
        
        // Perform operations
        const result = await performOperation(input);
        
        // Return success response
        return {
            success: true,
            message: 'Operation completed successfully',
            data: result
        };
        
    } catch (error) {
        // Always catch and return errors - never let exceptions crash the container
        console.error('Handler error:', error);
        return {
            success: false,
            error: error.message,
            stack: error.stack // Optional: include for debugging
        };
    }
}

// Export the handler
export default handler;
```

### Key Rules

1. **Handler name:** Must be `handler` (lowercase)
2. **Export:** Must be exported as default: `export default handler`
3. **Async:** Must be async to support await operations
4. **Error handling:** Must wrap logic in try-catch (see next section)
5. **Return value:** Must return an object (JSON serializable)

---

## Context Object Structure

The `event.context` object contains all execution context passed from the platform. It includes user input, session data, conversation history, and metadata.

### Context Properties

```javascript
const context = event.context;

// Available context properties:
const {
    input,              // User arguments passed to the tool (object)
    context: ctxData,   // Additional context data (object)
    session,            // Session ID (string)
    history,            // Conversation history (array)
    user_message,       // Current user message (string)
    roc_user_session,   // ROC user session data (object)
    client_information, // Client metadata (string/object)
    assigned_agent      // Agent slug handling this request (string)
} = context;
```

### Context Properties Explained


| Property             | Type          | Description                                                                            |
| -------------------- | ------------- | -------------------------------------------------------------------------------------- |
| `input`              | object        | Arguments passed to the tool from the agent. Defined by tool's `arguments` schema.     |
| `context`            | object        | Additional context data from the platform (optional).                                  |
| `session`            | string        | Unique session ID for this conversation.                                               |
| `history`            | array         | Array of previous messages in the conversation. Each message has `role` and `content`. |
| `user_message`       | string        | The current user's question/message.                                                   |
| `roc_user_session`   | object        | ROC (Resmed Operations Center) user session data including user ID, permissions, etc.  |
| `client_information` | string/object | Client metadata (browser, app version, etc.).                                          |
| `assigned_agent`     | string        | The slug of the agent that invoked this tool.                                          |


### Accessing Context Example

```javascript
async function handler(event) {
    const context = event.context;
    
    try {
        // Access user input arguments
        const { query, limit, filters } = context.input;
        
        // Access session ID for caching
        const sessionId = context.session;
        
        // Access conversation history
        const previousMessages = context.history;
        
        // Access current user message
        const userQuestion = context.user_message;
        
        // Access user information
        const userId = context.roc_user_session?.userId;
        
        // Log for debugging
        console.log('Processing request for user:', userId);
        console.log('Agent:', context.assigned_agent);
        
        // Your logic here
        
    } catch (error) {
        return { success: false, error: error.message };
    }
}
```

---

## Error Handling Best Practices

**CRITICAL:** Always wrap your handler logic in try-catch blocks. If an exception is thrown and not caught, the container exits, and the tool execution fails completely.

### Why Error Handling is Critical

Without proper error handling:

- Container crashes on uncaught exceptions
- No error information is returned to the agent
- User sees a generic failure message
- Debugging becomes difficult

### Proper Error Handling Pattern

```javascript
async function handler(event) {
    const context = event.context;
    
    try {
        // All your logic here
        const result = await someOperation();
        
        // Return success response
        return {
            success: true,
            data: result,
            message: 'Operation completed'
        };
        
    } catch (error) {
        // Log the error for debugging
        console.error('Error in handler:', error);
        console.error('Stack trace:', error.stack);
        
        // Return structured error response
        return {
            success: false,
            error: error.message,
            errorType: error.constructor.name,
            // Optional: include for development/debugging
            stack: process.env.NODE_ENV === 'development' ? error.stack : undefined
        };
    }
}
```

### Handling Specific Error Types

```javascript
async function handler(event) {
    const context = event.context;
    
    try {
        // Validate input
        if (!context.input.query) {
            throw new Error('Query parameter is required');
        }
        
        // Call external service
        const records = await smriti.db.queryRecords({
            documentqueries: [{
                collection: "users",
                query: { email: context.input.email }
            }]
        });
        
        if (!records || records.length === 0) {
            return {
                success: true,
                data: [],
                message: 'No records found'
            };
        }
        
        return {
            success: true,
            data: records,
            message: `Found ${records.length} records`
        };
        
    } catch (error) {
        // Handle different error types
        if (error.message.includes('connection')) {
            return {
                success: false,
                error: 'Database connection failed',
                retryable: true
            };
        }
        
        if (error.message.includes('unauthorized')) {
            return {
                success: false,
                error: 'Authentication failed',
                retryable: false
            };
        }
        
        // Generic error handler
        console.error('Unexpected error:', error);
        return {
            success: false,
            error: error.message || 'An unexpected error occurred',
            retryable: false
        };
    }
}
```

### Error Response Format

Always return a consistent error format:

```javascript
{
    success: false,
    error: "Error message here",
    errorType: "ErrorClassName",      // Optional
    errorCode: "ERR_VALIDATION",      // Optional
    retryable: false,                 // Optional
    details: { /* ... */ }            // Optional additional context
}
```

---

## Using NPM Modules

FaaS functions support npm packages. You can use any package from the npm registry in your functions.

### Configuring package.json

Create a `package.json` file in your tool folder alongside your handler:

**Example: `tools/my-tool/package.json`**

```json
{
  "name": "my-tool",
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "lodash": "^4.17.21",
    "axios": "^1.6.0",
    "moment": "^2.29.4",
    "validator": "^13.11.0"
  }
}
```

### Important package.json Settings


| Field          | Value    | Required | Description                           |
| -------------- | -------- | -------- | ------------------------------------- |
| `name`         | string   | Yes      | Package name (should match tool name) |
| `version`      | string   | Yes      | Semantic version (e.g., "1.0.0")      |
| `type`         | "module" | **Yes**  | Must be "module" for ES6 imports      |
| `dependencies` | object   | No       | npm packages to install               |


**CRITICAL:** Always set `"type": "module"` to support ES6 import/export syntax.

### Using NPM Packages in Handler

```javascript
// Import SDK (always use /runtime path)
import { smriti } from '/runtime/runtime-sdks/smriti.js';

// Import npm packages using require (CommonJS)
const _ = require('lodash');
const axios = require('axios');
const moment = require('moment');

// Or use ES6 imports (if package supports it)
import lodash from 'lodash';

async function handler(event) {
    const context = event.context;
    
    try {
        // Use lodash
        const uniqueItems = _.uniq(context.input.items);
        
        // Use moment
        const formattedDate = moment().format('YYYY-MM-DD');
        
        // Use axios
        const response = await axios.get('https://api.example.com/data');
        
        return {
            success: true,
            data: {
                items: uniqueItems,
                date: formattedDate,
                apiData: response.data
            }
        };
        
    } catch (error) {
        return { success: false, error: error.message };
    }
}

export default handler;
```

### Common NPM Packages for FaaS


| Package               | Use Case          | Example                                    |
| --------------------- | ----------------- | ------------------------------------------ |
| `lodash`              | Data manipulation | `_.uniq()`, `_.groupBy()`, `_.merge()`     |
| `axios`               | HTTP requests     | `axios.get()`, `axios.post()`              |
| `moment` / `date-fns` | Date handling     | `moment().format()`, `parse()`             |
| `validator`           | Input validation  | `validator.isEmail()`, `validator.isURL()` |
| `uuid`                | Generate UUIDs    | `uuid.v4()`                                |
| `jsonwebtoken`        | JWT operations    | `jwt.sign()`, `jwt.verify()`               |
| `csv-parser`          | CSV processing    | Parse CSV data                             |
| `xml2js`              | XML processing    | Parse/convert XML                          |


### Package Installation

When you push a FaaS tool with a `package.json`, the platform automatically:

1. Reads the `package.json`
2. Runs `npm install` in the container
3. Makes packages available to your handler

**Note:** Large packages may increase container startup time. Use only necessary dependencies.

---

## Runtime SDKs

FaaS functions have pre-configured access to three internal services through runtime SDKs:

1. **Smriti SDK** - Data layer (database, vector search, secrets)
2. **Prajna SDK** - LLM layer (chat, embeddings, assistants)
3. **Kriya SDK** - Tool execution engine (agents, tools, assistants)

### Importing SDKs

```javascript
// Import pre-configured clients (recommended)
import { smriti } from '/runtime/runtime-sdks/smriti.js';
import { prajna } from '/runtime/runtime-sdks/prajna.js';
import { kriya } from '/runtime/runtime-sdks/kriya.js';

// Import classes for custom configuration (advanced)
import { SmritiClient } from '/runtime/runtime-sdks/smriti.js';
import { PrajnaClient } from '/runtime/runtime-sdks/prajna.js';
import { KriyaClient } from '/runtime/runtime-sdks/kriya.js';
```

### Pre-configured vs Custom Clients

**Pre-configured (Recommended):**

```javascript
import { smriti } from '/runtime/runtime-sdks/smriti.js';

// Ready to use - no configuration needed
const records = await smriti.db.queryRecords({...});
```

**Custom Configuration (Advanced):**

```javascript
import { SmritiClient } from '/runtime/runtime-sdks/smriti.js';

// Create custom client with different base URL
const customSmriti = new SmritiClient({
    baseUrl: 'https://custom-smriti.example.com',
    headers: { 'X-Custom-Header': 'value' }
});

const records = await customSmriti.db.queryRecords({...});
```

### Environment Variables

SDKs automatically use these environment variables (injected by the platform):


| Variable          | Default                 | Description        |
| ----------------- | ----------------------- | ------------------ |
| `SMRITI_BASE_URL` | `http://localhost:6222` | Smriti service URL |
| `PRAJNA_BASE_URL` | `http://localhost:5331` | Prajna service URL |
| `KRIYA_BASE_URL`  | `http://localhost:9319` | Kriya service URL  |


---

## Smriti Service (Data Layer)

Smriti provides database operations, vector search, and secrets management. Access via `smriti.db`, `smriti.vector`, and `smriti.secrets` modules.

### Database Module (`smriti.db`)

Complete CRUD operations and hybrid vector-metadata search.

#### createCollection

Create a new database collection.

```javascript
import { smriti } from '/runtime/runtime-sdks/smriti.js';

await smriti.db.createCollection({
    collection: "users"
});
```

**Arguments:**

- `collection` (string, required): Collection name

**Returns:** `{ success: true }` or throws error

---

#### createRecord

Insert a new record into a collection.

```javascript
const newRecord = await smriti.db.createRecord({
    collection: "users",
    payload: {
        name: "John Doe",
        email: "john@example.com",
        role: "admin",
        createdAt: new Date().toISOString()
    }
});

console.log('Created record ID:', newRecord._id);
```

**Arguments:**

- `collection` (string, required): Collection name
- `payload` (object, required): Record data (any valid JSON object)

**Returns:** Created record with `_id` field

**Example Response:**

```json
{
    "_id": "507f1f77bcf86cd799439011",
    "name": "John Doe",
    "email": "john@example.com",
    "role": "admin",
    "createdAt": "2024-01-15T10:30:00.000Z"
}
```

---

#### getRecord

Retrieve a single record by ID.

```javascript
const record = await smriti.db.getRecord({
    collection: "users",
    id: "507f1f77bcf86cd799439011"
});

if (record) {
    console.log('Found user:', record.name);
} else {
    console.log('Record not found');
}
```

**Arguments:**

- `collection` (string, required): Collection name
- `id` (string, required): Record ID (MongoDB ObjectId string)

**Returns:** Record object or `null` if not found

---

#### queryRecords

Query records with filters and options (MongoDB-style queries).

```javascript
const results = await smriti.db.queryRecords({
    documentqueries: [{
        collection: "users",
        query: { 
            role: "admin",
            status: "active"
        },
        options: {
            limit: 10,
            sort: { createdAt: -1 },
            projection: { name: 1, email: 1 },
            skip: 0
        }
    }]
});

console.log(`Found ${results.length} records`);
```

**Arguments:**

- `documentqueries` (array, required): Array of query objects (usually one)
  - `collection` (string): Collection name
  - `query` (object): MongoDB query filter
  - `options` (object, optional): Query options
    - `limit` (number): Max number of results
    - `sort` (object): Sort order (e.g., `{ createdAt: -1 }` for descending)
    - `projection` (object): Fields to include (e.g., `{ name: 1, email: 1 }`)
    - `skip` (number): Number of records to skip (for pagination)

**Returns:** Array of matching records

**Query Examples:**

```javascript
// Simple equality
query: { status: "active" }

// Multiple conditions (AND)
query: { role: "admin", status: "active" }

// OR conditions
query: { $or: [{ role: "admin" }, { role: "moderator" }] }

// Comparison operators
query: { age: { $gte: 18, $lt: 65 } }

// Array contains
query: { tags: { $in: ["javascript", "nodejs"] } }

// Regex pattern matching
query: { email: { $regex: ".*@example.com$" } }

// Nested fields
query: { "address.city": "New York" }
```

---

#### updateRecord

Update a record by ID (replaces specified fields).

```javascript
const updated = await smriti.db.updateRecord({
    collection: "users",
    id: "507f1f77bcf86cd799439011",
    document: {
        status: "inactive",
        lastModified: new Date().toISOString()
    }
});

console.log('Updated record:', updated);
```

**Arguments:**

- `collection` (string, required): Collection name
- `id` (string, required): Record ID
- `document` (object, required): Fields to update (merges with existing record)

**Returns:** Updated record

**Note:** This performs a partial update - only specified fields are changed.

---

#### updateRecordByField

Update multiple records matching a field value.

```javascript
const result = await smriti.db.updateRecordByField({
    collection: "users",
    field: "role",
    value: "guest",
    data: {
        permissions: ["read"],
        updatedAt: new Date().toISOString()
    }
});

console.log(`Updated ${result.modifiedCount} records`);
```

**Arguments:**

- `collection` (string, required): Collection name
- `field` (string, required): Field name to match
- `value` (any, required): Field value to match
- `data` (object, required): Update data

**Returns:** Update result with `modifiedCount` and `matchedCount`

---

#### deleteRecord

Delete a record by ID.

```javascript
await smriti.db.deleteRecord({
    collection: "users",
    id: "507f1f77bcf86cd799439011"
});

console.log('Record deleted');
```

**Arguments:**

- `collection` (string, required): Collection name
- `id` (string, required): Record ID

**Returns:** Deletion result `{ acknowledged: true, deletedCount: 1 }`

---

#### queryVectorHybrid

Hybrid search combining vector similarity and metadata filters.

```javascript
// First, you need a query vector (embedding)
const queryVector = [0.1, 0.2, 0.3, /* ... 1536 dimensions */];

const results = await smriti.db.queryVectorHybrid({
    collection: "documents",
    vector: queryVector,
    metadataQuery: { 
        category: "technical",
        status: "published"
    },
    vectorweight: 0.7,      // 70% weight on vector similarity
    metadataweight: 0.3,    // 30% weight on metadata match
    topk: 10
});

results.forEach(doc => {
    console.log(`${doc.title} - Score: ${doc.score}`);
});
```

**Arguments:**

- `collection` (string, required): Collection name
- `vector` (array, required): Query embedding vector (must match collection's vector dimension)
- `metadataQuery` (object, optional): MongoDB-style filter for metadata
- `vectorweight` (number, optional): Weight for vector similarity (0-1, default: 0.5)
- `metadataweight` (number, optional): Weight for metadata match (0-1, default: 0.5)
- `topk` (number, optional): Number of results to return (default: 10)

**Returns:** Array of records sorted by hybrid score (descending), each with `score` field

**Use Cases:**

- Semantic search with category filters
- Find similar documents within a specific date range
- Search knowledge base with access control filters

---

#### freeSearch

Natural language search using automatic embedding generation.

```javascript
const results = await smriti.db.freeSearch({
    collection: "knowledge_base",
    query: "How do I reset my password?"
});

results.forEach(article => {
    console.log(`${article.title} - Relevance: ${article.score}`);
});
```

**Arguments:**

- `collection` (string, required): Collection name (must have vector embeddings)
- `query` (string, required): Natural language query

**Returns:** Array of relevant records with similarity scores

**How it works:**

1. Platform generates embedding for the query text
2. Performs vector similarity search
3. Returns top matching documents

**Note:** Collection records must have vector embeddings. Use `prajna.embedding.generate()` to create embeddings when storing documents.

---

#### llmFeedback

Record feedback for LLM responses (for model fine-tuning and quality monitoring).

```javascript
await smriti.db.llmFeedback({
    payload: {
        sessionId: context.session,
        prompt: "What is the capital of France?",
        response: "The capital of France is Paris.",
        rating: 5,
        feedback: "Accurate and concise answer"
    }
});
```

**Arguments:**

- `payload` (object, required): Feedback data
  - `sessionId` (string): Conversation session ID
  - `prompt` (string): The user's input prompt
  - `response` (string): The LLM's response
  - `rating` (number, optional): Numeric rating (e.g., 1-5)
  - `feedback` (string, optional): Text feedback

**Returns:** Feedback record ID

---

### Vector Module (`smriti.vector`)

Dedicated vector operations for high-performance similarity search. Use this for pure vector operations without metadata.

#### createCollection

Create a vector collection with specified dimensions.

```javascript
await smriti.vector.createCollection({
    collection: "embeddings",
    vectorSize: 1536  // OpenAI text-embedding-3-small
});
```

**Arguments:**

- `collection` (string, required): Collection name
- `vectorSize` (number, required): Vector dimension

**Common Vector Sizes:**

- OpenAI `text-embedding-3-small`: 1536
- OpenAI `text-embedding-3-large`: 3072
- OpenAI `text-embedding-ada-002`: 1536

---

#### insert

Insert a single vector with optional metadata.

```javascript
await smriti.vector.insert({
    collection: "embeddings",
    vector: [0.1, 0.2, 0.3, /* ... */],
    metadata: {
        documentId: "doc-123",
        title: "Product Overview",
        source: "website"
    }
});
```

**Arguments:**

- `collection` (string, required): Collection name
- `vector` (array, required): Embedding vector (must match `vectorSize`)
- `metadata` (object, optional): Associated metadata

**Returns:** Insert result with vector ID

---

#### bulkInsert

Insert multiple vectors in a single operation (more efficient than individual inserts).

```javascript
await smriti.vector.bulkInsert({
    collection: "embeddings",
    records: [
        {
            vector: [0.1, 0.2, /* ... */],
            metadata: { id: "doc-1", title: "First Document" }
        },
        {
            vector: [0.3, 0.4, /* ... */],
            metadata: { id: "doc-2", title: "Second Document" }
        }
    ]
});
```

**Arguments:**

- `collection` (string, required): Collection name
- `records` (array, required): Array of vector records
  - `vector` (array): Embedding vector
  - `metadata` (object, optional): Associated metadata

**Returns:** Bulk insert result with count

---

#### query

Find similar vectors using cosine similarity.

```javascript
const results = await smriti.vector.query({
    collection: "embeddings",
    vector: queryVector,
    top_k: 5
});

results.forEach(result => {
    console.log(`ID: ${result.id}, Score: ${result.score}`);
    console.log(`Metadata:`, result.metadata);
});
```

**Arguments:**

- `collection` (string, required): Collection name
- `vector` (array, required): Query vector
- `top_k` (number, optional): Number of results (default: 10)

**Returns:** Array of similar vectors with:

- `id`: Vector ID
- `score`: Similarity score (0-1, higher = more similar)
- `metadata`: Associated metadata
- `vector`: The stored vector (optional)

---

### Secrets Module (`smriti.secrets`)

Secure secrets management using AWS Secrets Manager.

#### set

Store a new secret.

```javascript
await smriti.secrets.set({
    key: "openai-api-key",
    value: "sk-...",
    description: "OpenAI API key for production",
    tags: {
        environment: "production",
        service: "llm"
    }
});
```

**Arguments:**

- `key` (string, required): Secret identifier (unique name)
- `value` (string, required): Secret value
- `description` (string, optional): Human-readable description
- `tags` (object, optional): Key-value tags for organization
- `servicetype` (string, optional): Backend service (default: "AwsSecretsManager")

**Returns:** Secret creation result

---

#### get

Retrieve a secret value.

```javascript
const secret = await smriti.secrets.get({
    key: "openai-api-key"
});

const apiKey = secret.value;
console.log('Secret retrieved');
```

**Arguments:**

- `key` (string, required): Secret identifier
- `servicetype` (string, optional): Backend service

**Returns:** Secret object with:

- `value`: Secret value (string)
- `description`: Description
- `tags`: Associated tags
- `createdAt`: Creation timestamp
- `updatedAt`: Last update timestamp

**Security Note:** Never log secret values to console in production.

---

#### update

Update an existing secret.

```javascript
await smriti.secrets.update({
    key: "openai-api-key",
    value: "sk-new-value",
    description: "Updated OpenAI key"
});
```

**Arguments:**

- `key` (string, required): Secret identifier
- `value` (string, optional): New secret value
- `description` (string, optional): Updated description
- `tags` (object, optional): Updated tags
- `servicetype` (string, optional): Backend service

**Returns:** Update result

---

#### delete

Delete a secret.

```javascript
await smriti.secrets.delete({
    key: "old-api-key"
});
```

**Arguments:**

- `key` (string, required): Secret identifier
- `servicetype` (string, optional): Backend service

**Returns:** Deletion result

---

#### checkAvailability

Check if a secret exists without retrieving its value.

```javascript
const exists = await smriti.secrets.checkAvailability({
    key: "openai-api-key"
});

if (exists.available) {
    console.log('Secret exists');
} else {
    console.log('Secret not found');
}
```

**Arguments:**

- `key` (string, required): Secret identifier
- `servicetype` (string, optional): Backend service

**Returns:** `{ available: boolean }`

---

## Prajna Service (LLM Layer)

Prajna provides LLM interactions, embeddings generation, and chat orchestration. Access via `prajna.llm`, `prajna.embedding`, and `prajna.chat` modules.

### LLM Module (`prajna.llm`)

Direct LLM interactions with optional structured outputs.

#### ask

Ask the LLM a question with optional context and file attachments.

```javascript
import { prajna } from '/runtime/runtime-sdks/prajna.js';

const response = await prajna.llm.ask({
    question: "What are the benefits of using TypeScript?",
    context: "You are a senior software engineer explaining concepts to junior developers.",
    fileIds: [] // Optional file attachments
});

console.log('LLM Response:', response.answer);
```

**Arguments:**

- `question` (string, required): The user's question
- `context` (string, optional): Additional context to guide the LLM
- `fileIds` (array, optional): Array of file IDs to include as context

**Returns:** Object with:

- `answer` (string): The LLM's response
- `usage` (object): Token usage statistics

---

#### askStructured

Ask the LLM and get a structured JSON response validated against a schema.

```javascript
const schema = {
    type: "object",
    properties: {
        name: { type: "string" },
        age: { type: "number" },
        email: { type: "string", format: "email" },
        skills: {
            type: "array",
            items: { type: "string" }
        }
    },
    required: ["name", "email"]
};

const result = await prajna.llm.askStructured({
    question: "Extract user information from this text: John Doe, 30 years old, contact at john@example.com, knows JavaScript and Python",
    schema: schema,
    context: "Extract structured data from unstructured text"
});

console.log('Structured Data:', result.data);
// { name: "John Doe", age: 30, email: "john@example.com", skills: ["JavaScript", "Python"] }
```

**Arguments:**

- `question` (string, required): The extraction/transformation prompt
- `schema` (object, required): JSON Schema definition for the expected output
- `context` (string, optional): Additional context
- `fileIds` (array, optional): File IDs for context

**Returns:** Object with:

- `data` (object): Structured data matching the schema
- `usage` (object): Token usage

**Use Cases:**

- Data extraction from unstructured text
- Form field population from natural language
- Converting documents to structured formats
- Parsing complex information into databases

**Schema Examples:**

```javascript
// Simple object
{
    type: "object",
    properties: {
        name: { type: "string" },
        age: { type: "number" }
    },
    required: ["name"]
}

// Array of objects
{
    type: "array",
    items: {
        type: "object",
        properties: {
            productId: { type: "string" },
            quantity: { type: "number" }
        }
    }
}

// Nested structure
{
    type: "object",
    properties: {
        user: {
            type: "object",
            properties: {
                name: { type: "string" },
                address: {
                    type: "object",
                    properties: {
                        city: { type: "string" },
                        country: { type: "string" }
                    }
                }
            }
        }
    }
}
```

---

#### askWithFiles

Ask the LLM with file attachments (documents, images, etc.).

```javascript
const response = await prajna.llm.askWithFiles({
    question: "Summarize the key points from the attached document",
    fileIds: ["file-id-1", "file-id-2"],
    context: "Provide a concise summary in bullet points"
});

console.log('Summary:', response.answer);
```

**Arguments:**

- `question` (string, required): The question
- `fileIds` (array, required): Array of file IDs (uploaded documents/images)
- `context` (string, optional): Additional context

**Returns:** Object with:

- `answer` (string): LLM response
- `usage` (object): Token usage

**Supported File Types:** PDF, DOCX, TXT, images (PNG, JPG), etc.

---

### Embedding Module (`prajna.embedding`)

Generate vector embeddings for text content.

#### generate

Generate embeddings for text content and optionally store in a collection.

```javascript
import { prajna } from '/runtime/runtime-sdks/prajna.js';

// Generate and store embeddings
const result = await prajna.embedding.generate({
    content: "This is a sample document about machine learning and artificial intelligence.",
    collectionName: "knowledge_base",
    metadata: {
        title: "ML Overview",
        category: "technology",
        author: "John Doe"
    },
    chunkSize: 500,
    overlap: 50,
    returnEmbedding: true
});

console.log('Embedding dimensions:', result.embedding.length);
```

**Arguments:**

- `content` (string, required): Text content to embed
- `collectionName` (string, required): Collection to store embeddings
- `metadata` (object, optional): Metadata to store with embeddings
- `chunkSize` (number, optional): Size of text chunks (for long documents)
- `overlap` (number, optional): Overlap between chunks
- `returnEmbedding` (boolean, optional): Return the embedding vector (default: false)
- `asyncProcessing` (boolean, optional): Process asynchronously (default: false)

**Returns:** Object with:

- `success` (boolean): Operation status
- `embedding` (array, optional): The embedding vector (if `returnEmbedding: true`)
- `chunks` (number): Number of chunks created

**How Chunking Works:**

For long documents, the text is split into overlapping chunks:

- **chunkSize**: Maximum characters per chunk
- **overlap**: Characters shared between consecutive chunks (maintains context)

Example:

```
Document: "ABCDEFGHIJ" (10 chars)
chunkSize: 5, overlap: 2
Chunks: ["ABCDE", "CDEFG", "EFGHIJ"]
```

**Use Cases:**

- Indexing documents for semantic search
- Building knowledge bases
- Creating chatbot context databases
- Document similarity analysis

---

### Chat Module (`prajna.chat`)

Orchestrate multi-agent conversations and chat workflows.

#### validateChatRequest

Validate a chat request and prepare it for processing.

```javascript
const validation = await prajna.chat.validateChatRequest({
    chatId: "chat-123",
    sessionId: "session-456",
    question: "What is the status of my order?",
    attachments: [
        { type: "image", url: "https://..." }
    ]
});

console.log('Document queries:', validation.documentQueries);
```

**Arguments:**

- `chatId` (string, required): Chat identifier
- `sessionId` (string, required): Session identifier
- `question` (string, required): User's question
- `attachments` (array, optional): File attachments

**Returns:** Object with:

- `documentQueries` (array): Queries for Smriti to fetch context
- `valid` (boolean): Validation status

---

#### validateGeneralChatRequest

Validate a general chat request with multi-agent support.

```javascript
const validation = await prajna.chat.validateGeneralChatRequest({
    chatId: "chat-123",
    sessionId: "session-456",
    question: "Generate a report and send it via email",
    agents: ["report-generator", "email-sender"]
});
```

**Arguments:**

- `chatId` (string, required): Chat identifier
- `sessionId` (string, required): Session identifier
- `question` (string, required): User's question
- `attachments` (array, optional): File attachments
- `agents` (array, optional): Specific agents to use

**Returns:** Validation result with document queries

---

#### composeSteps

Orchestrate a multi-step conversation flow (agent task decomposition).

```javascript
const steps = await prajna.chat.composeSteps([
    chatData,
    sessionData,
    historyData,
    agentConfigs
]);

console.log('Execution steps:', steps.tasks);
```

**Arguments:**

- `payload` (array, required): Array of query results from Smriti
  - Chat data
  - Session data
  - History data
  - Agent configurations
- `correlationId` (string, optional): Correlation ID for tracking

**Returns:** Object with:

- `tasks` (array): Array of tasks to execute
- `agents` (array): Agents involved

---

#### composeAnswer

Compose final answer after all agent tasks are completed.

```javascript
const finalAnswer = await prajna.chat.composeAnswer({
    question: context.user_message,
    context: "Agent results: ...",
    session: context.session,
    history: context.history,
    agent: context.assigned_agent,
    usage: { prompt_tokens: 100, completion_tokens: 50 }
});

console.log('Final answer:', finalAnswer.answer);
```

**Arguments:**

- `question` (string, required): Original user question
- `context` (string, required): Agent execution results
- `session` (string, required): Session ID
- `history` (array, optional): Conversation history
- `agent` (string, optional): Agent slug
- `usage` (object, optional): Token usage

**Returns:** Object with:

- `answer` (string): Final composed answer
- `usage` (object): Total token usage

---

#### guardRails

Execute guardrails validation on user input.

```javascript
const guardResult = await prajna.chat.guardRails([
    chatData,
    sessionData,
    historyData,
    agentConfigs
]);

if (!guardResult.allowed) {
    console.log('Request blocked:', guardResult.reason);
}
```

**Arguments:**

- `payload` (array, required): Array of query results from Smriti

**Returns:** Object with:

- `allowed` (boolean): Whether request is allowed
- `reason` (string, optional): Reason if blocked

---

## Kriya Service (Tool Execution Engine)

Kriya manages agents, tools, and assistants. Access via `kriya.agent`, `kriya.assistant`, and `kriya.tool` modules.

### Agent Module (`kriya.agent`)

Manage agents and agent configurations.

#### getAgentCard

Get agent card information for display.

```javascript
import { kriya } from '/runtime/runtime-sdks/kriya.js';

const agentCard = await kriya.agent.getAgentCard("code-generator", {
    includeSkills: "true"
});

console.log('Agent:', agentCard.name);
console.log('Skills:', agentCard.skills);
```

**Arguments:**

- `agentSlug` (string, required): Agent slug identifier
- `queryParams` (object, optional): Query parameters
  - `includeSkills`: Include skills in response

**Returns:** Agent card object with metadata

---

#### getAgentDetails

Get detailed agent information.

```javascript
const details = await kriya.agent.getAgentDetails(
    "personal",           // type: "personal" | "marketplace"
    "code-generator",     // agent slug
    "user-123"           // user ID
);

console.log('Agent details:', details);
```

**Arguments:**

- `typeParam` (string, required): Agent type ("personal" or "marketplace")
- `agent` (string, required): Agent slug
- `userId` (string, required): User ID

**Returns:** Detailed agent object

---

#### create

Create a new agent.

```javascript
const newAgent = await kriya.agent.create({
    name: "Custom Code Generator",
    slug: "custom-code-gen",
    description: "Generates custom code snippets",
    systemInstructions: [
        "You are a code generation expert",
        "Generate clean, well-documented code"
    ],
    skills: ["tool-id-1", "tool-id-2"],
    version: "1.0",
    createdBy: "user-123",
    managedBy: ["user-123"],
    admins: ["user-123"],
    icon: "https://...",
    is_public: false,
    roles: ["developer"],
    guardrailsContext: "Only generate code in JavaScript, Python, or TypeScript",
    guardrailsViolationFallback: "I can only help with JavaScript, Python, or TypeScript code"
});

console.log('Created agent ID:', newAgent.id);
```

**Arguments:**

- `name` (string, required): Agent display name
- `slug` (string, required): Unique slug identifier
- `description` (string, required): Agent description
- `systemInstructions` (array, required): Array of instruction strings
- `skills` (array, required): Array of tool IDs
- `version` (string, required): Version number
- `createdBy` (string, required): Creator user ID
- `managedBy` (array, required): Array of manager user IDs
- `admins` (array, required): Array of admin user IDs
- `icon` (string, optional): Icon URL
- `is_public` (boolean, optional): Public visibility
- `roles` (array, optional): Allowed roles
- `guardrailsContext` (string, optional): Guardrails context
- `guardrailsViolationFallback` (string, optional): Fallback message

**Returns:** Created agent object with ID

---

#### update

Update an existing agent.

```javascript
const updated = await kriya.agent.update({
    id: "agent-id-123",
    name: "Updated Agent Name",
    description: "Updated description",
    skills: ["tool-1", "tool-2", "tool-3"], // Updated skills
    systemInstructions: ["New instruction 1", "New instruction 2"]
    // ... other fields
});
```

**Arguments:** Same as `create`, plus:

- `id` (string, required): Agent ID to update

**Returns:** Updated agent object

---

### Assistant Module (`kriya.assistant`)

Manage assistants (multi-agent orchestrators).

#### create

Create a new assistant.

```javascript
const assistant = await kriya.assistant.create({
    name: "Customer Support Assistant",
    slug: "customer-support",
    description: "Handles customer inquiries",
    systemContext: "You assist customers with orders, returns, and product questions",
    status: "active",
    visibility: "private",
    owner: "user-123",
    type: "support",
    is_public: false,
    roles: ["support-agent"],
    agents: ["agent-id-1", "agent-id-2"],
    managedBy: ["user-123"],
    guardrailsContext: "Only handle customer support queries",
    guardrailsViolationFallback: "I can only help with customer support questions",
    welcomeMessage: "Hello! How can I help you today?",
    welcomeDescription: "Your customer support assistant"
});

console.log('Created assistant:', assistant.id);
```

**Arguments:**

- `name` (string, required): Assistant name
- `slug` (string, required): Unique slug
- `description` (string, required): Description
- `systemContext` (string, required): System context
- `status` (string, required): Status ("active", "inactive")
- `visibility` (string, required): Visibility ("public", "private")
- `owner` (string, required): Owner user ID
- `type` (string, required): Assistant type
- `is_public` (boolean, optional): Public flag
- `roles` (array, optional): Allowed roles
- `agents` (array, required): Array of agent IDs
- `managedBy` (array, optional): Manager user IDs
- `guardrailsContext` (string, optional): Guardrails context
- `guardrailsViolationFallback` (string, optional): Fallback message
- `welcomeMessage` (string, optional): Welcome message
- `welcomeDescription` (string, optional): Welcome description

**Returns:** Created assistant object

---

#### update

Update an existing assistant.

```javascript
const updated = await kriya.assistant.update({
    id: "assistant-id-123",
    name: "Updated Assistant",
    agents: ["agent-1", "agent-2", "agent-3"],
    // ... other fields
});
```

**Arguments:** Same as `create`, plus:

- `id` (string, required): Assistant ID to update

**Returns:** Updated assistant object

---

### Tool Module (`kriya.tool`)

Manage tools (skills that agents use).

#### create

Create a new tool.

```javascript
const tool = await kriya.tool.create({
    name: "Data Transformer",
    description: "Transforms data between formats",
    tags: ["data", "transformation"],
    examples: ["Convert JSON to CSV", "Transform XML to JSON"],
    systemInstructions: [
        "Transform data accurately",
        "Preserve all data fields"
    ],
    input_modes: ["application/json"],
    output_modes: ["application/json"],
    version: "1.0",
    type: "FaaS",
    code: handlerCode, // Your handler function as string
    arguments: {
        inputFormat: {
            type: "string",
            required: true,
            description: "Input data format"
        },
        outputFormat: {
            type: "string",
            required: true,
            description: "Output data format"
        }
    },
    createdBy: "user-123",
    managedBy: ["user-123"],
    package_json: JSON.stringify({
        name: "data-transformer",
        version: "1.0.0",
        type: "module",
        dependencies: {
            "lodash": "^4.17.21"
        }
    })
});

console.log('Created tool:', tool.id);
```

**Arguments:**

- `name` (string, required): Tool name
- `description` (string, required): Tool description
- `tags` (array, optional): Tags for organization
- `examples` (array, optional): Usage examples
- `systemInstructions` (array, required): Instructions for agents
- `input_modes` (array, required): Accepted input MIME types
- `output_modes` (array, required): Output MIME types
- `version` (string, required): Version number
- `type` (string, required): Tool type ("JS", "MCP", "FaaS")
- `code` (string, required): Handler code
- `arguments` (object, required): Tool arguments schema
- `createdBy` (string, required): Creator user ID
- `managedBy` (array, optional): Manager user IDs
- `package_json` (string, optional): package.json as string (for FaaS tools)

**Returns:** Created tool object with ID

---

#### update

Update an existing tool.

```javascript
const updated = await kriya.tool.update({
    id: "tool-id-123",
    name: "Updated Tool",
    code: updatedHandlerCode,
    version: "1.1",
    // ... other fields
});
```

**Arguments:** Same as `create`, plus:

- `id` (string, required): Tool ID to update
- `functionId` (string, optional): Function ID (for FaaS)
- `statusMessage` (string, optional): Status message

**Returns:** Updated tool object

---

## Complete Examples

### Example 1: User Data Lookup with Error Handling

```javascript
import { smriti } from '/runtime/runtime-sdks/smriti.js';

async function handler(event) {
    const context = event.context;
    
    try {
        // Validate input
        const { userId, email } = context.input;
        
        if (!userId && !email) {
            return {
                success: false,
                error: 'Either userId or email is required'
            };
        }
        
        // Build query
        const query = userId 
            ? { userId: userId }
            : { email: email };
        
        // Query database
        const users = await smriti.db.queryRecords({
            documentqueries: [{
                collection: "users",
                query: query,
                options: { limit: 1 }
            }]
        });
        
        if (!users || users.length === 0) {
            return {
                success: true,
                found: false,
                message: 'User not found'
            };
        }
        
        const user = users[0];
        
        // Return user data (exclude sensitive fields)
        return {
            success: true,
            found: true,
            user: {
                id: user._id,
                name: user.name,
                email: user.email,
                role: user.role,
                status: user.status
                // Don't include password or sensitive data
            }
        };
        
    } catch (error) {
        console.error('User lookup error:', error);
        return {
            success: false,
            error: error.message,
            errorType: 'DatabaseError'
        };
    }
}

export default handler;
```

---

### Example 2: Semantic Search with LLM Enhancement

```javascript
import { smriti } from '/runtime/runtime-sdks/smriti.js';
import { prajna } from '/runtime/runtime-sdks/prajna.js';

async function handler(event) {
    const context = event.context;
    
    try {
        const { query, limit = 5 } = context.input;
        
        if (!query) {
            return { success: false, error: 'Query is required' };
        }
        
        // Step 1: Perform semantic search
        const searchResults = await smriti.db.freeSearch({
            collection: "knowledge_base",
            query: query
        });
        
        // Step 2: Take top results
        const topResults = searchResults.slice(0, limit);
        
        if (topResults.length === 0) {
            return {
                success: true,
                results: [],
                message: 'No relevant documents found'
            };
        }
        
        // Step 3: Enhance with LLM summary
        const documentsText = topResults
            .map((doc, i) => `Document ${i + 1}: ${doc.title}\n${doc.content}`)
            .join('\n\n');
        
        const llmResponse = await prajna.llm.ask({
            question: `Based on these documents, answer the user's question: "${query}"`,
            context: `Documents:\n${documentsText}`
        });
        
        return {
            success: true,
            answer: llmResponse.answer,
            sources: topResults.map(doc => ({
                title: doc.title,
                score: doc.score,
                id: doc._id
            })),
            usage: llmResponse.usage
        };
        
    } catch (error) {
        console.error('Search error:', error);
        return {
            success: false,
            error: error.message
        };
    }
}

export default handler;
```

---

### Example 3: Structured Data Extraction from Text

```javascript
import { prajna } from '/runtime/runtime-sdks/prajna.js';
import { smriti } from '/runtime/runtime-sdks/smriti.js';

async function handler(event) {
    const context = event.context;
    
    try {
        const { text, documentType } = context.input;
        
        // Define schema based on document type
        const schemas = {
            invoice: {
                type: "object",
                properties: {
                    invoiceNumber: { type: "string" },
                    date: { type: "string" },
                    vendor: { type: "string" },
                    items: {
                        type: "array",
                        items: {
                            type: "object",
                            properties: {
                                description: { type: "string" },
                                quantity: { type: "number" },
                                price: { type: "number" }
                            }
                        }
                    },
                    total: { type: "number" }
                },
                required: ["invoiceNumber", "vendor", "total"]
            },
            resume: {
                type: "object",
                properties: {
                    name: { type: "string" },
                    email: { type: "string" },
                    phone: { type: "string" },
                    skills: {
                        type: "array",
                        items: { type: "string" }
                    },
                    experience: {
                        type: "array",
                        items: {
                            type: "object",
                            properties: {
                                company: { type: "string" },
                                position: { type: "string" },
                                duration: { type: "string" }
                            }
                        }
                    }
                },
                required: ["name", "email"]
            }
        };
        
        const schema = schemas[documentType];
        
        if (!schema) {
            return {
                success: false,
                error: `Unknown document type: ${documentType}`
            };
        }
        
        // Extract structured data
        const extraction = await prajna.llm.askStructured({
            question: `Extract information from this ${documentType}:\n\n${text}`,
            schema: schema,
            context: `Extract all relevant fields. Return null for missing fields.`
        });
        
        // Store extracted data
        const record = await smriti.db.createRecord({
            collection: `extracted_${documentType}s`,
            payload: {
                ...extraction.data,
                originalText: text,
                extractedAt: new Date().toISOString(),
                sessionId: context.session
            }
        });
        
        return {
            success: true,
            data: extraction.data,
            recordId: record._id,
            message: `Successfully extracted ${documentType} data`
        };
        
    } catch (error) {
        console.error('Extraction error:', error);
        return {
            success: false,
            error: error.message
        };
    }
}

export default handler;
```

---

### Example 4: Multi-Service Integration with Secrets

```javascript
import { smriti } from '/runtime/runtime-sdks/smriti.js';
import { prajna } from '/runtime/runtime-sdks/prajna.js';
const axios = require('axios');

async function handler(event) {
    const context = event.context;
    
    try {
        const { action, data } = context.input;
        
        // Step 1: Retrieve API key from secrets
        const apiKeySecret = await smriti.secrets.get({
            key: "external-api-key"
        });
        
        const apiKey = apiKeySecret.value;
        
        // Step 2: Call external API
        const apiResponse = await axios.post(
            'https://api.external-service.com/process',
            data,
            {
                headers: {
                    'Authorization': `Bearer ${apiKey}`,
                    'Content-Type': 'application/json'
                }
            }
        );
        
        // Step 3: Generate embedding for the response
        await prajna.embedding.generate({
            content: JSON.stringify(apiResponse.data),
            collectionName: "api_responses",
            metadata: {
                action: action,
                source: "external-api",
                timestamp: new Date().toISOString(),
                sessionId: context.session
            },
            chunkSize: 1000,
            returnEmbedding: false
        });
        
        // Step 4: Store in database
        const record = await smriti.db.createRecord({
            collection: "api_transactions",
            payload: {
                action: action,
                request: data,
                response: apiResponse.data,
                status: apiResponse.status,
                timestamp: new Date().toISOString(),
                userId: context.roc_user_session?.userId
            }
        });
        
        return {
            success: true,
            data: apiResponse.data,
            transactionId: record._id,
            message: 'API call successful and data stored'
        };
        
    } catch (error) {
        console.error('Integration error:', error);
        
        // Enhanced error handling
        if (error.response) {
            // API returned error
            return {
                success: false,
                error: `API error: ${error.response.status}`,
                details: error.response.data
            };
        } else if (error.message.includes('Secret not found')) {
            // Secret retrieval failed
            return {
                success: false,
                error: 'Configuration error: API key not found'
            };
        } else {
            // Generic error
            return {
                success: false,
                error: error.message
            };
        }
    }
}

export default handler;
```

---

### Example 5: Vector Search with Hybrid Filtering

```javascript
import { prajna } from '/runtime/runtime-sdks/prajna.js';
import { smriti } from '/runtime/runtime-sdks/smriti.js';

async function handler(event) {
    const context = event.context;
    
    try {
        const { 
            query, 
            category, 
            dateFrom, 
            dateTo,
            limit = 10 
        } = context.input;
        
        // Step 1: Generate query embedding
        const embeddingResult = await prajna.embedding.generate({
            content: query,
            collectionName: "temp",  // Temporary collection
            returnEmbedding: true,   // Return the vector
            asyncProcessing: false
        });
        
        const queryVector = embeddingResult.embedding;
        
        // Step 2: Build metadata filter
        const metadataFilter = {};
        
        if (category) {
            metadataFilter.category = category;
        }
        
        if (dateFrom || dateTo) {
            metadataFilter.createdAt = {};
            if (dateFrom) metadataFilter.createdAt.$gte = dateFrom;
            if (dateTo) metadataFilter.createdAt.$lte = dateTo;
        }
        
        // Step 3: Hybrid search (vector + metadata)
        const results = await smriti.db.queryVectorHybrid({
            collection: "documents",
            vector: queryVector,
            metadataQuery: metadataFilter,
            vectorweight: 0.7,      // 70% semantic similarity
            metadataweight: 0.3,    // 30% metadata match
            topk: limit
        });
        
        // Step 4: Enhance results with LLM summary
        if (results.length === 0) {
            return {
                success: true,
                results: [],
                message: 'No documents found matching the criteria'
            };
        }
        
        const topDoc = results[0];
        const summary = await prajna.llm.ask({
            question: `Summarize this document in the context of the query: "${query}"`,
            context: `Document: ${topDoc.content}`
        });
        
        return {
            success: true,
            results: results.map(doc => ({
                id: doc._id,
                title: doc.title,
                score: doc.score,
                category: doc.category,
                excerpt: doc.content.substring(0, 200) + '...'
            })),
            topResultSummary: summary.answer,
            totalFound: results.length
        };
        
    } catch (error) {
        console.error('Hybrid search error:', error);
        return {
            success: false,
            error: error.message
        };
    }
}

export default handler;
```

---

## Summary

This guide covered:

1. ✅ **FaaS Overview** - When to use FaaS vs JS tools
2. ✅ **Handler Pattern** - Required function signature and structure
3. ✅ **Context Object** - All available context properties
4. ✅ **Error Handling** - Critical try-catch patterns
5. ✅ **NPM Modules** - How to use external packages
6. ✅ **Runtime SDKs** - Pre-configured clients for services
7. ✅ **Smriti Service** - Database, vector, and secrets operations
8. ✅ **Prajna Service** - LLM, embeddings, and chat orchestration
9. ✅ **Kriya Service** - Agent, assistant, and tool management
10. ✅ **Complete Examples** - Real-world integration patterns

### Key Takeaways

- **Always use try-catch** to prevent container crashes
- **Return structured responses** with `success` boolean
- **Use pre-configured SDKs** (`smriti`, `prajna`, `kriya`) for simplicity
- **Set `"type": "module"`** in package.json for ES6 imports
- **Access context via `event.context`** for all execution data
- **Log errors but don't expose secrets** in production

### Next Steps

1. Review the examples that match your use case
2. Set up your `package.json` with required dependencies
3. Write your handler with proper error handling
4. Test locally before pushing to the platform
5. Monitor execution logs for debugging

For questions or issues, refer to the VGen platform documentation or contact the development team.