"""LLM helper utilities for conversational responses and content generation."""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Any

try:
    from openai import OpenAI, OpenAIError
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

    class OpenAIError(Exception):
        pass


class LLMClient:
    """Wrapper around OpenAI responses API with graceful degradation."""

    def __init__(self, model: Optional[str] = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self.enabled = bool(api_key and OpenAI is not None)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client: Optional[OpenAI] = None
        if self.enabled and api_key:
            self.client = OpenAI(api_key=api_key)

    def is_available(self) -> bool:
        return self.enabled and self.client is not None

    def _safe_generate(self, prompt: str, **kwargs) -> Optional[str]:
        if not self.is_available():
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()
        except OpenAIError:
            return None
        except Exception:
            return None
        return None

    def generate_clarification_question(self, user_query: str, missing_points: List[str]) -> str:
        """Produce a friendly follow-up question asking for missing information."""
        if not missing_points:
            return "Could you share a bit more detail?"
        prompt = (
            "You are a friendly assistant chatting with the user. "
            "The user asked: " + json.dumps(user_query) + ". "
            "You still need the following information: " + ", ".join(missing_points) + ". "
            "Ask a single, polite question to collect that information. Keep it short, warm, and end with a question mark."
        )
        generated = self._safe_generate(prompt)
        if generated:
            return generated
        points = ", ".join(missing_points)
        return f"I can take care of that for you. Could you share the {points.lower()}?"

    def generate_email_content(
        self,
        user_query: str,
        recipient: Optional[str],
        existing_subject: Optional[str],
        summary_text: Optional[str],) -> Dict[str, str]:
        """Generate a subject/body pair for an email using the LLM. Raises exception if LLM unavailable."""
        if not self.is_available():
            raise RuntimeError("LLM is required for email generation but is not available. Please check your OpenAI API key.")
        recipient_name = recipient or "there"
        summary_instruction = (
            f"Base the email content on this information: {summary_text}"
            if summary_text
            else "Create appropriate professional content based on the context."
        )
        
        prompt = (
            "You are a professional email writer. Create a polished, business-appropriate email.\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "- DO NOT include the raw user request in the email body\n"
            "- DO NOT reference 'the user asked me to...' or similar phrases\n"
            "- Write as if YOU are the sender, not an assistant\n"
            "- Use proper email structure: greeting, context, main content, closing\n"
            "- Keep it concise but complete\n"
            "- Use professional, warm tone\n\n"
            f"Context for email creation: {user_query}\n"
            f"Recipient: {recipient_name}\n"
            f"Subject hint: {existing_subject or 'Create appropriate subject'}\n"
            f"{summary_instruction}\n\n"
            "Return a JSON object with keys 'subject' and 'body'. "
            "The subject should be clear and specific. "
            "The body should be a complete, professional email with proper greeting and closing."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content
                data = json.loads(text)
                subject = data.get("subject")
                body = data.get("body")
                
                if subject and body:
                    # Content validation - check for raw user query leakage
                    self._validate_email_content(user_query, subject, body)
                    return {"subject": subject.strip(), "body": body.strip()}
                else:
                    raise RuntimeError("LLM failed to generate complete email content (missing subject or body)")
        except (OpenAIError, json.JSONDecodeError, AttributeError) as e:
            raise RuntimeError(f"LLM email generation failed: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error in email generation: {str(e)}")

    def generate_general_response(self, user_query: str) -> Optional[str]:
        """Generate a conversational response for general user queries."""
        prompt = (
            "You are a helpful operations assistant. Respond to the following user request "
            "with a concise, friendly message. Mention available capabilities (Gmail email support, HubSpot CRM, and Calendly availability suggestions) if relevant.\n"
            f"User request: {user_query}"
        )
        return self._safe_generate(prompt)
    
    def _validate_email_content(self, user_query: str, subject: str, body: str) -> None:
        """Validate that email content is professional and doesn't contain raw user queries."""
        # Check for raw user query in email body
        query_words = set(user_query.lower().split())
        body_lower = body.lower()
        
        # Check if too many words from user query appear consecutively in body
        query_phrases = [phrase.strip() for phrase in user_query.lower().split(',') if len(phrase.strip()) > 10]
        for phrase in query_phrases:
            if phrase in body_lower:
                raise RuntimeError(f"Email content contains raw user request. Please rephrase your request more naturally.")
        
        # Check for assistant-like language
        problematic_phrases = [
            "the user asked", "user request", "you asked me to", "as requested by",
            "the user wants", "user query", "based on your request to"
        ]
        
        for phrase in problematic_phrases:
            if phrase in body_lower:
                raise RuntimeError(f"Email content sounds like an assistant response. Please try rephrasing your request.")
        
        # Basic professionalism checks
        if len(subject.strip()) < 3:
            raise RuntimeError("Email subject is too short or empty")
        
        if len(body.strip()) < 20:
            raise RuntimeError("Email body is too short to be professional")
        
        # Check for proper email structure (should have some greeting and closing)
        if not any(greeting in body_lower for greeting in ['hello', 'hi', 'dear', 'greetings']):
            raise RuntimeError("Email lacks proper greeting")
        
        if not any(closing in body_lower for closing in ['regards', 'sincerely', 'best', 'thank you', 'thanks']):
            raise RuntimeError("Email lacks proper closing")

    def analyze_user_query(self, query: str, available_tools: List[str], available_documents: List[str] = None) -> Dict[str, Any]:
        """Analyze user query using LLM to determine intent, extract parameters, and identify missing info."""
        if not self.is_available():
            raise RuntimeError("LLM is required for query analysis but is not available. Please check your OpenAI API key.")
        
        tools_description = {
            "gmail": "Send emails via Gmail",
            "pipedrive": "Manage contacts in Pipedrive CRM (create, update contacts)",
            "calendly": "Check Calendly availability and share scheduling links",
            "general": "General conversation and assistance"
        }
        
        available_tools_desc = [f"- {tool}: {tools_description.get(tool, 'Unknown tool')}" for tool in available_tools]
        
        # Add document context if available
        document_context = ""
        if available_documents:
            document_context = f"\n\nAvailable documents: {', '.join(available_documents)}\n" \
                             f"If the user mentions any of these documents, you can assume their content is available for processing."
        
        prompt = (
            "You are an intelligent task planner. Analyze the user's request and determine what they want to do.\n\n"
            "Available tools:\n" + "\n".join(available_tools_desc) + document_context + "\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- Determine the user's primary intent\n"
            "- Extract any parameters mentioned in the request\n"
            "- Identify what information is missing to complete the task\n"
            "- For emails: ALWAYS require subject and content/purpose if not provided\n"
            "- For CRM: ALWAYS require contact details (name, email, etc.)\n"
            "- For calendar: Determine what kind of scheduling help they need\n"
            "- If user mentions a document that's available, consider the task complete for document processing\n\n"
            f"User request: {query}\n\n"
            "Return a JSON object with this exact structure:\n"
            "{\n"
            '  "intent": "send_email|create_contact|check_calendar|general_assistance",\n'
            '  "primary_tool": "gmail|pipedrive|calendly|general",\n'
            '  "confidence": 0.0-1.0,\n'
            '  "extracted_parameters": {\n'
            '    "key": "value"\n'
            '  },\n'
            '  "missing_information": [\n'
            '    "list of missing required info"\n'
            '  ],\n'
            '  "follow_up_question": "Natural question to ask user for missing info (or null if complete)"\n'
            "}\n\n"
            "Examples of missing_information:\n"
            '- For emails: ["email_subject", "email_content_purpose"]\n'
            '- For contacts: ["contact_name", "contact_email"]\n'
            '- For calendar: ["specific_date", "meeting_purpose"]'
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content
                analysis = json.loads(text)
                
                # Validate required fields
                required_fields = ["intent", "primary_tool", "confidence", "extracted_parameters", "missing_information"]
                for field in required_fields:
                    if field not in analysis:
                        raise RuntimeError(f"LLM analysis missing required field: {field}")
                
                return analysis
            else:
                raise RuntimeError("LLM failed to analyze user query")
        except (OpenAIError, json.JSONDecodeError, AttributeError) as e:
            raise RuntimeError(f"LLM query analysis failed: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error in query analysis: {str(e)}")
