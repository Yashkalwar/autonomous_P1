# CrewAI Agent Workflow System

A sophisticated CLI-based agent workflow system built with CrewAI that automates tasks across Gmail, HubSpot CRM, and Google Calendar with intelligent planning, review, and execution capabilities.

## 🌟 Features

- **🧠 Intelligent Task Planning**: Breaks down complex user requests into actionable steps
- **🔍 Automated Quality Review**: Validates drafts with confidence scoring before execution
- **🛠️ Multi-Tool Integration**: Seamlessly works with Gmail, HubSpot, and Google Calendar
- **💾 Persistent Memory**: Uses ChromaDB to remember past interactions and learn from them
- **📢 Real-time Notifications**: Provides live updates on task progress
- **🎯 Typed Contracts**: Fully typed interfaces for reliability and maintainability
- **📄 Document Summaries**: Pull meeting notes from uploaded PDF/DOCX/TXT files for email drafts

## 🏗️ Architecture

The system follows a modular agent-based architecture:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Planner       │───▶│  Deliberation    │───▶│   Reviewer      │
│   Agent         │    │  Core            │    │   Agent         │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Memory        │    │   Tool Agents    │    │   Notifier      │
│   Agent         │    │ (Gmail/HubSpot/  │    │   Agent         │
│  (ChromaDB)     │    │   Calendar)      │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Core Components

1. **Planner Agent**: Analyzes user queries and creates structured execution plans
2. **Deliberation Core**: Generates high-quality drafts based on plans
3. **Reviewer Agent**: Validates drafts with confidence scoring and issue detection
4. **Tool Agents**: Execute actions on external services (Gmail, HubSpot, Calendar)
5. **Memory Agent**: Stores and retrieves interaction history using ChromaDB
6. **Notifier Agent**: Provides real-time progress updates

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- pip package manager

### Installation

1. **Clone or download the project files**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python cli.py
   ```

### First Run

1. **API Credentials Setup** (one-time): populate a `.env` file with your API tokens before launching the CLI.
   - **Gmail**: supply `GMAIL_SENDER`, choose `GMAIL_AUTH_METHOD` (`app_password` or `oauth`), and provide either `GMAIL_APP_PASSWORD` *or* `GMAIL_OAUTH_TOKEN_PATH` / `GMAIL_OAUTH_TOKEN_JSON`.
   - **HubSpot & Google Calendar**: set `HUBSPOT_API_TOKEN` and `CALENDAR_API_TOKEN` as needed.

2. **Interactive Mode**: After setup, you can start making requests like:

   - "Send an email to john@example.com about the project update"
   - "Schedule a meeting for tomorrow at 2 PM"
   - "Log a customer interaction in CRM"

## 📋 Usage Examples

### Email Tasks
```
💬 What can I help you with? Send an email to team@company.com about the quarterly review

🧠 [PLANNER] Created plan with 1 steps, requires tools: [ToolType.GMAIL]
📝 [DELIBERATION] Generated email draft: abc123...
🔍 [REVIEWER] Draft abc123... - Score: 0.85, Approved: True
📧 [GMAIL] Email sent to team@company.com: Re: Send an email to team@company.com about the quarterly review
✅ [NOTIFICATION] Task completed successfully!
```

### Calendar Tasks
```
💬 What can I help you with? Schedule a team meeting for next Monday at 10 AM

🧠 [PLANNER] Created plan with 1 steps, requires tools: [ToolType.CALENDAR]
📝 [DELIBERATION] Generated calendar_event draft: def456...
🔍 [REVIEWER] Draft def456... - Score: 0.90, Approved: True
📅 [CALENDAR] Event created: Meeting: Schedule a team meeting for next Monday at 10 AM at 2024-01-15T14:00:00
✅ [NOTIFICATION] Task completed successfully!
```

### CRM Tasks
```
💬 What can I help you with? Create a contact for sarah@newclient.com

