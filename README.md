# 🚀 NOVA - Nutanix Objects Virtual Assistant

<p align="center">
  <img src="https://img.shields.io/badge/Nutanix-Objects-blue?style=for-the-badge" />
  <img src="https://img.shields.io/badge/AI-Powered-purple?style=for-the-badge" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-green?style=for-the-badge" />
</p>

NOVA is an AI-powered assistant for managing Nutanix Objects storage. It provides a natural language interface for performing bucket operations, configuring lifecycle policies, viewing analytics, and more.

## ✨ Features

- 🤖 **Natural Language Interface** - Just tell NOVA what you want to do
- 🪣 **Bucket Management** - Create, list, delete buckets with versioning & WORM
- 📊 **Analytics Dashboard** - View storage usage and metrics
- ⏰ **Lifecycle Policies** - Configure automatic data archival and expiration
- 🔑 **Access Key Management** - Create and manage API credentials
- 🎨 **Beautiful UI** - Dark, Light, and Nutanix themes
- 📱 **Responsive Design** - Works on desktop and mobile

## 🏗️ Architecture

```
nova-ui/
├── index.html              # Main chat interface
├── object-browser.html     # File browser
├── buckets.html           # Bucket dashboard
├── settings.html          # Configuration (Prism IP, themes)
├── css/
│   └── design-system.css  # Shared styles & themes
├── backend/
│   ├── main.py            # FastAPI server
│   ├── config.py          # Configuration management
│   ├── requirements.txt   # Python dependencies
│   └── services/
│       ├── prism_client.py    # Nutanix Prism API client
│       ├── vector_db.py       # ChromaDB for RAG
│       └── chat_agent.py      # AI agent logic
└── start_backend.sh       # Startup script
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Node.js (optional, for serving frontend)
- Access to Nutanix Prism Central

### 1. Start the Backend

```bash
# Make the script executable
chmod +x start_backend.sh

# Run the backend
./start_backend.sh
```

Or manually:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### 2. Serve the Frontend

```bash
# Simple Python server
python3 -m http.server 8888

# Or use any static file server
npx serve .
```

### 3. Configure Prism Connection

1. Open http://localhost:8888
2. Go to **Settings** page
3. Enter your **Prism Central IP**, port, and credentials
4. Click **Test Connection**

## 🔧 Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
PRISM_IP=10.0.0.1
PRISM_PORT=9440
PRISM_USERNAME=admin
PRISM_PASSWORD=your-password
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Check backend status |
| `/api/chat` | POST | Send message to NOVA |
| `/api/config/prism` | GET/POST | Prism configuration |
| `/api/config/prism/test` | POST | Test Prism connection |
| `/api/objects/stores` | GET | List Object Stores |
| `/api/objects/buckets` | GET | List buckets |
| `/api/knowledge/stats` | GET | Vector DB stats |

## 💬 Example Commands

Try these with NOVA:

- "Create a bucket named prod-backups with versioning"
- "List all buckets"
- "Show storage statistics"
- "Set lifecycle policy for logs bucket to delete after 90 days"
- "Create access key for user admin"
- "Help"

## 🎨 Themes

NOVA includes three beautiful themes:

- **Dark** - Deep indigo/purple on dark background
- **Light** - Clean, minimal white theme
- **Nutanix** - Official Nutanix brand colors

## 📚 Vector Database

NOVA uses ChromaDB for:

- **Intent Recognition** - Understanding user commands
- **Knowledge Base** - Storing Nutanix Objects documentation
- **Conversation Context** - Remembering chat history

## 🔒 Security Notes

- Store credentials securely (use environment variables)
- The backend uses HTTPS when connecting to Prism
- API keys are only shown once when created
- Consider adding authentication for production use

## 🛠️ Development

### Running in Debug Mode

```bash
cd backend
NOVA_DEBUG=true python main.py
```

### Adding Custom Knowledge

```python
# Via API
POST /api/knowledge/add
{
    "documents": ["Your custom documentation here..."]
}
```

## 📄 License

MIT License - Built for Nutanix Hackathon 2026

---

<p align="center">
  <strong>NOVA</strong> - Intelligent Object Operations at Your Command
</p>
