"""
Main CLI interface for the CrewAI Agent Workflow System.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

# Rich for better CLI formatting
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn


try:
    from dateutil import parser as date_parser
except ImportError:
    date_parser = None

# Import our modules
from contracts import ToolType, ToolExecution, Plan
from agents import PlannerAgent, DeliberationCore, ReviewerAgent, NotifierAgent
from tools import GmailToolAgent, PipedriveToolAgent, CalendlyToolAgent
from memory import MemoryAgent
from config_store import CredentialsStore
from llm import LLMClient
from document_manager import DocumentManager


class CrewAIWorkflowCLI:
    """Main CLI application for the CrewAI workflow system."""
    
    def __init__(self):
        self.console = Console()
        self.credentials_store = CredentialsStore()
        self.credentials = self.credentials_store.load_env_credentials()
        self.llm = LLMClient()
        self.memory_agent = MemoryAgent()
        self.notifier = NotifierAgent()
        self.document_manager = DocumentManager(Path("user_documents"))
        self.documents_dir = self.document_manager.base_dir

        # Initialize agents
        self.planner = PlannerAgent(llm_client=self.llm, documents_dir=self.documents_dir)
        self.deliberation_core = DeliberationCore(llm_client=self.llm)
        self.reviewer = ReviewerAgent(confidence_threshold=0.7, llm_client=self.llm)
        
        # Tool agents (will be initialized after credentials)
        self.tool_agents = {}
        
        # Simple pending states
        self.pending_email = {
            "to": None,
            "subject": None, 
            "content": None,
            "original_query": None
        }
        self.pending_crm = {
            "name": None,
            "email": None,
            "original_query": None
        }
        self.current_task_type = None  # "email", "crm", "calendly", None
        
    def run(self):
        """Main entry point for the CLI application."""
        self.show_welcome()

        # Collect API credentials
        if not self.collect_credentials():
            self.console.print("❌ Cannot proceed without API credentials. Exiting.", style="red")
            return

        # Initialize tool agents
        self.initialize_tool_agents()

        # Show system status
        self.show_system_status()

        # Main interaction loop
        self.main_loop()

    def show_welcome(self):
        """Display welcome message and system information."""
        welcome_text = Text()
        welcome_text.append("🤖 CrewAI Agent Workflow System\n", style="bold blue")
        welcome_text.append("Intelligent task automation with Gmail, HubSpot & Calendly integration\n\n", style="cyan")
        welcome_text.append("Features:\n", style="bold")
        welcome_text.append("• 📋 Smart task planning and breakdown\n", style="green")
        welcome_text.append("• 🔍 Automated quality review and validation\n", style="green")
        welcome_text.append("• 🛠️ Multi-tool integration (Gmail, HubSpot & Calendly)\n", style="green")
        welcome_text.append("• 🧠 Persistent memory with ChromaDB\n", style="green")
        welcome_text.append("• 📢 Real-time notifications and updates\n", style="green")

        panel = Panel(welcome_text, title="Welcome", border_style="blue")
        self.console.print(panel)

    def collect_credentials(self) -> bool:
        """Load API credentials from environment and report status."""
        self.credentials = self.credentials_store.load_env_credentials()

        has_gmail = bool(
            self.credentials.gmail_address
            and (self.credentials.gmail_token or self.credentials.gmail_token_path)
        )
        has_pipedrive = bool(
            self.credentials.pipedrive_api_token
            and self.credentials.pipedrive_domain
        )
        has_calendly = bool(
            self.credentials.calendly_token
            and self.credentials.calendly_event_type_uuid
            and self.credentials.calendly_scheduling_link
        )


        self.console.print("\n🔐 Loading credentials from environment (.env)", style="bold yellow")

        if has_gmail:
            method = self.credentials.gmail_auth_method
            if not method:
                if self.credentials.gmail_token_path:
                    method = "oauth"
                elif self.credentials.gmail_token:
                    method = "app_password"
                else:
                    method = "unknown"
            method_label = (
                "OAuth (Gmail API)" if method == "oauth" else
                "App password (SMTP)" if method == "app_password" else
                "Configured"
            )
            self.console.print(
                f"📧 Gmail: {self.credentials.gmail_address} ({method_label})",
                style="green"
            )
        else:
            self.console.print(
                "⚠️ Gmail credentials missing or incomplete. Gmail tool will run in demo mode.",
                style="yellow"
            )

        if has_pipedrive:
            domain_name = self.credentials.pipedrive_domain.replace('https://', '').replace('http://', '')
            self.console.print(f"💼 Pipedrive CRM ready ({domain_name})", style="green")
        else:
            self.console.print("⚠️ Pipedrive credentials missing. CRM features will be disabled.", style="yellow")

        if has_calendly:
            self.console.print("📅 Calendly API ready (token, event type, scheduling link).", style="green")
        else:
            self.console.print("⚠️ Calendly credentials incomplete. Availability lookups will be disabled.", style="yellow")

        if not any([has_gmail, has_pipedrive, has_calendly]):
            self.console.print(
                "⚠️ No credentials found in environment. Running in demo mode.",
                style="yellow"
            )

        return True

    def _find_step(self, plan: Plan, tool_type: ToolType):
        for step in plan.steps:
            if step.tool_required == tool_type:
                return step
        return None

    def _map_missing_label(self, label: str, plan: Plan) -> Optional[Dict[str, Any]]:
        label_lower = label.lower()
        if "email recipient" in label_lower:
            step = self._find_step(plan, ToolType.GMAIL)
            if step:
                return {"label": label, "field": "to", "prompt": "Who should receive the email?", "step": step}
        if "email subject" in label_lower:
            step = self._find_step(plan, ToolType.GMAIL)
            if step:
                return {"label": label, "field": "subject", "prompt": "What subject line would you like?", "step": step}
        if "report summary" in label_lower or "summary" in label_lower:
            step = self._find_step(plan, ToolType.GMAIL)
            if step:
                prompt = (
                    "Please share the notes to summarize. Paste the text or provide "
                    "the filename (e.g., meeting.pdf) after placing it in the documents folder."
                )
                return {"label": label, "field": "summary_content", "prompt": prompt, "step": step}
        if "meeting date" in label_lower:
            step = self._find_step(plan, ToolType.CALENDLY)
            if step:
                prompt = "Which date should I check availability for? (YYYY-MM-DD or phrases like today/tomorrow)"
                return {"label": label, "field": "date", "prompt": prompt, "step": step}
        return None

    def _build_missing_items(self, plan: Plan) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for label in plan.missing_info:
            mapping = self._map_missing_label(label, plan)
            if mapping:
                items.append(mapping)
        plan.missing_info = []
        return items

    def _auto_resolve_missing_items(self) -> None:
        if not self.pending_plan or not self.pending_missing_items:
            return

        for item in list(self.pending_missing_items):
            field = item.get("field")
            if field == "summary_content":
                success, content, error, source_path = self.document_manager.load_latest_document_text()
                if success and content and content.strip():
                    self._apply_missing_answer(item, content.strip())
                    source_label = source_path.name if source_path else "document"
                    self.console.print(f"📄 Loaded notes from {source_label}", style="green")
                    self.pending_missing_items.remove(item)
                    continue

                if error:
                    self.console.print(f"ℹ️ {error}", style="yellow")
                self.console.print(
                    f"Drop your notes file into {self.documents_dir} and tell me its name, or paste the notes directly.",
                    style="yellow"
                )
                continue

    def _ask_next_missing_question(self) -> None:
        if not self.pending_plan:
            return
        if not self.pending_missing_items:
            plan = self.pending_plan
            self.pending_plan = None
            self._execute_plan(plan)
            return
        current = self.pending_missing_items[0]
        question = None
        if self.llm and self.llm.is_available():
            question = self.llm.generate_clarification_question(
                self.pending_plan.user_query,
                [current["label"]],
            )
        if not question:
            question = current.get("prompt", "Could you provide more detail?")
        current["last_prompt"] = question
        self.console.print(question, style="cyan")

    def _apply_missing_answer(self, item: Dict[str, Any], answer: str) -> None:
        step = item.get("step")
        field = item.get("field")
        if step and field:
            step.parameters[field] = answer

    def handle_missing_info_response(self, user_input: str) -> bool:
        if not self.current_task_type:
            return False
            
        stripped = user_input.strip()
        if stripped.lower() in {"cancel", "stop"}:
            self.console.print("Okay, I'll cancel that request.", style="yellow")
            self._clear_all_pending()
            return True
        
        # Handle based on current task type
        if self.current_task_type == "email":
            return self._handle_email_followup(stripped)
        elif self.current_task_type == "crm":
            return self._handle_crm_followup(stripped)
        
        return False
    
    def _clear_all_pending(self):
        """Clear all pending states."""
        self.pending_email = {"to": None, "subject": None, "content": None, "original_query": None}
        self.pending_crm = {"name": None, "email": None, "original_query": None}
        self.current_task_type = None
    
    def _clear_pending_email(self):
        """Clear pending email state."""
        self.pending_email = {"to": None, "subject": None, "content": None, "original_query": None}
        self.current_task_type = None
    
    def _handle_email_followup(self, text: str) -> bool:
        """Handle email follow-up responses."""
        self._extract_email_info(text)
        
        if self._is_email_complete():
            self._send_email()
            self._clear_pending_email()
        else:
            missing = self._get_missing_email_info()
            self.console.print(f"\n❓ I still need: {', '.join(missing)}", style="yellow")
        return True
    
    def _handle_crm_followup(self, text: str) -> bool:
        """Handle CRM follow-up responses."""
        self._extract_crm_info(text)
        
        if self._is_crm_complete():
            self._add_crm_contact()
            self._clear_pending_crm()
        else:
            missing = self._get_missing_crm_info()
            self.console.print(f"\n❓ I still need: {', '.join(missing)}", style="yellow")
        return True
    
    def _clear_pending_crm(self):
        """Clear pending CRM state."""
        self.pending_crm = {"name": None, "email": None, "original_query": None}
        self.current_task_type = None
    
    def _extract_email_info(self, text: str):
        """Extract email info from text and store it."""
        import re
        
        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        if emails and not self.pending_email["to"]:
            self.pending_email["to"] = emails[0]
        
        # Extract subject
        if "subject" in text.lower():
            # Look for patterns like "subject: X", "subject - X", or "subject would be X"
            subject_match = re.search(r'subject[:\s-]+(?:would be\s+|is\s+)?([^,.\n]+?)(?:\s*,|\s*$)', text, re.IGNORECASE)
            if subject_match and not self.pending_email["subject"]:
                self.pending_email["subject"] = subject_match.group(1).strip()
        
        # Check for document references and load content
        if "jp.txt" in text.lower() or "document" in text.lower():
            jp_path = self.documents_dir / "JP.txt"
            if jp_path.exists() and not self.pending_email["content"]:
                try:
                    raw_content = jp_path.read_text(encoding='utf-8').strip()
                    
                    # Use LLM to process content based on user request
                    processed_content = self._process_content_with_llm(raw_content, text)
                    self.pending_email["content"] = processed_content
                    
                    self.console.print(f"✅ Processed content from JP.txt using AI ({len(processed_content)} characters)", style="green")
                except Exception as e:
                    self.console.print(f"⚠️ Could not load JP.txt: {e}", style="yellow")
        
        # If no document reference, treat the text as content (but not if it's just an email request)
        elif not self.pending_email["content"] and len(text) > 20:
            # Don't treat email requests as content
            if not any(phrase in text.lower() for phrase in ["send email", "send an email", "help me send"]):
                self.pending_email["content"] = text
    
    def _is_email_complete(self) -> bool:
        """Check if we have all required email info."""
        return all([self.pending_email["to"], self.pending_email["subject"], self.pending_email["content"]])
    
    def _get_missing_email_info(self) -> List[str]:
        """Get list of missing email information."""
        missing = []
        if not self.pending_email["to"]:
            missing.append("recipient email")
        if not self.pending_email["subject"]:
            missing.append("subject")
        if not self.pending_email["content"]:
            missing.append("content")
        return missing
    
    def _extract_crm_info(self, text: str):
        """Extract CRM info from text and store it."""
        import re
        
        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        if emails and not self.pending_crm["email"]:
            self.pending_crm["email"] = emails[0]
        
        # Extract name (look for "name" keyword)
        if "name" in text.lower() and not self.pending_crm["name"]:
            # Look for patterns like "name - John Doe" or "name is John"
            name_match = re.search(r'name[:\s-]+([A-Za-z\s]+?)(?:\s+and|\s+email|$)', text, re.IGNORECASE)
            if name_match:
                self.pending_crm["name"] = name_match.group(1).strip()
    
    def _is_crm_complete(self) -> bool:
        """Check if we have all required CRM info."""
        return all([self.pending_crm["name"], self.pending_crm["email"]])
    
    def _get_missing_crm_info(self) -> List[str]:
        """Get list of missing CRM information."""
        missing = []
        if not self.pending_crm["name"]:
            missing.append("contact name")
        if not self.pending_crm["email"]:
            missing.append("email address")
        return missing
    
    def _add_crm_contact(self):
        """Add contact to CRM with collected information."""
        try:
            if ToolType.PIPEDRIVE in self.tool_agents:
                pipedrive_agent = self.tool_agents[ToolType.PIPEDRIVE]
                result = pipedrive_agent.execute("create_contact", {
                    "name": self.pending_crm["name"],
                    "email": self.pending_crm["email"]
                })
                
                if result.success:
                    self.console.print(f"✅ Contact '{self.pending_crm['name']}' added to Pipedrive with email {self.pending_crm['email']}", style="green")
                    self.notifier.send_notification("task_completed", "Contact added successfully!")
                else:
                    self.console.print(f"❌ Failed to add contact: {result.error}", style="red")
            else:
                self.console.print("❌ Pipedrive not configured", style="red")
        except Exception as e:
            self.console.print(f"❌ Error adding contact: {str(e)}", style="red")
    
    def _send_email(self):
        """Send the email with collected information."""
        try:
            if ToolType.GMAIL in self.tool_agents:
                gmail_agent = self.tool_agents[ToolType.GMAIL]
                
                # Call the correct method with correct parameters
                result = gmail_agent.execute("send_email", {
                    "to": self.pending_email["to"],
                    "subject": self.pending_email["subject"],
                    "body": self.pending_email["content"]
                })
                
                if result.success:
                    self.console.print(f"✅ Email sent to {self.pending_email['to']}", style="green")
                    self.notifier.send_notification("task_completed", "Email sent successfully!")
                else:
                    self.console.print(f"❌ Failed to send email: {result.error}", style="red")
            else:
                self.console.print("❌ Gmail not configured", style="red")
        except Exception as e:
            self.console.print(f"❌ Error sending email: {str(e)}", style="red")

    def _process_content_with_llm(self, raw_content: str, user_request: str) -> str:
        """Process document content using LLM based on user request."""
        try:
            if not self.llm:
                return raw_content
            
            # Determine what the user wants to do with the content
            request_lower = user_request.lower()
            
            if any(word in request_lower for word in ["summary", "summarize", "summarise"]):
                prompt = f"""Please create a concise professional summary of the following content for an email:

