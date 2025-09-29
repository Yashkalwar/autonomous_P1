"""
Simplified Agents implementation for the workflow system (without CrewAI dependency).
"""
import uuid
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

from contracts import (
    Plan, TaskStep, ToolType, TaskType, Draft, ReviewResult, 
    ConfidenceLevel, NotificationEvent, APICredentials
)
from tools import GmailToolAgent, PipedriveToolAgent, CalendlyToolAgent
from memory import MemoryAgent

try:
    from dateutil import parser as date_parser
except ImportError:
    date_parser = None
    
class PlannerAgent:
    """Agent responsible for breaking down user queries into actionable plans."""

    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    def __init__(self, llm_client=None, documents_dir=None):
        self.role = 'Task Planner'
        self.llm = llm_client
        self.documents_dir = Path(documents_dir) if documents_dir else Path("user_documents")
        self.goal = 'Break down user requests into clear, actionable steps with appropriate tool assignments'
        self.backstory = """You are an expert task planner who excels at understanding user needs 
        and creating structured plans. You identify which tools are needed (Gmail, Pipedrive CRM, Calendly availability checks, or conversational support) 
        and break complex requests into manageable steps."""
    
    def create_plan(self, user_query: str, available_tools: List[ToolType]) -> Plan:
        """Create a structured plan from user query."""
        plan_id = str(uuid.uuid4())
        
        # Analyze the query to determine required tools and steps
        steps = self._analyze_query(user_query, available_tools)
        required_tools = list(set([step.tool_required for step in steps]))
        missing_info = self._identify_missing_info(user_query, steps)
        
        plan = Plan(
            plan_id=plan_id,
            user_query=user_query,
            steps=steps,
            required_tools=required_tools,
            missing_info=missing_info,
            is_complete=len(missing_info) == 0
        )
        
        print(f"📋 [PLANNER] Created plan with {len(steps)} steps, requires tools: {required_tools}")
        if missing_info:
            print(f"❓ [PLANNER] Missing information: {missing_info}")
        
        return plan
    
    def _analyze_query(self, query: str, available_tools: List[ToolType]) -> List[TaskStep]:
        """Analyze user query using LLM to create intelligent task steps."""
        if not self.llm:
            raise RuntimeError("LLM client is required for query analysis but not initialized.")
        
        # Convert ToolType enums to strings for LLM
        available_tool_names = [tool.value for tool in available_tools]
        
        try:
            # Preprocess query to include document content if referenced
            enhanced_query = self._preprocess_query_with_documents(query)
            
            # Get available documents for context
            available_documents = self._get_available_documents()
            
            # Use LLM to analyze the query with document context
            analysis = self.llm.analyze_user_query(enhanced_query, available_tool_names, available_documents)
            
            # Convert tool name back to ToolType enum
            tool_mapping = {
                "gmail": ToolType.GMAIL,
                "pipedrive": ToolType.PIPEDRIVE, 
                "calendly": ToolType.CALENDLY,
                "general": ToolType.GENERAL
            }
            
            primary_tool = tool_mapping.get(analysis["primary_tool"], ToolType.GENERAL)
            
            # Create task step based on LLM analysis
            step = TaskStep(
                step_id=str(uuid.uuid4()),
                description=self._get_step_description(analysis["intent"], primary_tool),
                tool_required=primary_tool,
                parameters=analysis["extracted_parameters"]
            )
            
            return [step]
            
        except RuntimeError as e:
            # If LLM analysis fails, create a general step
            print(f"⚠️ [PLANNER] LLM analysis failed: {e}")
            return [TaskStep(
                step_id=str(uuid.uuid4()),
                description="Process general user request",
                tool_required=ToolType.GENERAL,
                parameters={"action": "general_assistance", "query": query}
            )]
    
    def _get_step_description(self, intent: str, tool: ToolType) -> str:
        """Generate step description based on intent and tool."""
        descriptions = {
            "send_email": "Send email based on user request",
            "create_contact": "Create contact in Pipedrive CRM", 
            "check_calendar": "Check Calendly availability",
            "general_assistance": "Process general user request"
        }
        return descriptions.get(intent, f"Execute {tool.value} task")

    def _get_available_documents(self) -> List[str]:
        """Get list of available documents in the documents directory."""
        try:
            if not self.documents_dir.exists():
                return []
            
            documents = []
            for file_path in self.documents_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in ['.txt', '.md', '.json', '.csv']:
                    documents.append(file_path.name)
            return documents
        except Exception:
            return []
    
    def _load_document_content(self, filename: str) -> str:
        """Load content from a document file."""
        try:
            file_path = self.documents_dir / filename
            if file_path.exists() and file_path.is_file():
                return file_path.read_text(encoding='utf-8').strip()
        except Exception:
            pass
        return ""
    
    def _preprocess_query_with_documents(self, query: str) -> str:
        """Preprocess query to include document content when referenced."""
        # Check if query mentions any available documents
        available_docs = self._get_available_documents()
        
        for doc_name in available_docs:
            # Check if document is mentioned in the query
            if doc_name.lower() in query.lower():
                content = self._load_document_content(doc_name)
                if content:
                    # Add document content to the query
                    query += f"\n\nDocument '{doc_name}' content:\n{content}"
                    break
        
        return query

    def _contains_summary_request(self, query: str) -> bool:
        """Detect whether the user is asking for a summary, allowing minor typos."""
        query_lower = query.lower()
        keyword_hits = [
            "summary",
            "summaries",
            "summarize",
            "summarise",
            "summarizing",
            "summarising",
        ]
        if any(keyword in query_lower for keyword in keyword_hits):
            return True

        tokens = re.findall(r"[a-z]+", query_lower)
        targets = ["summary", "summarize", "summarise"]
        for token in tokens:
            for target in targets:
                if SequenceMatcher(None, token, target).ratio() >= 0.75:
                    return True

        if "sum up" in query_lower or "summ up" in query_lower:
            return True

        if "summ" in query_lower and "note" in query_lower:
            return True

        return False

    def _identify_missing_info(self, query: str, steps: List[TaskStep]) -> List[str]:
        """Use LLM to identify missing information needed to complete the plan."""
        if not self.llm or not steps:
            return []
        
        try:
            # Preprocess query to include document content if referenced
            enhanced_query = self._preprocess_query_with_documents(query)
            
            # Convert ToolType enums to strings for LLM
            available_tool_names = [step.tool_required.value for step in steps]
            
            # Get available documents for context
            available_documents = self._get_available_documents()
            
            # Use LLM analysis to get missing information
            analysis = self.llm.analyze_user_query(enhanced_query, available_tool_names, available_documents)
            missing_info = analysis.get("missing_information", [])
            
            # Store the follow-up question for later use
            if hasattr(self, '_current_analysis'):
                self._current_analysis = analysis
            else:
                self._current_analysis = analysis
            
            return missing_info
            
        except RuntimeError as e:
            print(f"⚠️ [PLANNER] LLM missing info detection failed: {e}")
            # Fallback to basic validation
            missing = []
            for step in steps:
                if step.tool_required == ToolType.GMAIL:
                    if not step.parameters.get("to"):
                        missing.append("email recipient")
                    if not step.parameters.get("subject") and not step.parameters.get("email_content_purpose"):
                        missing.append("email subject and content purpose")
                elif step.tool_required == ToolType.PIPEDRIVE:
                    if not step.parameters.get("email") or not step.parameters.get("name"):
                        missing.append("contact details (name and email)")
            return missing

