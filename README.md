# NOVA - Nutanix Objects Virtual Assistant

An AI-powered chat interface for managing Nutanix Object Storage using natural language.

## Features

- **Natural Language Chat**: Talk to NOVA to manage buckets and objects
- **Bucket Operations**: Create, list, and manage S3-compatible buckets
- **Object Management**: Upload, list, and manage objects in buckets
- **SQL Analytics**: Query storage trends and statistics via natural language
- **Chat History**: Persistent conversation history stored locally

## Architecture

```
nova-ui/
├── index.html          # Main chat interface
├── settings.html       # Configuration page
├── css/
│   └── design-system.css
├── backend/
│   ├── main.py         # FastAPI backend with OpenAI integration
│   ├── requirements.txt
│   └── .env           # Configuration (API keys, endpoints)
└── start_server.sh    # Start both servers
```

## Quick Start

### 1. Configure Environment

Edit `backend/.env` with your credentials:

```env
OPENAI_API_KEY=sk-your-openai-key
NUTANIX_S3_ENDPOINT=http://your-s3-endpoint:80
NUTANIX_ACCESS_KEY=your-access-key
NUTANIX_SECRET_KEY=your-secret-key
SQL_AGENT_URL=http://sql-agent-host:9001/execute  # Optional
```

### 2. Start the Servers

**Option A: Using start script**
```bash
./start_server.sh
```

**Option B: Manual start**
```bash
# Terminal 1: Start backend
cd backend
pip install -r requirements.txt
python3 main.py

# Terminal 2: Start frontend
python3 -m http.server 8888
```

### 3. Open the UI

Navigate to `http://localhost:8888` in your browser.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Check backend status |
| `/api/chat` | POST | Send message to NOVA |
| `/api/chat/sessions` | GET | List chat sessions |
| `/api/chat/sessions/{id}` | GET | Get session messages |
| `/api/chat/sessions/{id}` | DELETE | Delete session |
| `/api/config/s3` | GET | Get S3 config status |
| `/api/objects/stats` | GET | Get bucket statistics |

## Available Tools

NOVA can perform these operations through natural language:

1. **create_bucket** - Create a new S3 bucket
2. **list_buckets** - List all buckets
3. **list_objects** - List objects in a bucket
4. **put_object** - Upload text content to a bucket
5. **execute_sql** - Run analytics queries (requires SQL agent)

## Example Commands

- "List all buckets"
- "Create a new bucket called my-data"
- "What objects are in bucket test-bucket?"
- "Show me storage growth over the last week"
- "Which buckets have the most objects?"

## Requirements

- Python 3.8+
- OpenAI API key
- Nutanix Objects (S3-compatible) endpoint

## License

Internal Nutanix tool.