{raw_content}

Make it:
- Professional and engaging
- Concise (2-3 paragraphs max)
- Suitable for email communication
- Highlight key achievements and skills

Summary:"""
                
                response = self.llm.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.7
                )
                return response.choices[0].message.content.strip()
            
            elif any(word in request_lower for word in ["brief", "short", "concise"]):
                prompt = f"""Please create a brief, professional version of the following content for an email:

{raw_content}

Make it:
- Very concise (1-2 paragraphs)
- Professional tone
- Include only the most important points

Brief version:"""
                
                response = self.llm.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    temperature=0.7
                )
                return response.choices[0].message.content.strip()
            
            else:
                # Default: return raw content
                return raw_content
                
        except Exception as e:
            self.console.print(f"⚠️ Could not process content with AI: {e}", style="yellow")
            return raw_content

    def _handle_crm_request(self, query: str):
        """Handle CRM contact requests with simple extraction."""
        import re
        
        # Extract email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, query)
        
        # Extract name (look for "name" keyword)
        name = None
        if "name" in query.lower():
            # Look for patterns like "name - John Doe" or "name is John"
            name_match = re.search(r'name[:\s-]+([A-Za-z\s]+?)(?:\s+and|\s+email|$)', query, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()
        
        if emails and name:
            try:
                if ToolType.PIPEDRIVE in self.tool_agents:
                    pipedrive_agent = self.tool_agents[ToolType.PIPEDRIVE]
                    result = pipedrive_agent.execute("create_contact", {
                        "name": name,
                        "email": emails[0]
                    })
                    
                    if result.success:
                        self.console.print(f"✅ Contact '{name}' added to Pipedrive with email {emails[0]}", style="green")
                        self.notifier.send_notification("task_completed", "Contact added successfully!")
                    else:
                        self.console.print(f"❌ Failed to add contact: {result.error}", style="red")
                else:
                    self.console.print("❌ Pipedrive not configured", style="red")
            except Exception as e:
                self.console.print(f"❌ Error adding contact: {str(e)}", style="red")
        else:
            missing = []
            if not name:
                missing.append("contact name")
            if not emails:
                missing.append("email address")
            self.console.print(f"❓ I need: {', '.join(missing)}", style="yellow")

    def _handle_calendly_request(self, query: str):
        """Handle Calendly availability requests."""
        try:
            if ToolType.CALENDLY in self.tool_agents:
                calendly_agent = self.tool_agents[ToolType.CALENDLY]
                
                # Extract date from query (simple approach)
                date_param = None
                if "tomorrow" in query.lower():
                    from datetime import datetime, timedelta
                    tomorrow = datetime.now() + timedelta(days=1)
                    date_param = tomorrow.strftime("%Y-%m-%d")
                elif "today" in query.lower():
                    from datetime import datetime
                    today = datetime.now()
                    date_param = today.strftime("%Y-%m-%d")
                
                params = {}
                if date_param:
                    params["date"] = date_param
                
                result = calendly_agent.execute("list_available_slots", params)
                
                if result.success:
                    self.console.print("📅 Available time slots for tomorrow:", style="green")
                    if hasattr(result, 'result') and result.result:
                        self._format_calendly_slots(result.result)
                    else:
                        self.console.print("Check your Calendly scheduling link for available times.", style="cyan")
                    self.notifier.send_notification("task_completed", "Calendar availability retrieved!")
                else:
                    self.console.print(f"❌ Failed to get availability: {result.error}", style="red")
            else:
                self.console.print("❌ Calendly not configured", style="red")
        except Exception as e:
            self.console.print(f"❌ Error getting calendar availability: {str(e)}", style="red")

    def _format_calendly_slots(self, data):
        """Format Calendly slots in a user-friendly way."""
        try:
            if isinstance(data, dict) and 'slots' in data:
                slots = data['slots'][:4]  # Show only first 4 slots
                
                self.console.print("\n⏰ Next 4 available slots:", style="bold cyan")
                for i, slot in enumerate(slots, 1):
                    time_label = slot.get('label', 'Time not available')
                    self.console.print(f"   {i}. {time_label}", style="white")
                
                # Show booking link
                booking_link = data.get('scheduling_link', 'https://calendly.com/asyash21/30min')
                self.console.print(f"\n🔗 Book your meeting: {booking_link}", style="bold green")
                
                # Show additional info
                duration = data.get('meeting_duration', '30 minutes')
                self.console.print(f"📝 Meeting duration: {duration}", style="dim")
                
            else:
                self.console.print("Available slots data format not recognized.", style="yellow")
                
        except Exception as e:
            self.console.print(f"Error formatting slots: {str(e)}", style="red")
            # Fallback to raw data
            self.console.print(str(data), style="dim")

    def request_additional_info(self, plan: Plan) -> None:
        self.pending_plan = plan
        
        # Use LLM-generated follow-up question if available
        if hasattr(self.planner, '_current_analysis') and self.planner._current_analysis:
            follow_up_question = self.planner._current_analysis.get("follow_up_question")
            if follow_up_question:
                self.console.print(f"\n❓ {follow_up_question}", style="yellow")
                return
        
        # Fallback to generic question
        missing_info_text = ", ".join(plan.missing_info)
        if self.llm_client and self.llm_client.is_available():
            try:
                question = self.llm_client.generate_clarification_question(plan.user_query, plan.missing_info)
                self.console.print(f"\n❓ {question}", style="yellow")
                return
            except Exception:
                pass
        
        # Final fallback
        self.console.print(f"\n❓ I need more information: {missing_info_text}", style="yellow")

    def initialize_tool_agents(self):
        """Initialize tool agents with credentials."""
        available_tools = []
        
        if self.credentials.gmail_token or self.credentials.gmail_token_path:
            self.tool_agents[ToolType.GMAIL] = GmailToolAgent(self.credentials)
            available_tools.append(ToolType.GMAIL)
        
        if self.credentials.pipedrive_api_token and self.credentials.pipedrive_domain:
            self.tool_agents[ToolType.PIPEDRIVE] = PipedriveToolAgent(self.credentials)
            available_tools.append(ToolType.PIPEDRIVE)
        
        if (
            self.credentials.calendly_token
            and self.credentials.calendly_event_type_uuid
            and self.credentials.calendly_scheduling_link
        ):
            self.tool_agents[ToolType.CALENDLY] = CalendlyToolAgent(self.credentials)
            available_tools.append(ToolType.CALENDLY)

        self.available_tools = available_tools
        
        if available_tools:
            tools_text = ", ".join([tool.value for tool in available_tools])
            self.console.print(f"🛠️ Initialized tools: {tools_text}", style="green")
        else:
            self.console.print("⚠️ No tools available - running in demo mode", style="yellow")
    
    def show_system_status(self):
        """Display current system status."""
        # Memory statistics
        memory_stats = self.memory_agent.get_interaction_stats()

        # Create status table
        table = Table(title="System Status", show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")
        
        # Add rows
        table.add_row("🧠 Memory Agent", "✅ Active", f"Stored interactions: {memory_stats.get('total_interactions', 0)}")
        table.add_row("📋 Planner Agent", "✅ Ready", "Task planning and breakdown")
        table.add_row("🔍 Reviewer Agent", "✅ Ready", f"Confidence threshold: {self.reviewer.confidence_threshold}")
        table.add_row("📢 Notifier Agent", "✅ Ready", "Real-time notifications")
        
        # Gmail status with method details
        if ToolType.GMAIL in self.tool_agents:
            method = self.credentials.gmail_auth_method
            if not method:
                if self.credentials.gmail_token_path:
                    method = "oauth"
                elif self.credentials.gmail_token:
                    method = "app_password"
                else:
                    method = "unknown"
            method_label = ("OAuth (Gmail API)" if method == "oauth" else "App password (SMTP)" if method == "app_password" else "Configured")
            address = self.credentials.gmail_address or "Unknown sender"
            detail = f"Account: {address} | Method: {method_label}"
            if method == "oauth" and not (self.credentials.gmail_token_path or self.credentials.gmail_token):
                detail += " | OAuth token missing"
            table.add_row("🛠️ Gmail", "✅ Connected", detail)
        else:
            table.add_row("🛠️ Gmail", "❌ Offline", "Configure Gmail credentials")

        for tool_type, label in [
            (ToolType.PIPEDRIVE, "Ready for CRM contact management"),
            (ToolType.CALENDLY, "Ready to share Calendly availability"),
        ]:
            if tool_type in self.tool_agents:
                table.add_row(f"🛠️ {tool_type.value.title()}", "✅ Connected", label)
            else:
                table.add_row(f"🛠️ {tool_type.value.title()}", "❌ Offline", "No credentials provided")

        self.console.print(table)

    def main_loop(self):
        """Main interaction loop."""
        self.console.print("\n🚀 System ready! Type 'help' for commands or 'quit' to exit.\n", style="bold green")
        
        while True:
            try:
                user_input = Prompt.ask("\n💬 What can I help you with?", default="").strip()

                if not user_input:
                    continue

                lower = user_input.lower()

                # Handle pending tasks
                if self.current_task_type and lower not in {'help', 'status', 'memory', 'clear', 'quit', 'exit', 'q'}:
                    if self.handle_missing_info_response(user_input):
                        continue

                if lower in {'quit', 'exit', 'q'}:
                    self.console.print("👋 Goodbye!", style="blue")
                    break
                if lower == 'help':
                    self.show_help()
                    continue
                if lower == 'status':
                    self.show_system_status()
                    continue
                if lower == 'memory':
                    self.show_memory_stats()
                    continue
                if lower == 'clear':
                    os.system('cls' if os.name == 'nt' else 'clear')
                    continue

                if any(self.pending_email.values()):
                    if self.handle_missing_info_response(user_input):
                        continue

                self.process_user_request(user_input)

            except KeyboardInterrupt:
                self.console.print("\n👋 Goodbye!", style="blue")
                break
            except Exception as e:
                self.console.print(f"❌ Error: {str(e)}", style="red")
    
    def process_user_request(self, user_query: str):
        """Process user request with simple deterministic logic."""
        self.notifier.send_notification("task_started", f"Processing request: {user_query}")
        query_lower = user_query.lower()
        
        # CRM DETECTION (check first to avoid email conflict)
        if any(word in query_lower for word in ["contact", "crm", "pipedrive", "add"]) and not any(word in query_lower for word in ["send email", "email to"]):
            self.current_task_type = "crm"
            self.pending_crm["original_query"] = user_query
            self._extract_crm_info(user_query)
            
            if self._is_crm_complete():
                self._add_crm_contact()
                self._clear_pending_crm()
            else:
                missing = self._get_missing_crm_info()
                self.console.print(f"\n❓ I need: {', '.join(missing)}", style="yellow")
        
        # EMAIL DETECTION
        elif any(word in query_lower for word in ["send email", "email to", "send mail"]) or (any(word in query_lower for word in ["email", "send", "mail"]) and not any(word in query_lower for word in ["contact", "crm", "pipedrive"])):
            self.current_task_type = "email"
            self.pending_email["original_query"] = user_query
            self._extract_email_info(user_query)
            
            if self._is_email_complete():
                self._send_email()
                self._clear_pending_email()
            else:
                missing = self._get_missing_email_info()
                self.console.print(f"\n❓ I need: {', '.join(missing)}", style="yellow")
        
        # CALENDLY DETECTION  
        elif any(word in query_lower for word in ["calendar", "meeting", "schedule", "available", "calendly"]):
            self.current_task_type = "calendly"
            self._handle_calendly_request(user_query)
        
        # GENERAL
        else:
            self.console.print("Hello! I can help you with:\n• 📧 Email (Gmail)\n• 👥 Contacts (Pipedrive CRM)\n• 📅 Calendar (Calendly)\n\nWhat would you like to do?", style="cyan")
    
    def handle_user_review(self, draft, review_result) -> bool:
        """Handle user review of drafts that need approval."""
        self.console.print("\n🔍 Draft Review Required", style="bold yellow")
        
        # Show confidence score
        confidence_color = "green" if review_result.confidence_score >= 0.7 else "yellow" if review_result.confidence_score >= 0.5 else "red"
        self.console.print(f"Confidence Score: {review_result.confidence_score:.2f}", style=confidence_color)
        
        # Show issues if any
        if review_result.issues:
            self.console.print("\n⚠️ Issues Found:", style="red")
            for issue in review_result.issues:
                self.console.print(f"  • {issue}", style="red")
        
        # Show suggestions if any
        if review_result.suggestions:
            self.console.print("\n💡 Suggestions:", style="yellow")
            for suggestion in review_result.suggestions:
                self.console.print(f"  • {suggestion}", style="yellow")
        
        # Show draft content
        self.console.print("\n📄 Draft Content:", style="bold")
        draft_panel = Panel(
            json.dumps(draft.content, indent=2),
            title=f"{draft.task_type.value.title()} Draft",
            border_style="blue"
        )
        self.console.print(draft_panel)
        
        # Ask for user approval
        return Confirm.ask("\n✅ Do you want to proceed with this draft?")
    
    def _execute_plan(self, plan: Plan) -> None:
        plan.is_complete = True
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as progress:
            task = progress.add_task("📝 Generating draft...", total=None)
            try:
                draft = self.deliberation_core.generate_draft(plan)
                progress.update(task, description="🔍 Reviewing draft...")
                review_result = self.reviewer.review_draft(draft)
                progress.update(task, description="✅ Processing complete")
            except RuntimeError as e:
                progress.update(task, description="❌ Draft generation failed")
                self.console.print(f"\n❌ [bold red]Error generating content:[/bold red] {str(e)}")
                self.console.print("\n💡 [yellow]Suggestions:[/yellow]")
                self.console.print("• Check your OpenAI API key is valid and has credits")
                self.console.print("• Try rephrasing your request more naturally")
                self.console.print("• Ensure all required information is provided")
                self.notifier.send_notification("task_failed", f"Content generation failed: {str(e)}")
                return
            except Exception as e:
                progress.update(task, description="❌ Unexpected error")
                self.console.print(f"\n❌ [bold red]Unexpected error:[/bold red] {str(e)}")
                self.notifier.send_notification("task_failed", f"Unexpected error: {str(e)}")
                return

        if review_result.requires_user_review:
            if not self.handle_user_review(draft, review_result):
                self.notifier.send_notification("task_failed", "Task cancelled by user")
                return

        execution_results = self.execute_draft(draft, plan)
        self.store_interaction_memory(plan.user_query, plan, draft, execution_results)
        self.notifier.send_notification("task_completed", "Task completed successfully!")

    def execute_draft(self, draft, plan):
        """Execute the approved draft using appropriate tool agents."""
        self.console.print("\n🚀 Executing approved draft...", style="bold green")
        
        execution_results = []
        
        for step in plan.steps:
            action = step.parameters.get("action", "default_action")

            if step.tool_required == ToolType.GENERAL or action == "general_assistance":
                message = draft.content.get("message") if isinstance(draft.content, dict) else None
                if not message and self.llm and self.llm.is_available():
                    message = self.llm.generate_general_response(plan.user_query)
                if not message:
                    message = "I'm here to help with Gmail email tasks, Pipedrive CRM contact management, and share Calendly availability. Let me know what you'd like to do next."

                self.console.print(f"\n💬 {message}\n", style="cyan")
                execution_results.append(ToolExecution(
                    execution_id=f"general_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    tool_type=ToolType.GENERAL,
                    action=action,
                    parameters=step.parameters,
                    success=True,
                    result={"message": message}
                ))
                continue

            if step.tool_required in self.tool_agents:
                tool_agent = self.tool_agents[step.tool_required]

                # Merge step parameters with draft content
                execution_params = {**step.parameters, **draft.content}
                
                # Execute the tool action
                result = tool_agent.execute(action, execution_params)
                execution_results.append(result)
                
                if result.success:
                    self.console.print(f"✅ {step.description}", style="green")
                    if step.tool_required == ToolType.CALENDLY:
                        self._display_calendly_slots(result)
                else:
                    self.console.print(f"❌ {step.description}: {result.error}", style="red")
                    if step.tool_required == ToolType.CALENDLY:
                        self._display_calendly_slots(result)
            else:
                self.console.print(f"⚠️ Tool not available: {step.tool_required.value}", style="yellow")
                execution_results.append(ToolExecution(
                    execution_id=f"missing_tool_{step.tool_required.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    tool_type=step.tool_required,
                    action=action,
                    parameters=step.parameters,
                    success=False,
                    error="Tool not available"
                ))
                continue

        return execution_results
    
    def _display_calendly_slots(self, execution_result: ToolExecution) -> None:
        result = execution_result.result or {}
        date_label = result.get("date_label", "the selected date")
        slots = result.get("slots", [])
        total_slots = result.get("total_slots", 0)
        scheduling_link = result.get("scheduling_link")
        meeting_duration = result.get("meeting_duration")
        timezone_info = result.get("timezone")

        if execution_result.success:
            if slots:
                self.console.print(f"\n📅 Available slots for {date_label}:", style="green")
                for i, slot in enumerate(slots, 1):
                    label = slot.get("label", "Available slot")
                    self.console.print(f"  {i}. {label}", style="cyan")
                
                if total_slots > len(slots):
                    remaining = total_slots - len(slots)
                    self.console.print(f"  ... and {remaining} more slots", style="dim")
            else:
                self.console.print(f"\n📅 No available slots found for {date_label}", style="yellow")
        else:
            error_msg = execution_result.error or "Failed to fetch availability"
            self.console.print(f"\n❌ {error_msg}", style="red")
        
        if meeting_duration and timezone_info:
            self.console.print(f"\n⏱️  Duration: {meeting_duration} | 🌍 Timezone: {timezone_info}", style="dim")
        
        if scheduling_link:
            self.console.print(f"🔗 Book via Calendly: {scheduling_link}", style="green")
        
        self.console.print("")

    def _normalize_date_input(self, text: str) -> Optional[str]:
        if not text:
            return None

        lowered = text.strip().lower()
        ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
        if lowered == "today":
            return ist_today.isoformat()
        if lowered == "tomorrow":
            return (ist_today + timedelta(days=1)).isoformat()

        try:
            parsed = datetime.fromisoformat(text.strip())
            return parsed.date().isoformat()
        except ValueError:
            pass

        if date_parser:
            try:
                parsed = date_parser.parse(text, fuzzy=True)
                if parsed:
                    return parsed.date().isoformat()
            except (ValueError, TypeError):
                return None
        return None

    def store_interaction_memory(
        self,
        user_query: str,
        plan,
        draft,
        execution_results: Optional[List[ToolExecution]] = None):
        """Store the interaction in memory for future reference."""
        try:
            execution_results = execution_results or []
            success_count = sum(1 for result in execution_results if result.success)
            plan_summary = (
                f"Created {len(plan.steps)} steps using tools: {[t.value for t in plan.required_tools]}"
            )
            if execution_results:
                plan_summary += f" | Success: {success_count}/{len(execution_results)}"
            sentiment = "positive" if execution_results and success_count == len(execution_results) else "neutral"

            memory_entry = self.memory_agent.create_memory_entry(
                user_query=user_query,
                plan_summary=plan_summary,
                execution_results=execution_results,
                sentiment=sentiment,
                tags=[draft.task_type.value, "cli_interaction"]
            )

            self.memory_agent.store_interaction(memory_entry)

        except Exception as e:
            self.console.print(f"⚠️ Failed to store interaction in memory: {e}", style="yellow")

    def show_help(self):
        """Display help information."""
        help_text = Text()
        help_text.append("Available Commands:\n\n", style="bold")
        help_text.append("help", style="cyan")
        help_text.append(" - Show this help message\n")
        help_text.append("status", style="cyan")
        help_text.append(" - Show system status\n")
        help_text.append("memory", style="cyan")
        help_text.append(" - Show memory statistics\n")
        help_text.append("clear", style="cyan")
        help_text.append(" - Clear the screen\n")
        help_text.append("quit/exit/q", style="cyan")
        help_text.append(" - Exit the application\n\n")

        help_text.append("Example Requests:\n", style="bold")
        help_text.append("• Send an email to john@example.com about the meeting\n", style="green")
        help_text.append("• Create a contact for jane@company.com\n", style="green")
        help_text.append("• Search for contacts named John Smith\n", style="green")
        help_text.append("• Update contact 123 with phone +1-555-0123\n", style="green")
        help_text.append("• Share today's Calendly slots for a quick catch-up\n", style="green")
        help_text.append(
            f"\nDocuments folder: {self.documents_dir}\nPlace meeting notes there and I'll grab the latest file automatically. Tell me the filename if you need a different one.\n",
            style="dim"
        )

        panel = Panel(help_text, title="Help", border_style="blue")
        self.console.print(panel)
    
    def show_memory_stats(self):
        """Display memory statistics and recent interactions."""
        stats = self.memory_agent.get_interaction_stats()
        recent_interactions = self.memory_agent.get_recent_interactions(5)
        
        # Stats table
        stats_table = Table(title="Memory Statistics", show_header=True, header_style="bold magenta")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="green")
        
        stats_table.add_row("Total Interactions", str(stats.get('total_interactions', 0)))
        
        if 'sentiment_distribution' in stats:
            for sentiment, count in stats['sentiment_distribution'].items():
                stats_table.add_row(f"  {sentiment.title()} Sentiment", str(count))
        
        self.console.print(stats_table)
        
        # Recent interactions
        if recent_interactions:
            self.console.print("\n📚 Recent Interactions:", style="bold")
            for i, interaction in enumerate(recent_interactions[:3], 1):
                timestamp = interaction.get('timestamp', 'Unknown')
                query = interaction.get('user_query', 'No query')[:50] + "..." if len(interaction.get('user_query', '')) > 50 else interaction.get('user_query', 'No query')
                self.console.print(f"{i}. [{timestamp[:19]}] {query}", style="dim")


def main():
    """Main entry point."""
    try:
        cli = CrewAIWorkflowCLI()
        cli.run()
    except Exception as e:
        console = Console()
        console.print(f"❌ Fatal error: {str(e)}", style="red")
        sys.exit(1)


if __name__ == "__main__":
    main()
