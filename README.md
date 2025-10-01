# Autonomous AI Workflow System

A streamlined CLI-based workflow system that automates tasks across Gmail, Pipedrive CRM, and Calendly with intelligent hybrid processing combining deterministic logic and LLM capabilities.

## 🌟 Features

- **🤖 Hybrid Processing**: Combines deterministic pattern matching with LLM intelligence
- **📧 Smart Email System**: Step-by-step prompting for simple requests, auto-generation for complex ones
- **🛠️ Multi-Tool Integration**: Gmail, Pipedrive CRM, and Calendly integration
- **📄 Document Processing**: AI-powered summaries, bullet points, and content extraction
- **💾 Persistent Memory**: ChromaDB-based interaction history
- **📢 Real-time Notifications**: Live progress updates
- **🎯 Type Safety**: Fully typed interfaces with Pydantic models

## 🏗️ Architecture

The system uses a **hybrid approach** that combines the best of both worlds:

```
┌─────────────────────────────────────────────────────────────┐
│                    HYBRID SYSTEM                            │
├─────────────────────────────────────────────────────────────┤
│  Deterministic Logic        │        LLM Intelligence       │
│  ├─ Email field extraction  │  ├─ Document summarization    │
│  ├─ CRM data parsing        │  ├─ Content generation        │
│  ├─ One-at-a-time prompting │  ├─ Subject line creation     │
│  └─ Pattern matching        │  └─ Natural language processing│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Tool Agents   │    │   Memory Agent   │    │  Notifier Agent │
│ (Gmail/Pipedrive│    │   (ChromaDB)     │    │                 │
│   /Calendly)    │    │                  │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Core Components

1. **Hybrid Email System**: Deterministic extraction + LLM content generation
2. **Tool Agents**: Direct API integrations (Gmail, Pipedrive, Calendly)
3. **Memory Agent**: ChromaDB-based interaction storage
4. **Document Manager**: Smart file processing with LLM summaries
5. **Notifier Agent**: Progress updates and notifications

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- OpenAI API key (for LLM features)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Yashkalwar/autonomous_P1.git
   cd autonomous1
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables** in `.env`:
   ```env
   # OpenAI (Required for LLM features)
   OPENAI_API_KEY=your_openai_api_key
   
   # Gmail (Optional)
   GMAIL_SENDER=your_email@gmail.com
   GMAIL_AUTH_METHOD=app_password
   GMAIL_APP_PASSWORD=your_16_char_app_password
   
   # Pipedrive CRM (Optional)
   PIPEDRIVE_API_TOKEN=your_pipedrive_token
   PIPEDRIVE_DOMAIN=yourcompany.pipedrive.com
   
   # Calendly (Optional)
   CALENDLY_TOKEN=your_calendly_token
   CALENDLY_EVENT_TYPE_UUID=your_event_type_uuid
   CALENDLY_SCHEDULING_LINK=https://calendly.com/your-link
   ```

4. **Run the application**:
   ```bash
   python cli.py
   ```

## 📋 Usage Examples

### Simple Email (Step-by-Step)
```
💬 What can I help you with? I want to send an email
❓ Please provide the recipient email address: john@example.com
✅ Got recipient: john@example.com
❓ What should be the email subject? Meeting follow-up
✅ Got subject: Meeting follow-up
❓ What should be the email content? Thanks for the great meeting today!
✅ Got content (32 characters)
📧 [GMAIL] Email sent to john@example.com via SMTP
✅ Email sent to john@example.com
```

### Smart Document Processing
```
💬 What can I help you with? Send 5 bullet points from resume.txt to hr@company.com
❓ Please provide the recipient email address: hr@company.com
✅ Got recipient: hr@company.com
✅ Loaded content from resume.txt (2254 characters)
✅ Got processed content (245 characters)
📧 [GMAIL] Email sent to hr@company.com via SMTP
✅ Email sent to hr@company.com
```

### CRM Contact Management
```
💬 What can I help you with? Add contact to CRM
❓ Please provide the contact name: Sarah Johnson
✅ Got name: Sarah Johnson
❓ Please provide the contact email address: sarah@newclient.com
✅ Got email: sarah@newclient.com
✅ Contact 'Sarah Johnson' added to Pipedrive with email sarah@newclient.com
```

### Calendly Availability
```
💬 What can I help you with? Check my availability for tomorrow
📅 Available slots for 2024-01-16:
  1. 9:00 AM - 9:30 AM
  2. 2:00 PM - 2:30 PM
  3. 4:00 PM - 4:30 PM
