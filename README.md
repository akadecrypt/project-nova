# ObjectsAI - NOVA
## Nutanix Objects Virtual Assistant

**Hackathon XII Project**

| | |
|---|---|
| **Code** | D2761 |
| **Submitter** | Vignesh Chandrasekar |
| **Project URL** | https://nutanix.brightidea.com/D2761 |

---

An AI-powered chat interface for managing Nutanix Object Storage using natural language.

## Features

- **Natural Language Chat**: Talk to NOVA to manage buckets and objects
- **Bucket Operations**: Create, list, and manage S3-compatible buckets
- **Object Management**: Upload, list, and manage objects in buckets
- **SQL Analytics**: Query storage trends and statistics via natural language
- **Prism Central Integration**: Monitor object stores and fetch real-time stats
- **Chat History**: Persistent conversation history stored locally
- **Dynamic Context**: AI learns from markdown documentation files

## Architecture

```
nova-ui/
├── frontend/
│   ├── index.html          # Main chat interface
│   ├── settings.html       # Configuration page
│   └── css/
│       └── design-system.css
├── backend/
│   ├── run.py              # Entry point
│   ├── config.json         # All configuration (API keys, endpoints)
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py         # FastAPI application
│   │   ├── config.py       # Configuration loader
│   │   ├── context.py      # Context manager for AI
│   │   ├── models.py       # Pydantic models
│   │   ├── routers/        # API endpoints
│   │   └── tools/          # Tool implementations
│   ├── context/            # AI context markdown files
│   │   ├── system_prompt.md
│   │   ├── product_knowledge.md
│   │   ├── api_reference.md
│   │   └── ...
│   └── tools/
│       └── tools.json      # Tool definitions
├── start_server.sh         # Start both servers
└── README.md
```

## Quick Start

### 1. Configure Settings

Edit `backend/config.json` with your credentials:

```json
{
  "llm": {
    "provider": "nutanix-ai",
    "hackathon_api_key": "your-api-key",
    "base_url": "https://hkn12.ai.nutanix.com/enterpriseai/v1/",
    "model": "hack-reason"
  },
  "prism_central": {
    "ip": "10.x.x.x",
    "port": 9440,
    "username": "admin",
    "password": "your-password"
  },
  "s3": {
    "endpoint": "http://your-s3-endpoint:80",
    "access_key": "your-access-key",
    "secret_key": "your-secret-key",
    "region": "us-east-1"
  },
  "sql_agent": {
    "url": "http://sql-agent-host:9001/execute"
  }
}
```

### 2. Start the Servers

**Option A: Using start script (recommended)**
```bash
chmod +x start_server.sh
./start_server.sh
```

**Option B: Manual start**
```bash
# Terminal 1: Start backend
cd backend
pip install -r requirements.txt
python3 run.py

# Terminal 2: Start frontend
python3 -m http.server 8888
```

### 3. Open the UI

Navigate to `http://{your-ip}:8888` in your browser.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Check backend status |
| `/api/chat` | POST | Send message to NOVA |
| `/api/config/llm` | GET/POST | LLM configuration |
| `/api/config/prism` | GET/POST | Prism Central configuration |
| `/api/config/s3` | GET/POST | S3 configuration |
| `/api/context` | GET | List context files |
| `/api/context/{name}` | GET/PUT | Get/Update context |
| `/api/tools` | GET | List available tools |

## Available Tools

NOVA can perform these operations through natural language:

### S3 Operations
- **create_bucket** - Create a new S3 bucket
- **list_buckets** - List all buckets
- **list_objects** - List objects in a bucket
- **put_object** - Upload text content to a bucket
- **delete_object** - Delete an object
- **get_bucket_info** - Get bucket details

### Prism Central
- **get_object_stores** - List all object stores
- **fetch_object_store_stats_v4** - Get object store statistics

### Analytics
- **execute_sql** - Run SQL analytics queries
- **list_tables** - List database tables
- **get_table_schema** - Get table structure
- **get_database_summary** - Get database overview

## Example Commands

- "List all buckets"
- "Create a new bucket called my-data"
- "What objects are in bucket test-bucket?"
- "Show me storage growth over the last week"
- "Which buckets have the most objects?"
- "Get statistics for the object store"
- "What tables are in the database?"

## Requirements

- Python 3.8+
- Nutanix Hackathon AI API key (or OpenAI API key)
- Nutanix Objects (S3-compatible) endpoint
- Prism Central access (optional)
- SQL Agent (optional, for analytics)

## License

Internal Nutanix Hackathon Project.