class DeliberationCore:
    """Core agent responsible for generating drafts based on plans."""
    
    def __init__(self, llm_client=None):
        self.role = 'Content Generator'
        self.llm = llm_client
        self.goal = 'Generate high-quality drafts for emails, CRM entries, availability updates, and conversational responses based on structured plans'
        self.backstory = """You are a skilled content creator who can generate professional emails, 
        CRM logs, Calendly availability summaries, and conversational updates. You follow plans precisely 
        and create content that is clear, professional, and actionable."""
    
    def generate_draft(self, plan: Plan) -> Draft:
        """Generate a draft based on the provided plan."""
        draft_id = str(uuid.uuid4())
        
        # Determine the primary task type
        task_type = self._determine_task_type(plan)
        
        # Generate content based on the task type
        content = self._generate_content(plan, task_type)
        
        draft = Draft(
            draft_id=draft_id,
            plan_id=plan.plan_id,
            task_type=task_type,
            content=content,
            metadata={
                "generated_at": datetime.now().isoformat(),
                "plan_steps_count": len(plan.steps),
                "user_query": plan.user_query
            }
        )
        
        print(f"📝 [DELIBERATION] Generated {task_type} draft: {draft_id}")
        
        return draft
    
    def _determine_task_type(self, plan: Plan) -> TaskType:
        """Determine the primary task type from the plan."""
        # Count tool types in steps
        tool_counts = {}
        for step in plan.steps:
            tool_counts[step.tool_required] = tool_counts.get(step.tool_required, 0) + 1
        
        # Map most common tool to task type
        if not tool_counts:
            return TaskType.EMAIL
        
        most_common_tool = max(tool_counts, key=tool_counts.get)
        
        if most_common_tool == ToolType.GMAIL:
            return TaskType.EMAIL
        elif most_common_tool == ToolType.PIPEDRIVE:
            return TaskType.CRM_CONTACT
        elif most_common_tool == ToolType.GENERAL:
            return TaskType.GENERAL_RESPONSE
        else:
            return TaskType.GENERAL_RESPONSE
    
    def _generate_content(self, plan: Plan, task_type: TaskType) -> Dict[str, Any]:
        """Generate content based on task type."""
        if task_type == TaskType.EMAIL:
            return self._generate_email_content(plan)
        elif task_type == TaskType.CRM_CONTACT:
            return self._generate_crm_content(plan)
        elif task_type == TaskType.GENERAL_RESPONSE:
            return self._generate_general_content(plan)
        else:
            return {"content": "General response based on user query", "query": plan.user_query}
    
    def _generate_email_content(self, plan: Plan) -> Dict[str, Any]:
        """Generate email content using LLM (required)."""
        # Find email-related steps
        email_steps = [step for step in plan.steps if step.tool_required == ToolType.GMAIL]
        
        if not email_steps:
            raise RuntimeError("No email steps found in plan. Cannot generate email content.")
        
        step = email_steps[0]
        # Handle different parameter names for recipient
        to_value = step.parameters.get("to") or step.parameters.get("recipient") or step.parameters.get("recipient_email")
        if not to_value:
            raise RuntimeError("Email recipient is required but not specified. Please provide the recipient email address.")
            
        subject_hint = step.parameters.get("subject")
        summary_text = step.parameters.get("summary_content") or step.parameters.get("content")

        if not self.llm:
            raise RuntimeError("LLM client is required for email generation but not initialized. Please check your OpenAI configuration.")

        try:
            llm_content = self.llm.generate_email_content(
                plan.user_query,
                recipient=to_value,
                existing_subject=subject_hint,
                summary_text=summary_text,
            )
            return {
                "to": to_value,
                "subject": llm_content["subject"],
                "body": llm_content["body"],
            }
        except RuntimeError as e:
            # Re-raise LLM validation errors with helpful context
            raise RuntimeError(f"Email generation failed: {str(e)}. Please try rephrasing your request or check your OpenAI API configuration.")
        except Exception as e:
            raise RuntimeError(f"Unexpected error during email generation: {str(e)}. Please try again or contact support.")
    
    def _generate_crm_content(self, plan: Plan) -> Dict[str, Any]:
        """Generate CRM content."""
        crm_steps = [step for step in plan.steps if step.tool_required == ToolType.PIPEDRIVE]

        if not crm_steps:
            return {
                "content": "No CRM actions found in plan",
                "query": plan.user_query
            }
        
        step = crm_steps[0]
        action = step.parameters.get("action", "create_contact")
        
        # Return the parameters as-is for Pipedrive tool to handle
        crm_payload = {
            key: value
            for key, value in step.parameters.items()
            if value is not None
        }
        
        # Ensure action is set
        crm_payload["action"] = action
        
        return crm_payload

    def _generate_general_content(self, plan: Plan) -> Dict[str, Any]:
        """Generate conversational response content."""
        general_steps = [step for step in plan.steps if step.tool_required == ToolType.GENERAL]
        query = plan.user_query
        step = general_steps[0] if general_steps else None
        prompt = step.parameters.get("query") if step else query

        if self.llm and self.llm.is_available():
            message = self.llm.generate_general_response(prompt or query)
            if message:
                return {"message": message.strip(), "action": step.parameters.get("action") if step else "general_assistance"}

        fallback = "Here's what I can help with right now: Gmail for email tasks, Pipedrive for CRM contact management, and Calendly availability lookups. Let me know what you'd like to do."
        return {"message": fallback, "action": step.parameters.get("action") if step else "general_assistance"}
    
