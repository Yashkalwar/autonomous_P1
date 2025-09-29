"""
Tool Agents for Gmail, HubSpot, and Calendly integration.
"""
import ssl
import smtplib
import json
from base64 import urlsafe_b64encode
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone, time, date
import pytz

import requests
from contracts import ToolExecution, ToolType, APICredentials

# Optional imports for Gmail API
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    build = None
    HttpError = None
    Request = None
    Credentials = None

# Optional imports for Pipedrive API
try:
    from pipedrive.client import Client as PipedriveClient
except ImportError:
    PipedriveClient = None


class ToolAgent:
    """Base class for all tool agents."""
    
    def __init__(self, credentials: APICredentials):
        self.credentials = credentials
    
    def execute(self, action: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Execute a tool action and return the result."""
        raise NotImplementedError


class GmailToolAgent(ToolAgent):
    """Gmail integration tool agent."""
    
    def __init__(self, credentials: APICredentials):
        super().__init__(credentials)
        self.tool_type = ToolType.GMAIL
        self.outbox_dir = Path("memory_db") / "outbox"
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
    
    def execute(self, action: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Execute Gmail actions."""
        execution_id = f"gmail_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            if action == "send_email":
                return self._send_email(execution_id, parameters)
            else:
                raise ValueError(f"Unknown Gmail action: {action}")
                
        except Exception as e:
            return ToolExecution(
                execution_id=execution_id,
                tool_type=self.tool_type,
                action=action,
                parameters=parameters,
                success=False,
                error=str(e)
            )
    
    GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

    def _send_email(self, execution_id: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Send an email using SMTP or Gmail API when available."""
        required_params = ['to', 'subject', 'body']
        for param in required_params:
            if not parameters.get(param):
                raise ValueError(f"Missing required parameter: {param}")

        from_address = parameters.get('from') or getattr(self.credentials, 'gmail_address', None)
        if not from_address:
            raise ValueError("Missing sender email address. Provide 'from' parameter or configure gmail_address in credentials.")

        message = EmailMessage()
        message['Subject'] = parameters['subject']
        message['From'] = from_address
        message['To'] = parameters['to']

        cc_field = parameters.get('cc')
        if cc_field:
            if isinstance(cc_field, str):
                cc_recipients = [addr.strip() for addr in cc_field.split(',') if addr.strip()]
            else:
                cc_recipients = [str(addr).strip() for addr in cc_field if str(addr).strip()]
            if cc_recipients:
                message['Cc'] = ', '.join(cc_recipients)
        else:
            cc_recipients = []

        bcc_field = parameters.get('bcc')
        if bcc_field:
            if isinstance(bcc_field, str):
                bcc_recipients = [addr.strip() for addr in bcc_field.split(',') if addr.strip()]
            else:
                bcc_recipients = [str(addr).strip() for addr in bcc_field if str(addr).strip()]
            if bcc_recipients:
                message['Bcc'] = ', '.join(bcc_recipients)
        else:
            bcc_recipients = []

        message.set_content(parameters['body'])

        recipients: list[str] = [parameters['to']]
        recipients.extend(cc_recipients)
        recipients.extend(bcc_recipients)

        delivery_status = 'sent'
        transport = None
        outbox_path: Optional[Path] = None
        note: Optional[str] = None
        success = False

        try:
            if self._can_use_smtp(from_address):
                self._send_via_smtp(from_address, recipients, message)
                transport = 'smtp'
                success = True
                print(f"📧 [GMAIL] Email sent to {parameters['to']} via SMTP")
            elif self._can_use_gmail_api():
                self._send_via_gmail_api(message)
                transport = 'gmail_api'
                success = True
                print(f"📧 [GMAIL] Email sent to {parameters['to']} via Gmail API")
            else:
                raise RuntimeError("No email transport is configured. Provide a Gmail app password or an OAuth token JSON file.")
        except Exception as exc:
            delivery_status = 'queued'
            transport = transport or 'outbox'
            note = str(exc)
            outbox_path = self._write_outbox(execution_id, message)
            print(f"📬 [GMAIL] Email saved to outbox for {parameters['to']}: {note}")
        else:
            note = None

        result = {
            "message_id": f"msg_{execution_id}",
            "from": from_address,
            "to": parameters['to'],
            "subject": parameters['subject'],
            "sent_at": datetime.now().isoformat(),
            "delivery_status": delivery_status if success else 'queued',
            "transport": transport or 'outbox'
        }
        if cc_recipients:
            result['cc'] = cc_recipients
        if bcc_recipients:
            result['bcc'] = bcc_recipients
        if outbox_path:
            result['outbox_path'] = str(outbox_path)
        if note:
            result['note'] = note

        return ToolExecution(
            execution_id=execution_id,
            tool_type=self.tool_type,
            action="send_email",
            parameters=parameters,
            success=success,
            result=result,
            error=note if not success else None
        )

    def _can_use_smtp(self, from_address: Optional[str] = None) -> bool:
        method = getattr(self.credentials, 'gmail_auth_method', None)
        if method and method != 'app_password':
            return False
        token = getattr(self.credentials, 'gmail_token', None)
        sender = from_address or getattr(self.credentials, 'gmail_address', None)
        return bool(token and token != 'demo_gmail_token' and sender)

    def _can_use_gmail_api(self) -> bool:
        if build is None or Credentials is None:
            return False
        method = getattr(self.credentials, 'gmail_auth_method', None)
        inferred_method = method
        token_path = getattr(self.credentials, 'gmail_token_path', None)
        token_value = getattr(self.credentials, 'gmail_token', None)
        if not inferred_method:
            if token_path or (token_value and token_value != 'demo_gmail_token'):
                inferred_method = 'oauth'
        if inferred_method != 'oauth':
            return False
        if token_path and Path(token_path).is_file():
            return True
        if token_value and token_value != 'demo_gmail_token':
            token_candidate = Path(token_value)
            if token_candidate.is_file():
                return True
            try:
                json.loads(token_value)
                return True
            except json.JSONDecodeError:
                return False
        return False

    def _load_gmail_credentials(self) -> Credentials:
        if Credentials is None:
            raise RuntimeError("Gmail OAuth support requires google-auth and google-api-python-client packages")
        token_path_str = getattr(self.credentials, 'gmail_token_path', None)
        token_value = getattr(self.credentials, 'gmail_token', None)
        token_path_obj: Optional[Path] = None

        if token_path_str:
            token_path_obj = Path(token_path_str)
            if not token_path_obj.is_file():
                raise ValueError(f"Stored Gmail OAuth token not found at {token_path_str}")
            creds = Credentials.from_authorized_user_file(str(token_path_obj), self.GMAIL_SCOPES)
        else:
            if not token_value:
                raise ValueError("Gmail OAuth token not provided")
            token_candidate = Path(token_value)
            if token_candidate.is_file():
                token_path_obj = token_candidate
                creds = Credentials.from_authorized_user_file(str(token_candidate), self.GMAIL_SCOPES)
            else:
                try:
                    creds_data = json.loads(token_value)
                except json.JSONDecodeError as exc:
                    raise ValueError("Invalid Gmail OAuth token JSON provided") from exc
                creds = Credentials.from_authorized_user_info(creds_data, scopes=self.GMAIL_SCOPES)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                if Request is None:
                    raise RuntimeError("google-auth transport is not available to refresh credentials")
                creds.refresh(Request())
                if token_path_obj:
                    token_path_obj.write_text(creds.to_json(), encoding='utf-8')
            else:
                raise RuntimeError("Provided Gmail credentials are invalid or expired")
        return creds

    def _send_via_smtp(self, from_address: str, recipients: list[str], message: EmailMessage) -> None:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(from_address, self.credentials.gmail_token)
            server.sendmail(from_address, recipients, message.as_string())

    def _send_via_gmail_api(self, message: EmailMessage) -> None:
        if build is None:
            raise RuntimeError("google-api-python-client is not installed")
        creds = self._load_gmail_credentials()
        try:
            service = build("gmail", "v1", credentials=creds)
            encoded_message = urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()
        except HttpError as exc:
            raise RuntimeError(f"Gmail API error: {exc}") from exc

    def _write_outbox(self, execution_id: str, message: EmailMessage) -> Path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = self.outbox_dir / f"{execution_id}_{timestamp}.eml"
        with open(file_path, 'w', encoding='utf-8') as message_file:
            message_file.write(message.as_string())
        return file_path
    

class PipedriveToolAgent(ToolAgent):
    """Pipedrive CRM integration tool agent."""
    
    def __init__(self, credentials: APICredentials):
        super().__init__(credentials)
        self.tool_type = ToolType.PIPEDRIVE
        self.client = None
        
        api_token = getattr(credentials, "pipedrive_api_token", None)
        domain = getattr(credentials, "pipedrive_domain", None)
        
        if PipedriveClient and api_token and domain:
            try:
                self.client = PipedriveClient(domain=domain)
                self.client.set_api_token(api_token)
                print(f"✅ [PIPEDRIVE] Client initialized successfully")
            except Exception as exc:
                print(f"❌ [PIPEDRIVE] Failed to initialize client: {exc}")
        else:
            print(f"⚠️ [PIPEDRIVE] Missing credentials or library not installed")
    
    def execute(self, action: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Execute Pipedrive actions."""
        execution_id = f"pipedrive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            if action == "create_contact":
                return self._create_contact(execution_id, parameters)
            elif action == "update_contact":
                return self._update_contact(execution_id, parameters)
            elif action == "search_contacts":
                return self._search_contacts(execution_id, parameters)
            elif action == "list_contacts":
                return self._list_contacts(execution_id, parameters)
            else:
                raise ValueError(f"Unknown Pipedrive action: {action}")
        except Exception as e:
            return ToolExecution(
                execution_id=execution_id,
                tool_type=self.tool_type,
                action=action,
                parameters=parameters,
                success=False,
                error=str(e)
            )
    
    def _create_contact(self, execution_id: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Create a new contact (person) in Pipedrive."""
        name = parameters.get('name')
        email = parameters.get('email')
        
        if not name and not email:
            raise ValueError("Missing required parameter: name or email")
        
        # If no name but have email, derive name from email
        if not name and email:
            name_part = email.split('@')[0]
            name = ' '.join(word.capitalize() for word in name_part.replace('.', ' ').replace('_', ' ').split())
        
        # Prepare contact data
        contact_data = {'name': name}
        
        if email:
            contact_data['email'] = [email]
        
        # Add optional fields
        phone = parameters.get('phone')
        if phone:
            contact_data['phone'] = [phone]
            
        linkedin = parameters.get('linkedin')
        notes = parameters.get('notes')
        
        print(f"🔍 [DEBUG] Contact data: {contact_data}")
        print(f"🔍 [DEBUG] Client available: {self.client is not None}")
        
        if self.client:
            try:
                print(f"🔍 [DEBUG] Calling Pipedrive API...")
                response = self.client.persons.create_person(contact_data)
                print(f"🔍 [DEBUG] API Response: {response}")
                
                if response.get('success'):
                    contact = response.get('data', {})
                    result = {
                        "contact_id": contact.get('id'),
                        "name": contact.get('name'),
                        "email": email,
                        "phone": phone,
                        "created_at": datetime.now().isoformat(),
                        "pipedrive_url": f"{self.credentials.pipedrive_domain}/person/{contact.get('id')}"
                    }
                    
                    # Add notes if provided
                    if notes and contact.get('id'):
                        self._add_note_to_contact(contact.get('id'), notes)
                    
                    print(f"💼 [PIPEDRIVE] Contact created: {name} ({email})")
                    return ToolExecution(
                        execution_id=execution_id,
                        tool_type=self.tool_type,
                        action="create_contact",
                        parameters=parameters,
                        success=True,
                        result=result
                    )
                else:
                    error_msg = response.get('error', 'Unknown error creating contact')
                    raise Exception(error_msg)
                    
            except Exception as exc:
                return ToolExecution(
                    execution_id=execution_id,
                    tool_type=self.tool_type,
                    action="create_contact",
                    parameters=parameters,
                    success=False,
                    error=str(exc)
                )
        
        # Fallback simulation when client unavailable
        result = {
            "contact_id": f"sim_{execution_id}",
            "name": name,
            "email": email,
            "phone": phone,
            "created_at": datetime.now().isoformat(),
            "simulated": True
        }
        
        print(f"💼 [PIPEDRIVE] Simulated contact creation: {name}")
        return ToolExecution(
            execution_id=execution_id,
            tool_type=self.tool_type,
            action="create_contact",
            parameters=parameters,
            success=False,
            result=result,
            error="Pipedrive client not available - simulated response"
        )
    
    def _update_contact(self, execution_id: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Update an existing contact in Pipedrive."""
        contact_id = parameters.get('contact_id')
        if not contact_id:
            raise ValueError("Missing required parameter: contact_id")
        
        # Prepare update data
        update_data = {}
        
        name = parameters.get('name')
        if name:
            update_data['name'] = name
            
        email = parameters.get('email')
        if email:
            update_data['email'] = [email]
            
        phone = parameters.get('phone')
        if phone:
            update_data['phone'] = [phone]
        
        if self.client and update_data:
            try:
                response = self.client.persons.update_person(contact_id, update_data)
                
                if response.get('success'):
                    contact = response.get('data', {})
                    result = {
                        "contact_id": contact.get('id'),
                        "name": contact.get('name'),
                        "updated_fields": list(update_data.keys()),
                        "updated_at": datetime.now().isoformat()
                    }
                    
                    # Add notes if provided
                    notes = parameters.get('notes')
                    if notes:
                        self._add_note_to_contact(contact_id, notes)
                    
                    print(f"💼 [PIPEDRIVE] Contact updated: {contact_id}")
                    return ToolExecution(
                        execution_id=execution_id,
                        tool_type=self.tool_type,
                        action="update_contact",
                        parameters=parameters,
                        success=True,
                        result=result
                    )
                else:
                    error_msg = response.get('error', 'Unknown error updating contact')
                    raise Exception(error_msg)
                    
            except Exception as exc:
                return ToolExecution(
                    execution_id=execution_id,
                    tool_type=self.tool_type,
                    action="update_contact",
                    parameters=parameters,
                    success=False,
                    error=str(exc)
                )
        
        # Fallback simulation
        result = {
            "contact_id": contact_id,
            "updated_fields": list(update_data.keys()) if update_data else [],
            "updated_at": datetime.now().isoformat(),
            "simulated": True
        }
        
        print(f"💼 [PIPEDRIVE] Simulated contact update: {contact_id}")
        return ToolExecution(
            execution_id=execution_id,
            tool_type=self.tool_type,
            action="update_contact",
            parameters=parameters,
            success=False,
            result=result,
            error="Pipedrive client not available - simulated response"
        )
    
    def _search_contacts(self, execution_id: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Search contacts by email or name."""
        query = parameters.get('query', '').strip()
        if not query:
            raise ValueError("Missing required parameter: query")
        
        if self.client:
            try:
                search_params = {'term': query}
                response = self.client.persons.search_persons(params=search_params)
                
                if response.get('success'):
                    contacts = []
                    data = response.get('data', {})
                    items = data.get('items', []) if isinstance(data, dict) else []
                    
                    for item in items:
                        person = item.get('item', {})
                        contacts.append({
                            "contact_id": person.get('id'),
                            "name": person.get('name'),
                            "email": self._extract_email(person),
                            "phone": self._extract_phone(person),
                            "organization": person.get('organization', {}).get('name') if person.get('organization') else None
                        })
                    
                    result = {
                        "query": query,
                        "contacts": contacts,
                        "total_results": len(contacts)
                    }
                    
                    print(f"🔍 [PIPEDRIVE] Contact search for '{query}' found {len(contacts)} results")
                    return ToolExecution(
                        execution_id=execution_id,
                        tool_type=self.tool_type,
                        action="search_contacts",
                        parameters=parameters,
                        success=True,
                        result=result
                    )
                else:
                    error_msg = response.get('error', 'Search failed')
                    raise Exception(error_msg)
                    
            except Exception as exc:
                return ToolExecution(
                    execution_id=execution_id,
                    tool_type=self.tool_type,
                    action="search_contacts",
                    parameters=parameters,
                    success=False,
                    error=str(exc)
                )
        
        # Fallback simulation
        result = {
            "query": query,
            "contacts": [
                {
                    "contact_id": "sim_123",
                    "name": f"Sample Contact for {query}",
                    "email": f"{query.lower().replace(' ', '.')}@example.com",
                    "phone": "+1-555-0123",
                    "organization": "Sample Company"
                }
            ],
            "total_results": 1,
            "simulated": True
        }
        
        print(f"🔍 [PIPEDRIVE] Simulated contact search for '{query}'")
        return ToolExecution(
            execution_id=execution_id,
            tool_type=self.tool_type,
            action="search_contacts",
            parameters=parameters,
            success=False,
            result=result,
            error="Pipedrive client not available - simulated response"
        )
    
    def _list_contacts(self, execution_id: str, parameters: Dict[str, Any]) -> ToolExecution:
        """List contacts with optional filters."""
        limit = parameters.get('limit', 20)
        
        if self.client:
            try:
                response = self.client.persons.get_all_persons()
                
                if response.get('success'):
                    contacts = []
                    data = response.get('data', [])
                    
                    for person in data[:limit]:
                        contacts.append({
                            "contact_id": person.get('id'),
                            "name": person.get('name'),
                            "email": self._extract_email(person),
                            "phone": self._extract_phone(person),
                            "organization": person.get('org_name'),
                            "last_activity": person.get('last_activity_date')
                        })
                    
                    result = {
                        "contacts": contacts,
                        "total_results": len(contacts),
                        "limit": limit
                    }
                    
                    print(f"📋 [PIPEDRIVE] Listed {len(contacts)} contacts")
                    return ToolExecution(
                        execution_id=execution_id,
                        tool_type=self.tool_type,
                        action="list_contacts",
                        parameters=parameters,
                        success=True,
                        result=result
                    )
                else:
                    error_msg = response.get('error', 'Failed to list contacts')
                    raise Exception(error_msg)
                    
            except Exception as exc:
                return ToolExecution(
                    execution_id=execution_id,
                    tool_type=self.tool_type,
                    action="list_contacts",
                    parameters=parameters,
                    success=False,
                    error=str(exc)
                )
        
        # Fallback simulation
        result = {
            "contacts": [
                {
                    "contact_id": "sim_1",
                    "name": "John Doe",
                    "email": "john.doe@example.com",
                    "phone": "+1-555-0123",
                    "organization": "Acme Corp",
                    "last_activity": datetime.now().isoformat()
                },
                {
                    "contact_id": "sim_2",
                    "name": "Jane Smith",
                    "email": "jane.smith@example.com",
                    "phone": "+1-555-0456",
                    "organization": "Tech Solutions",
                    "last_activity": datetime.now().isoformat()
                }
            ],
            "total_results": 2,
            "limit": limit,
            "simulated": True
        }
        
        print(f"📋 [PIPEDRIVE] Simulated contact list")
        return ToolExecution(
            execution_id=execution_id,
            tool_type=self.tool_type,
            action="list_contacts",
            parameters=parameters,
            success=False,
            result=result,
            error="Pipedrive client not available - simulated response"
        )
    
    def _add_note_to_contact(self, contact_id: str, note_content: str):
        """Add a note to a contact."""
        if self.client:
            try:
                note_data = {
                    'content': note_content,
                    'person_id': contact_id
                }
                self.client.notes.create_note(note_data)
                print(f"📝 [PIPEDRIVE] Note added to contact {contact_id}")
            except Exception as exc:
                print(f"⚠️ [PIPEDRIVE] Failed to add note: {exc}")
    
    def _extract_email(self, person_data: Dict[str, Any]) -> Optional[str]:
        """Extract primary email from person data."""
        emails = person_data.get('email')
        if isinstance(emails, list) and emails:
            return emails[0].get('value') if isinstance(emails[0], dict) else emails[0]
        elif isinstance(emails, str):
            return emails
        return None
    
    def _extract_phone(self, person_data: Dict[str, Any]) -> Optional[str]:
        """Extract primary phone from person data."""
        phones = person_data.get('phone')
        if isinstance(phones, list) and phones:
            return phones[0].get('value') if isinstance(phones[0], dict) else phones[0]
        elif isinstance(phones, str):
            return phones
        return None


class CalendlyToolAgent(ToolAgent):
    """Calendly integration tool agent for fetching availability."""

    IST_TZ = pytz.timezone('Asia/Kolkata')

    def __init__(self, credentials: APICredentials):
        super().__init__(credentials)
        self.tool_type = ToolType.CALENDLY
        self.base_url = "https://api.calendly.com"
        self._event_duration_cache: Dict[str, int] = {}

    def execute(self, action: str, parameters: Dict[str, Any]) -> ToolExecution:
        execution_id = f"calendly_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            if action == "list_available_slots":
                return self._list_available_slots(execution_id, parameters)
            raise ValueError(f"Unknown Calendly action: {action}")
        except Exception as exc:
            return ToolExecution(
                execution_id=execution_id,
                tool_type=self.tool_type,
                action=action,
                parameters=parameters,
                success=False,
                error=str(exc)
            )

    def _list_available_slots(self, execution_id: str, parameters: Dict[str, Any]) -> ToolExecution:
        """Get real available time slots from Calendly API."""

        token = parameters.get("calendly_token") or getattr(self.credentials, "calendly_token", None)
        if not token:
            raise ValueError("Calendly API token is not configured. Set CALENDLY_API_KEY in your environment.")

        event_type_uuid = parameters.get("event_type_uuid") or getattr(self.credentials, "calendly_event_type_uuid", None)
        if not event_type_uuid:
            raise ValueError("Calendly event type UUID is missing. Set CALENDLY_EVENT_TYPE_UUID or provide it in the request.")

        scheduling_link = parameters.get("scheduling_link") or getattr(self.credentials, "calendly_scheduling_link", None)
        if not scheduling_link:
            raise ValueError("Calendly scheduling link is missing. Set CALENDLY_SCHEDULING_LINK or provide it in the request.")

        date_str = parameters.get("date")
        target_date = self._parse_date(date_str)

        now_ist = datetime.now(self.IST_TZ)
        if target_date < now_ist.date():
            return ToolExecution(
                execution_id=execution_id,
                tool_type=self.tool_type,
                action="list_available_slots",
                parameters=parameters,
                success=False,
                error=f"The date {target_date.strftime('%B %d, %Y')} has already passed. Please choose a future date."
            )

        start_ist = self.IST_TZ.localize(datetime.combine(target_date, time.min))
        end_ist = start_ist + timedelta(days=1)
        start_iso = start_ist.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        end_iso = end_ist.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        slot_duration = parameters.get("duration_minutes")
        if not isinstance(slot_duration, int) or slot_duration <= 0:
            slot_duration = self._get_event_duration(token, event_type_uuid)

        event_type_uri = f"https://api.calendly.com/event_types/{event_type_uuid}"
        url = f"{self.base_url}/event_type_available_times"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {
            "event_type": event_type_uri,
            "start_time": start_iso,
            "end_time": end_iso,
            "timezone": "UTC",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            raise RuntimeError(f"Calendly API request failed: {exc}") from exc

        if response.status_code >= 400:
            try:
                error_detail = response.json().get("message", response.text)
            except Exception:
                error_detail = response.text
            raise RuntimeError(f"Calendly API error ({response.status_code}): {error_detail}")

        data = response.json()
        collection = data.get("collection", [])
        slots: List[Dict[str, Any]] = []

        for entry in collection:
            start_time = entry.get("start_time")
            if not start_time:
                continue
            try:
                start_dt_utc = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except ValueError:
                continue

            end_time = entry.get("end_time")
            if end_time:
                try:
                    end_dt_utc = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                except ValueError:
                    end_dt_utc = start_dt_utc + timedelta(minutes=slot_duration)
            else:
                end_dt_utc = start_dt_utc + timedelta(minutes=slot_duration)

            start_dt = start_dt_utc.astimezone(self.IST_TZ)
            end_dt = end_dt_utc.astimezone(self.IST_TZ)

            label = f"{self._format_time(start_dt)} - {self._format_time(end_dt)} IST"
            slots.append({
                "start_time_utc": start_dt_utc.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
                "end_time_utc": end_dt_utc.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
                "start_time_ist": start_dt.isoformat(),
                "end_time_ist": end_dt.isoformat(),
                "label": label,
                "duration_minutes": slot_duration,
                "scheduling_url": entry.get("scheduling_url"),
                "invitees_remaining": entry.get("invitees_remaining"),
                "status": entry.get("status"),
            })

        slots.sort(key=lambda item: item["start_time_utc"])
        limit = parameters.get("limit")
        recommended = slots[:limit] if isinstance(limit, int) and limit > 0 else slots[:5]

        if target_date == now_ist.date():
            date_label = "today"
        elif target_date == (now_ist + timedelta(days=1)).date():
            date_label = "tomorrow"
        else:
            date_label = target_date.strftime('%B %d, %Y')

        result = {
            "requested_date": target_date.isoformat(),
            "date_label": date_label,
            "slots": recommended,
            "total_slots": len(slots),
            "scheduling_link": scheduling_link,
            "meeting_duration_minutes": slot_duration,
            "meeting_duration": f"{slot_duration} minutes",
            "timezone": "IST (Indian Standard Time)",
        }

        status_message = "Available slots fetched successfully." if recommended else "No available slots found for the selected date."

        return ToolExecution(
            execution_id=execution_id,
            tool_type=self.tool_type,
            action="list_available_slots",
            parameters=parameters,
            success=True,
            result={**result, "status_message": status_message}
        )

    def _get_event_duration(self, token: str, event_type_uuid: str) -> int:
        if event_type_uuid in self._event_duration_cache:
            return self._event_duration_cache[event_type_uuid]

        url = f"{self.base_url}/event_types/{event_type_uuid}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code < 400:
                data = response.json().get("resource", {})
                duration = data.get("duration")
                if isinstance(duration, int) and duration > 0:
                    self._event_duration_cache[event_type_uuid] = duration
                    return duration
        except requests.RequestException:
            pass
        except Exception:
            pass

        fallback_duration = 30
        self._event_duration_cache[event_type_uuid] = fallback_duration
        return fallback_duration

    @classmethod
    def _parse_date(cls, date_str: Optional[str]) -> date:
        if not date_str:
            return datetime.now(cls.IST_TZ).date()
        try:
            return datetime.fromisoformat(date_str).date()
        except ValueError as exc:
            raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD format.") from exc

    @staticmethod
    def _format_time(value: datetime) -> str:
        formatted = value.strftime("%I:%M %p")
        if formatted.startswith("0"):
            formatted = formatted[1:]
        return formatted