🧠 [PLANNER] Created plan with 1 steps, requires tools: [ToolType.HUBSPOT]
📝 [DELIBERATION] Generated crm_log draft: ghi789...
🔍 [REVIEWER] Draft ghi789... - Score: 0.88, Approved: True
👤 [HUBSPOT] Contact created: sarah@newclient.com
✅ [NOTIFICATION] Task completed successfully!
```

## 🎛️ CLI Commands

- `help` - Show available commands and examples
- `status` - Display system status and component health
- `memory` - Show memory statistics and recent interactions
- `clear` - Clear the terminal screen
- `quit`/`exit`/`q` - Exit the application

## 🗂️ Document Summaries

- Place meeting notes and reference files in `./user_documents`.
- The CLI automatically grabs the most recently updated PDF/DOCX/TXT/Markdown file when a summary is needed.
- If you prefer a specific document, reply with its filename (for example, `meeting.pdf`) or paste the relevant text.

## 🔧 Configuration

### Confidence Threshold
The reviewer agent uses a confidence threshold (default: 0.7) to determine if drafts need user approval:
- **≥ 0.8**: High confidence (auto-approved)
- **0.6-0.79**: Medium confidence (may require review)
- **< 0.6**: Low confidence (requires user review)

### Environment Variables
The application reads credentials from a `.env` file (loaded via `python-dotenv`). Set one of the following options for each provider before launching the CLI:

- `GMAIL_SENDER` – Email address used as the sender.
- `GMAIL_AUTH_METHOD` – `app_password` or `oauth`. If omitted, the method is inferred from the provided secrets.
- `GMAIL_APP_PASSWORD` – 16-character Gmail app password (required when `GMAIL_AUTH_METHOD=app_password`).
- `GMAIL_OAUTH_TOKEN_PATH` – Filesystem path to an OAuth token JSON file (used when `GMAIL_AUTH_METHOD=oauth`).
- `GMAIL_OAUTH_TOKEN_JSON` – Raw OAuth token JSON (alternative to the path; the CLI stores it under `memory_db/credentials/`).
- `HUBSPOT_API_TOKEN` – HubSpot private app token.
- `CALENDAR_API_TOKEN` – Google Calendar API token.
- `OPENAI_API_KEY` – Enables conversational responses and draft generation.
- `OPENAI_MODEL` – Optional override for the OpenAI model name (defaults to `gpt-4o-mini`).

If none of the variables are supplied the CLI runs in demo mode (no live API calls).

### Memory Persistence

ChromaDB stores interaction history in the `./chroma_db` directory. This includes:
- User queries and generated plans
- Execution results and outcomes
- Sentiment analysis and tags
- Timestamps for temporal analysis

## 🛠️ Development

### Project Structure
```
autonomous1/
├── cli.py              # Main CLI interface
├── agents.py           # CrewAI agent implementations
├── tools.py            # Tool agent implementations
├── memory.py           # ChromaDB memory management
├── contracts.py        # Typed data contracts
├── document_manager.py # Document ingestion helpers
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── user_documents/     # Drop meeting notes for summaries
```

### Key Design Principles

1. **Modularity**: Each component has a single responsibility
2. **Type Safety**: All interfaces use Pydantic models for validation
3. **Error Handling**: Graceful degradation and informative error messages
4. **Extensibility**: Easy to add new tools and agents
5. **User Experience**: Rich CLI interface with progress indicators

### Adding New Tools

To add a new tool integration:

1. **Define the tool type** in `contracts.py`:
   ```python
   class ToolType(str, Enum):
       # ... existing tools
       NEW_TOOL = "new_tool"
   ```

2. **Create the tool agent** in `tools.py`:
   ```python
   class NewToolAgent(ToolAgent):
       def execute(self, action: str, parameters: Dict[str, Any]) -> ToolExecution:
           # Implementation here
   ```

3. **Update the CLI** to initialize the new tool in `cli.py`

## 🔍 Troubleshooting

### Common Issues

1. **ChromaDB Permission Errors**: Ensure write permissions in the project directory
2. **Missing Dependencies**: Run `pip install -r requirements.txt`
3. **API Token Issues**: Verify tokens are valid and have required permissions

### Debug Mode
For detailed logging, modify the agent verbose settings in `agents.py`:
```python
self.agent = Agent(
    # ... other parameters
    verbose=True  # Enable detailed logging
)
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with proper type hints
4. Test thoroughly with different scenarios
5. Submit a pull request

## 📄 License

This project is provided as-is for educational and demonstration purposes.

## 🙏 Acknowledgments

- **CrewAI**: For the excellent agent orchestration framework
- **ChromaDB**: For persistent vector storage capabilities
- **Rich**: For beautiful CLI formatting and user experience