🔗 Book via Calendly: https://calendly.com/your-link
```

## 🎛️ CLI Commands

- `help` - Show available commands and examples
- `status` - Display system status and component health
- `memory` - Show memory statistics and recent interactions
- `clear` - Clear the terminal screen
- `quit`/`exit`/`q` - Exit the application

## 📄 Document Processing Features

### Supported Formats
- `.txt`, `.md`, `.pdf`, `.doc`, `.docx`, `.json`, `.csv`

### Processing Types
- **Bullet Points**: `"5 bullet points from document.txt"`
- **Line Summaries**: `"3 line summary of report.md"`
- **General Summaries**: `"summary of meeting_notes.txt"`
- **Highlights**: `"key highlights from proposal.pdf"`
- **Brief Content**: `"brief overview of document"`

### Usage
1. Place documents in `./user_documents/` folder
2. Reference by filename: `"summary of resume.txt"`
3. Or use generic: `"bullet points from document"`

## 🔧 Configuration

### Environment Variables

**Required:**
- `OPENAI_API_KEY` - OpenAI API key for LLM features

**Optional (Gmail):**
- `GMAIL_SENDER` - Your Gmail address
- `GMAIL_AUTH_METHOD` - `app_password` or `oauth`
- `GMAIL_APP_PASSWORD` - 16-character app password
- `GMAIL_OAUTH_TOKEN_PATH` - Path to OAuth token file

**Optional (Pipedrive):**
- `PIPEDRIVE_API_TOKEN` - Pipedrive API token
- `PIPEDRIVE_DOMAIN` - Your Pipedrive domain

**Optional (Calendly):**
- `CALENDLY_TOKEN` - Calendly API token
- `CALENDLY_EVENT_TYPE_UUID` - Event type UUID
- `CALENDLY_SCHEDULING_LINK` - Your Calendly link

### Memory Storage

ChromaDB stores interaction history in `./chroma_db/`:
- User queries and responses
- Email content and metadata
- CRM interactions
- Timestamps and sentiment analysis

## 🛠️ Development

### Project Structure
```
autonomous1/
├── cli.py              # Main CLI interface (hybrid logic)
├── agents.py           # Notification agent (simplified)
├── tools.py            # Tool integrations (Gmail/Pipedrive/Calendly)
├── memory.py           # ChromaDB memory management
├── contracts.py        # Type definitions and data models
├── document_manager.py # Document processing utilities
├── llm.py             # OpenAI LLM client
├── config_store.py    # Configuration management
├── requirements.txt   # Python dependencies
└── user_documents/    # Document storage folder
```

### Key Design Principles

1. **Hybrid Approach**: Deterministic logic + LLM intelligence
2. **User-Friendly**: Step-by-step prompting for simple requests
3. **Smart Automation**: Auto-generation for complex document tasks
4. **Type Safety**: Pydantic models for data validation
5. **Modularity**: Clean separation of concerns
6. **Error Handling**: Graceful degradation and helpful messages

### Code Cleanup (Recent)

The codebase was recently streamlined:
- **Removed**: Old agent-based planning system (~800 lines)
- **Removed**: Unused review and deliberation agents
- **Simplified**: Direct LLM calls instead of complex orchestration
- **Improved**: Document processing with smart content generation
- **Result**: 46% code reduction while maintaining functionality

## 🔍 Troubleshooting

### Common Issues

1. **OpenAI API Errors**: Check your API key and credits
2. **Gmail Authentication**: Verify app password or OAuth setup
3. **Document Processing**: Ensure files are in `user_documents/` folder
4. **Memory Errors**: Check write permissions for `chroma_db/` directory

### Debug Tips

- Use `status` command to check component health
- Check `.env` file for correct variable names
- Verify file extensions are supported for document processing
- Test with simple requests first before complex ones

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with proper type hints
4. Test with different scenarios
5. Submit a pull request

## 📄 License

This project is provided as-is for educational and demonstration purposes.

## 🙏 Acknowledgments

- **OpenAI**: For GPT models powering the LLM features
- **ChromaDB**: For vector storage and memory capabilities
- **Rich**: For beautiful CLI formatting
- **Pydantic**: For robust data validation
