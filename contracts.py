"""
Typed contracts for agents and tools in the CrewAI workflow system.
"""
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field
from enum import Enum


class ToolType(str, Enum):
    GMAIL = "gmail"
    PIPEDRIVE = "pipedrive"
    CALENDLY = "calendly"
    GENERAL = "general"


class TaskType(str, Enum):
    EMAIL = "email"
    CRM_CONTACT = "crm_contact"
    GENERAL_RESPONSE = "general_response"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class APICredentials(BaseModel):
    gmail_token: Optional[str] = None
    gmail_token_path: Optional[str] = None
    gmail_address: Optional[str] = None
    gmail_auth_method: Optional[str] = None
    pipedrive_api_token: Optional[str] = None
    pipedrive_domain: Optional[str] = None
    calendly_token: Optional[str] = None
    calendly_event_type_uuid: Optional[str] = None
    calendly_scheduling_link: Optional[str] = None


class TaskStep(BaseModel):
    step_id: str
    description: str
    tool_required: ToolType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)


class Plan(BaseModel):
    plan_id: str
    user_query: str
    steps: List[TaskStep]
    required_tools: List[ToolType]
    missing_info: List[str] = Field(default_factory=list)
    is_complete: bool = False


class Draft(BaseModel):
    draft_id: str
    plan_id: str
    task_type: TaskType
    content: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReviewResult(BaseModel):
    draft_id: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    issues: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    approved: bool = False
    requires_user_review: bool = False


class ToolExecution(BaseModel):
    execution_id: str
    tool_type: ToolType
    action: str
    parameters: Dict[str, Any]
    success: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MemoryEntry(BaseModel):
    entry_id: str
    timestamp: str
    user_query: str
    plan_summary: str
    execution_results: List[ToolExecution]
    sentiment: str = "neutral"
    tags: List[str] = Field(default_factory=list)


class NotificationEvent(BaseModel):
    event_id: str
    timestamp: str
    event_type: Literal["task_started", "task_completed", "task_failed", "user_input_required"]
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
