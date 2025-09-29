"""
Memory Agent implementation using simple JSON file storage.
"""
import json
import uuid
import os
from datetime import datetime
from typing import List, Dict, Any

from contracts import MemoryEntry, ToolExecution


class MemoryAgent:
    def __init__(self, persist_directory: str = "./memory_db"):
        """Initialize simple file-based memory storage."""
        self.persist_directory = persist_directory
        self.memory_file = os.path.join(persist_directory, "interactions.json")

        # Create directory if it doesn't exist
        os.makedirs(persist_directory, exist_ok=True)

        # Initialize memory file if it doesn't exist
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def store_interaction(self, memory_entry: MemoryEntry) -> str:
        """Store a completed interaction in memory."""
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                interactions = json.load(f)

            serialized_results = []
            for execution in memory_entry.execution_results:
                if isinstance(execution, ToolExecution):
                    serialized_results.append(execution.model_dump())
                elif isinstance(execution, dict):
                    serialized_results.append(execution)
                else:
                    try:
                        serialized_results.append(ToolExecution(**execution).model_dump())
                    except Exception as exc:
                        serialized_results.append({"error": f"Unserializable execution result: {exc}"})

            interaction_data = {
                "entry_id": memory_entry.entry_id,
                "user_query": memory_entry.user_query,
                "plan_summary": memory_entry.plan_summary,
                "execution_results": serialized_results,
                "sentiment": memory_entry.sentiment,
                "tags": memory_entry.tags,
                "timestamp": memory_entry.timestamp
            }

            interactions.append(interaction_data)

            if len(interactions) > 100:
                interactions = interactions[-100:]

            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(interactions, f, indent=2)

            return memory_entry.entry_id

        except Exception as e:
            print(f"Error storing memory: {e}")
            return ""

    def search_similar_interactions(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar past interactions using simple text matching."""
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                interactions = json.load(f)

            if not interactions:
                return []

            query_lower = query.lower()
            similar_interactions: List[Dict[str, Any]] = []

            for interaction in interactions:
                user_query = interaction.get('user_query', '').lower()
                plan_summary = interaction.get('plan_summary', '').lower()

                score = 0
                for word in query_lower.split():
                    if word in user_query:
                        score += 2
                    if word in plan_summary:
                        score += 1

                if score > 0:
                    interaction['similarity_score'] = score
                    similar_interactions.append(interaction)

            similar_interactions.sort(key=lambda x: x['similarity_score'], reverse=True)
            return similar_interactions[:limit]

        except Exception as e:
            print(f"Error searching memory: {e}")
            return []

    def get_recent_interactions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent interactions for context."""
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                interactions = json.load(f)

            if not interactions:
                return []

            interactions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return interactions[:limit]

        except Exception as e:
            print(f"Error retrieving recent interactions: {e}")
            return []

    def create_memory_entry(
        self,
        user_query: str,
        plan_summary: str,
        execution_results: List[ToolExecution],
        sentiment: str = "neutral",
        tags: List[str] = None
    ) -> MemoryEntry:
        """Create a new memory entry."""
        normalized_results: List[ToolExecution] = []
        for execution in execution_results:
            if isinstance(execution, ToolExecution):
                normalized_results.append(execution)
            elif isinstance(execution, dict):
                normalized_results.append(ToolExecution(**execution))
            else:
                raise ValueError("Unsupported execution result type for memory entry")

        return MemoryEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            user_query=user_query,
            plan_summary=plan_summary,
            execution_results=normalized_results,
            sentiment=sentiment,
            tags=tags or []
        )

    def get_interaction_stats(self) -> Dict[str, Any]:
        """Get statistics about stored interactions."""
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                interactions = json.load(f)

            total_interactions = len(interactions)
            if total_interactions == 0:
                return {"total_interactions": 0}

            sentiments: Dict[str, int] = {}
            for interaction in interactions:
                sentiment = interaction.get('sentiment', 'neutral')
                sentiments[sentiment] = sentiments.get(sentiment, 0) + 1

            return {
                "total_interactions": total_interactions,
                "sentiment_distribution": sentiments,
                "storage_type": "file_based"
            }

        except Exception as e:
            print(f"Error getting stats: {e}")
            return {"total_interactions": 0, "error": str(e)}
