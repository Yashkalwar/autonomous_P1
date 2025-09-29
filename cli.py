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
from contracts import ToolType, ToolExecution
from agents import NotifierAgent
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

        # No agents needed for hybrid approach - using direct LLM calls
        
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
        # Track which single field we are currently asking for (one-at-a-time UX)
        self.current_prompt_field = None  # ("email", "subject") or ("crm", "name") etc.
        
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
        self.current_prompt_field = None
    
    def _clear_pending_email(self):
        """Clear pending email state."""
        self.pending_email = {"to": None, "subject": None, "content": None, "original_query": None}
        self.current_task_type = None
        self.current_prompt_field = None
    
    def _handle_email_followup(self, text: str) -> bool:
        """Handle email follow-up responses."""
        # Handle recipient input for hybrid approach
        if self.current_prompt_field == ("email", "to"):
            self._assign_email_field_from_text("to", text)
            if self.pending_email["to"]:
                # We have recipient, now check if we have enough info to generate content
                original_query = self.pending_email["original_query"]
                content_requirement = self.pending_email.get("content_requirement")
                document_reference = self.pending_email.get("document_reference")
                
                # Only auto-generate if we have specific content requirements or document references
                if content_requirement or document_reference:
                    try:
                        # Generate body using LLM
                        body = self._generate_email_body_with_llm(
                            original_query, 
                            content_requirement, 
                            document_reference
                        )
                        self.pending_email["content"] = body
                        
                        # Generate subject if not provided
                        if not self.pending_email["subject"]:
                            self.pending_email["subject"] = self._generate_subject_from_query(original_query, body)
                        
                        # Send email
                        self._send_email()
                        self._clear_pending_email()
                        return True
                        
                    except Exception as e:
                        self.console.print(f"❌ Error generating email content: {str(e)}", style="red")
                else:
                    # Ask for subject first, then content
                    self.current_prompt_field = ("email", "subject")
                    self.console.print("❓ What should be the email subject?", style="yellow")
                    return True
            return True
        
        # Handle subject input
        elif self.current_prompt_field == ("email", "subject"):
            self._assign_email_field_from_text("subject", text)
            if self.pending_email["subject"]:
                # Got subject, now ask for content
                self.current_prompt_field = ("email", "content")
                self.console.print("❓ What should be the email content?", style="yellow")
                return True
        
        # Handle content input
        elif self.current_prompt_field == ("email", "content"):
            self._assign_email_field_from_text("content", text)
            if self.pending_email["content"]:
                # Got content, now send email
                self._send_email()
                self._clear_pending_email()
                return True
        else:
            # No specific field set yet: seed from free text but do not over-capture
            self._extract_email_info(text)

        if self._is_email_complete():
            self._send_email()
            self._clear_pending_email()
            return True

        # Ask for next single missing field
        self._prompt_next_email_field()
        return True
    
    def _handle_crm_followup(self, text: str) -> bool:
        """Handle CRM follow-up responses."""
        # If we are asking for a specific field, map reply ONLY to that field
        if self.current_prompt_field == ("crm", "name"):
            self._assign_crm_field_from_text("name", text)
        elif self.current_prompt_field == ("crm", "email"):
            self._assign_crm_field_from_text("email", text)
        else:
            # No specific field set yet: seed from free text
            self._extract_crm_info(text)

        if self._is_crm_complete():
            self._add_crm_contact()
            self._clear_pending_crm()
            return True

        # Ask for next single missing field
        self._prompt_next_crm_field()
        return True
    
    def _clear_pending_crm(self):
        """Clear pending CRM state."""
        self.pending_crm = {"name": None, "email": None, "original_query": None}
        self.current_task_type = None
        self.current_prompt_field = None
    
    # ---------- Prompting helpers (one-at-a-time) ----------
    def _prompt_next_email_field(self):
        """Ask for the next missing email field one at a time."""
        missing = self._get_missing_email_info()
        if "recipient email" in missing:
            self.current_prompt_field = ("email", "to")
            self.console.print("❓ Please provide the recipient email address:", style="yellow")
            return
        if "subject" in missing:
            self.current_prompt_field = ("email", "subject")
            self.console.print("❓ What should be the email subject?", style="yellow")
            return
        if "content" in missing:
            self.current_prompt_field = ("email", "content")
            self.console.print("❓ What should be the email content?", style="yellow")
            return

    def _prompt_next_crm_field(self):
        """Ask for the next missing CRM field one at a time."""
        missing = self._get_missing_crm_info()
        if "contact name" in missing:
            self.current_prompt_field = ("crm", "name")
            self.console.print("❓ Please provide the contact name:", style="yellow")
            return
        if "email address" in missing:
            self.current_prompt_field = ("crm", "email")
            self.console.print("❓ Please provide the contact email address:", style="yellow")
            return

    # ---------- Strict field assignment ----------
    def _assign_email_field_from_text(self, field: str, text: str):
        """Assign text to a specific email field with validation."""
        import re
        if field == "to":
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            match = re.search(email_pattern, text)
            if match:
                self.pending_email["to"] = match.group(0)
                self.console.print(f"✅ Got recipient: {match.group(0)}", style="green")
            else:
                self.console.print("⚠️ That doesn't look like a valid email. Please enter a valid recipient email:", style="yellow")
        elif field == "subject":
            # Take the whole line as subject, but trim markers and trailing commas
            subj = text.strip()
            # Remove common subject prefixes: "subject:", "subject -", "subject would be", "subject is"
            subj = re.sub(r'^(subject\s*(would\s+be|is|:|-)\s*)', '', subj, flags=re.IGNORECASE).strip()
            subj = re.sub(r'[\s,]+$', '', subj)
            if subj:
                self.pending_email["subject"] = subj
                self.console.print(f"✅ Got subject: {subj}", style="green")
            else:
                self.console.print("⚠️ Please provide a non-empty subject:", style="yellow")
        elif field == "content":
            # Accept either free text or directives like 'summary of JP.txt'
            if any(doc_indicator in text.lower() for doc_indicator in ["jp.txt", "document", ".txt", ".md", ".pdf"]):
                # Process document with LLM based on user requirements
                try:
                    processed_content = self._process_document_request(text)
                    if processed_content:
                        self.pending_email["content"] = processed_content
                        self.console.print(f"✅ Got processed content ({len(processed_content)} characters)", style="green")
                        return
                except Exception as e:
                    self.console.print(f"❌ Error processing document: {str(e)}", style="red")
            
            if len(text.strip()) > 10:
                self.pending_email["content"] = text.strip()
                self.console.print(f"✅ Got content ({len(text.strip())} characters)", style="green")
            else:
                self.console.print("⚠️ Please provide the email content:", style="yellow")

    def _process_document_request(self, text: str) -> str:
        """Process document content based on user requirements using LLM."""
        import re
        
        # Extract document file name
        document_file = None
        words = text.split()
        for word in words:
            clean_word = word.strip('.,!?()[]{}":;')
            if '.' in clean_word and any(clean_word.lower().endswith(ext) for ext in ['.txt', '.md', '.pdf', '.doc', '.docx']):
                if (self.documents_dir / clean_word).exists():
                    document_file = clean_word
                    break
        
        # If no specific file found, look for jp.txt or any document
        if not document_file:
            if "jp.txt" in text.lower() and (self.documents_dir / "JP.txt").exists():
                document_file = "JP.txt"
            elif "document" in text.lower():
                # Find first available document
                for file_path in self.documents_dir.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in ['.txt', '.md', '.pdf']:
                        document_file = file_path.name
                        break
        
        if not document_file:
            return "Document not found."
        
        # Load document content
        try:
            doc_path = self.documents_dir / document_file
            raw_content = doc_path.read_text(encoding='utf-8').strip()
            self.console.print(f"✅ Loaded content from {document_file} ({len(raw_content)} characters)", style="green")
            
            # Process based on user requirements
            return self._generate_processed_content(raw_content, text)
            
        except Exception as e:
            return f"Error loading document: {str(e)}"
    
    def _generate_processed_content(self, raw_content: str, user_request: str) -> str:
        """Generate processed content using LLM based on user requirements."""
        import re
        
        if not self.llm or not self.llm.is_available():
            return "LLM not available for content processing."
        
        request_lower = user_request.lower()
        
        try:
            # Determine processing type based on user requirement
            if any(word in request_lower for word in ["bullet", "points"]):
                # Extract number of bullet points
                bullet_match = re.search(r'(\d+)\s*(?:bullet\s*)?points?', request_lower)
                num_points = bullet_match.group(1) if bullet_match else "5"
                
                prompt = f"""Please create {num_points} key bullet points from the following content for an email:

{raw_content}

Make it:
- Professional and clear
- {num_points} concise bullet points
- Highlight the most important information
- Suitable for email communication

Format as:
• Point 1
• Point 2
etc.

Key Points:"""
                
            elif any(word in request_lower for word in ["line", "lines"]):
                # Extract number of lines
                line_match = re.search(r'(\d+)\s*lines?', request_lower)
                num_lines = line_match.group(1) if line_match else "3"
                
                prompt = f"""Please create a {num_lines}-line professional summary of the following content for an email:

{raw_content}

Make it:
- Exactly {num_lines} lines
- Professional and engaging
- Concise and impactful
- Suitable for email communication

{num_lines}-line summary:"""
                
            elif any(word in request_lower for word in ["summary", "summarize"]):
                prompt = f"""Please create a concise professional summary of the following content for an email:

{raw_content}

Make it:
- Professional and engaging
- Concise (2-3 paragraphs max)
- Suitable for email communication
- Highlight key achievements and skills

Summary:"""
                
            else:
                # Default to summary
                prompt = f"""Please create a professional summary of the following content for an email:

{raw_content}

Make it professional and suitable for email communication.

Summary:"""
            
            response = self.llm.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return f"Error processing content with LLM: {str(e)}"

    def _assign_crm_field_from_text(self, field: str, text: str):
        """Assign text to a specific CRM field with validation."""
        import re
        if field == "email":
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            match = re.search(email_pattern, text)
            if match:
                self.pending_crm["email"] = match.group(0)
                self.console.print(f"✅ Got email: {match.group(0)}", style="green")
            else:
                self.console.print("⚠️ That doesn't look like a valid email. Please enter a valid contact email:", style="yellow")
        elif field == "name":
            name = text.strip()
            name = re.sub(r'^(name\s*(is)?\s*[-:]?)', '', name, flags=re.IGNORECASE).strip()
            name = name.strip('"\' ')
            if name:
                self.pending_crm["name"] = name
                self.console.print(f"✅ Got name: {name}", style="green")
            else:
                self.console.print("⚠️ Please provide a non-empty name:", style="yellow")
    
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
            # Look for patterns like "subject: X", "subject - X", "subject would be X", "subject is X"
            subject_match = re.search(r'subject\s*(?:would\s+be|is|:|-)\s*([^,.\n]+?)(?:\s*,|\s*$)', text, re.IGNORECASE)
            if subject_match and not self.pending_email["subject"]:
                self.pending_email["subject"] = subject_match.group(1).strip()
        
        # Check for document references and load content
        document_extensions = ['.txt', '.md', '.pdf', '.doc', '.docx', '.json', '.csv']
        document_file = None
        
        # Look for specific file mentions or "document" keyword
        if "document" in text.lower():
            # Find first available document
            if self.documents_dir.exists():
                for file_path in self.documents_dir.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in document_extensions:
                        document_file = file_path.name
                        break
        else:
            # Look for specific file mentions
            words = text.split()
            for word in words:
                clean_word = word.strip('.,!?()[]{}":;')
                if '.' in clean_word and any(clean_word.lower().endswith(ext) for ext in document_extensions):
                    potential_file = self.documents_dir / clean_word
                    if potential_file.exists():
                        document_file = clean_word
                        break
        
        if document_file and not self.pending_email["content"]:
            try:
                doc_path = self.documents_dir / document_file
                raw_content = doc_path.read_text(encoding='utf-8').strip()
                
                # Store raw content - LLM processing now handled in hybrid approach
                self.pending_email["content"] = raw_content
                
                self.console.print(f"✅ Loaded content from {document_file} ({len(raw_content)} characters)", style="green")
            except Exception as e:
                self.console.print(f"⚠️ Could not load {document_file}: {e}", style="yellow")
        
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
        table.add_row("📋 Email System", "✅ Ready", "Hybrid deterministic + LLM approach")
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
                self._prompt_next_crm_field()
        
        # EMAIL DETECTION
        elif any(word in query_lower for word in ["send email", "email to", "send mail"]) or (any(word in query_lower for word in ["email", "send", "mail"]) and not any(word in query_lower for word in ["contact", "crm", "pipedrive"])):
            # Always use hybrid approach: deterministic extraction + LLM for body
            self._handle_email_hybrid(user_query)
        
        # CALENDLY DETECTION  
        elif any(word in query_lower for word in ["calendar", "meeting", "schedule", "available", "calendly"]):
            self.current_task_type = "calendly"
            self._handle_calendly_request(user_query)
        
        # GENERAL
        else:
            self.console.print("Hello! I can help you with:\n• 📧 Email (Gmail)\n• 👥 Contacts (Pipedrive CRM)\n• 📅 Calendar (Calendly)\n\nWhat would you like to do?", style="cyan")
    
    

    

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
    
    def _handle_email_hybrid(self, user_query: str):
        """Handle email requests using hybrid approach: deterministic extraction + LLM for body."""
        self.current_task_type = "email"
        self.pending_email["original_query"] = user_query
        
        # Deterministic extraction of all email components
        email_data = self._extract_email_data_deterministic(user_query)
        
        # Store extracted data
        if email_data["to"]:
            self.pending_email["to"] = email_data["to"]
        if email_data["subject"]:
            self.pending_email["subject"] = email_data["subject"]
        
        # Check if we have recipient
        if not self.pending_email["to"]:
            self.current_prompt_field = ("email", "to")
            self.console.print("❓ Please provide the recipient email address:", style="yellow")
            # Store content requirement for later LLM processing
            self.pending_email["content_requirement"] = email_data["content_requirement"]
            self.pending_email["document_reference"] = email_data["document_reference"]
            return
        
        # Generate body using LLM
        try:
            body = self._generate_email_body_with_llm(
                user_query, 
                email_data["content_requirement"], 
                email_data["document_reference"]
            )
            self.pending_email["content"] = body
            
            # Generate subject if not provided
            if not self.pending_email["subject"]:
                self.pending_email["subject"] = self._generate_subject_from_query(user_query, body)
            
            # Send email
            self._send_email()
            self._clear_pending_email()
            
        except Exception as e:
            self.console.print(f"❌ Error generating email content: {str(e)}", style="red")
    
    def _extract_email_data_deterministic(self, query: str) -> dict:
        """Extract email components using deterministic patterns."""
        import re
        
        result = {
            "to": None,
            "subject": None,
            "content_requirement": None,
            "document_reference": None
        }
        
        # Extract recipient email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, query)
        if email_match:
            result["to"] = email_match.group(0)
        
        # Extract subject
        subject_match = re.search(r'subject\s*(?:would\s+be|is|:|-)\s*([^,.\n]+?)(?:\s*,|\s*with|\s*$)', query, re.IGNORECASE)
        if subject_match:
            result["subject"] = subject_match.group(1).strip()
        
        # Extract document reference - look for any file with common extensions
        import os
        document_extensions = ['.txt', '.md', '.pdf', '.doc', '.docx', '.json', '.csv']
        
        # Check for explicit "document" keyword
        if "document" in query.lower():
            # Look for available documents in the directory
            if hasattr(self, 'documents_dir') and self.documents_dir.exists():
                for file_path in self.documents_dir.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in document_extensions:
                        result["document_reference"] = file_path.name
                        break
        else:
            # Look for specific file mentions (e.g., "resume.txt", "profile.md", etc.)
            words = query.split()
            for word in words:
                # Remove punctuation and check if it looks like a filename
                clean_word = word.strip('.,!?()[]{}":;')
                if '.' in clean_word and any(clean_word.lower().endswith(ext) for ext in document_extensions):
                    # Verify the file exists
                    if hasattr(self, 'documents_dir'):
                        potential_file = self.documents_dir / clean_word
                        if potential_file.exists():
                            result["document_reference"] = clean_word
                            break
        
        # Extract content requirements
        query_lower = query.lower()
        content_requirements = []
        
        # Check for bullet points with numbers
        bullet_match = re.search(r'(\d+)\s*(?:bullet\s*)?points?', query_lower)
        if bullet_match:
            content_requirements.append(f"{bullet_match.group(1)} bullet points")
        elif any(word in query_lower for word in ["bullet", "points", "list"]):
            content_requirements.append("bullet points")
        
        # Check for other content types
        if any(word in query_lower for word in ["summary", "summarize", "summarise"]):
            content_requirements.append("summary")
        elif any(word in query_lower for word in ["brief", "short", "concise"]):
            content_requirements.append("brief")
        elif any(word in query_lower for word in ["highlight", "key", "important", "main"]):
            content_requirements.append("highlights")
        elif any(word in query_lower for word in ["overview", "intro", "introduction"]):
            content_requirements.append("overview")
        
        if content_requirements:
            result["content_requirement"] = " ".join(content_requirements)
        
        return result
    
    def _generate_email_body_with_llm(self, user_query: str, content_requirement: str, document_reference: str) -> str:
        """Generate email body using LLM based on requirements."""
        try:
            if not self.llm:
                return "Email content based on your request."
            
            # Load document content if referenced
            document_content = ""
            if document_reference:
                doc_path = self.documents_dir / document_reference
                if doc_path.exists():
                    document_content = doc_path.read_text(encoding='utf-8').strip()
            
            # Create prompt based on requirements
            if content_requirement and document_content:
                prompt = self._create_content_prompt(content_requirement, document_content, user_query)
            elif document_content:
                prompt = f"""Create professional email content based on the following document:

{document_content}

Make it suitable for email communication, professional and engaging."""
            else:
                prompt = f"""Create professional email content based on this request: {user_query}

Make it professional, clear, and suitable for email communication."""
            
            response = self.llm.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return f"Error generating content: {str(e)}"
    
    def _create_content_prompt(self, requirement: str, document_content: str, user_query: str) -> str:
        """Create specific prompt based on content requirement."""
        if "bullet points" in requirement:
            # Extract number if specified
            import re
            number_match = re.search(r'(\d+)', requirement)
            num_points = number_match.group(1) if number_match else "5"
            
            return f"""Create {num_points} professional bullet points from the following content for an email:

{document_content}

Format as:
• Point 1
• Point 2
etc.

Make them concise, professional, and suitable for email communication."""
        
        elif "summary" in requirement:
            return f"""Create a professional summary of the following content for an email:

{document_content}

Make it:
- Professional and engaging
- 2-3 paragraphs maximum
- Suitable for email communication
- Highlight key achievements and information"""
        
        elif "brief" in requirement:
            return f"""Create a brief, professional version of the following content for an email:

{document_content}

Make it:
- Very concise (1-2 paragraphs)
- Professional tone
- Include only the most important points"""
        
        elif "highlights" in requirement:
            return f"""Extract the key highlights from the following content for an email:

{document_content}

Make it:
- Professional and engaging
- 3-4 key highlights
- Focus on most important achievements
- Suitable for email communication"""
        
        elif "overview" in requirement:
            return f"""Create a professional overview from the following content for an email:

{document_content}

Make it:
- Professional introduction style
- 1-2 paragraphs
- Focus on background and key qualifications
- Suitable for email communication"""
        
        else:
            return f"""Create professional email content based on: {user_query}

Using this content: {document_content}

Make it professional, clear, and suitable for email communication."""
    
    def _generate_subject_from_query(self, user_query: str, body: str) -> str:
        """Generate subject line from query and body."""
        try:
            if not self.llm:
                return "Email Subject"
            
            prompt = f"""Based on this email request and content, suggest a professional email subject line:

Request: {user_query}
Content preview: {body[:200]}...

Generate a concise, professional subject line (max 8 words):"""
            
            response = self.llm.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.7
            )
            return response.choices[0].message.content.strip().strip('"')
        except:
            return "Email Subject"
    
    def _execute_email_draft(self, email_content: dict):
        """Execute an email draft generated by agents."""
        try:
            if ToolType.GMAIL in self.tool_agents:
                gmail_agent = self.tool_agents[ToolType.GMAIL]
                result = gmail_agent.execute("send_email", {
                    "to": email_content["to"],
                    "subject": email_content["subject"],
                    "content": email_content["body"]
                })
                
                if result.success:
                    self.console.print(f"✅ Email sent to {email_content['to']}", style="green")
                    self.console.print(f"📧 Subject: {email_content['subject']}", style="cyan")
                    self.notifier.send_notification("task_completed", "Email sent successfully!")
                else:
                    self.console.print(f"❌ Failed to send email: {result.error}", style="red")
            else:
                self.console.print("❌ Gmail not configured", style="red")
        except Exception as e:
            self.console.print(f"❌ Error sending email: {str(e)}", style="red")


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