class ReviewerAgent:
    """Agent responsible for reviewing and validating drafts."""
    
    def __init__(self, confidence_threshold: float = 0.7, llm_client=None):
        self.confidence_threshold = confidence_threshold
        self.role = 'Quality Reviewer'
        self.llm = llm_client
        self.goal = 'Review drafts for quality, completeness, and potential issues before execution'
        self.backstory = """You are a meticulous quality reviewer who ensures all content meets 
        high standards. You check for completeness, professionalism, and potential issues 
        that could cause problems during execution."""
    
    def review_draft(self, draft: Draft) -> ReviewResult:
        """Review a draft and provide feedback."""
        issues = []
        suggestions = []
        confidence_score = 1.0
        
        # Review based on task type
        if draft.task_type == TaskType.EMAIL:
            issues, suggestions, confidence_score = self._review_email(draft)
        elif draft.task_type == TaskType.CRM_CONTACT:
            issues, suggestions, confidence_score = self._review_crm(draft)
        elif draft.task_type == TaskType.GENERAL_RESPONSE:
            issues, suggestions, confidence_score = self._review_general(draft)
        
        # Determine confidence level
        if confidence_score >= 0.8:
            confidence_level = ConfidenceLevel.HIGH
        elif confidence_score >= 0.6:
            confidence_level = ConfidenceLevel.MEDIUM
        else:
            confidence_level = ConfidenceLevel.LOW
        
        # Determine if user review is required
        requires_user_review = confidence_score < self.confidence_threshold or len(issues) > 0
        approved = confidence_score >= self.confidence_threshold and len(issues) == 0
        
        result = ReviewResult(
            draft_id=draft.draft_id,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            issues=issues,
            suggestions=suggestions,
            approved=approved,
            requires_user_review=requires_user_review
        )
        
        print(f"🔍 [REVIEWER] Draft {draft.draft_id} - Score: {confidence_score:.2f}, Approved: {approved}")
        if issues:
            print(f"⚠️ [REVIEWER] Issues found: {issues}")
        
        return result
    
    def _review_email(self, draft: Draft) -> tuple[List[str], List[str], float]:
        """Review email draft."""
        issues = []
        suggestions = []
        confidence_score = 1.0
        
        content = draft.content
        
        # Check required fields
        if not content.get("to"):
            issues.append("Missing recipient email address")
            confidence_score -= 0.3
        
        if not content.get("subject"):
            issues.append("Missing email subject")
            confidence_score -= 0.2
        
        if not content.get("body") or len(content.get("body", "")) < 10:
            issues.append("Email body is too short or missing")
            confidence_score -= 0.3
        
        # Check email format
        if content.get("to") and "@" not in content["to"]:
            issues.append("Invalid email address format")
            confidence_score -= 0.2
        
        # Suggestions
        if content.get("body") and "placeholder" in content["body"].lower():
            suggestions.append("Replace placeholder text with actual content")
            confidence_score -= 0.1
        
        return issues, suggestions, max(0.0, confidence_score)
    
    def _review_crm(self, draft: Draft) -> tuple[List[str], List[str], float]:
        """Review CRM draft."""
        issues = []
        suggestions = []
        confidence_score = 1.0
        
        content = draft.content
        action = content.get("action", "create_contact")
        
        # Action-specific validations
        if action == "create_contact":
            if not content.get("name") and not content.get("email"):
                issues.append("Missing contact name or email")
                confidence_score -= 0.4
            if content.get("email") and "@" not in content["email"]:
                issues.append("Invalid email format")
                confidence_score -= 0.2
        elif action == "update_contact":
            if not content.get("contact_id"):
                issues.append("Missing contact ID for update")
                confidence_score -= 0.4
        elif action == "search_contacts":
            if not content.get("query"):
                issues.append("Missing search query")
                confidence_score -= 0.3

        # General validations
        if "email" in content and content.get("email") and "@" not in content["email"]:
            issues.append("Invalid email format")
            confidence_score -= 0.2
        
        # Check for placeholder values
        if "placeholder" in str(content).lower():
            suggestions.append("Replace placeholder values with actual data")
            confidence_score -= 0.2
        
        # Positive suggestions
        if action == "create_contact" and content.get("email") and not content.get("phone"):
            suggestions.append("Consider adding phone number for better contact info")
        
        if action in ["create_contact", "update_contact"] and not content.get("notes"):
            suggestions.append("Consider adding notes for context")
        
        return issues, suggestions, max(0.0, confidence_score)

    def _review_general(self, draft: Draft) -> tuple[List[str], List[str], float]:
        """Review general response drafts."""
        issues: List[str] = []
        suggestions: List[str] = []
        content = draft.content
        message = content.get("message", "").strip()

        if not message:
            issues.append("Missing response message")
            return issues, suggestions, 0.4

        if len(message) < 5:
            issues.append("Response is too short")
            return issues, suggestions, 0.6

        return issues, suggestions, 1.0

class NotifierAgent:
    """Agent responsible for sending notifications about task progress."""
    
    def __init__(self):
        self.notifications = []
    
    def send_notification(self, event_type: str, message: str, details: Dict[str, Any] = None) -> NotificationEvent:
        """Send a notification event."""
        notification = NotificationEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            message=message,
            details=details or {}
        )
        
        self.notifications.append(notification)
        
        # Print notification to CLI
        emoji_map = {
            "task_started": "🚀",
            "task_completed": "✅",
            "task_failed": "❌",
            "user_input_required": "❓"
        }
        
        emoji = emoji_map.get(event_type, "📢")
        print(f"{emoji} [NOTIFICATION] {message}")
        
        return notification
    
    def get_recent_notifications(self, limit: int = 10) -> List[NotificationEvent]:
        """Get recent notifications."""
        return self.notifications[-limit:] if self.notifications else []
