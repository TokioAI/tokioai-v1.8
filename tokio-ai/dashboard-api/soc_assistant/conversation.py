"""
Gestor de conversaciones para el SOC AI Assistant
Mantiene el historial y contexto de las conversaciones
"""
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


class ConversationManager:
    """Gestiona el historial y contexto de conversaciones"""
    
    def __init__(self):
        """Inicializa el gestor de conversaciones"""
        # En memoria por ahora, se puede migrar a DB después
        self.conversations: Dict[str, Dict[str, Any]] = {}
    
    def get_or_create_conversation(self, conversation_id: Optional[str] = None) -> str:
        """
        Obtiene o crea una conversación
        
        Args:
            conversation_id: ID de conversación existente (opcional)
        
        Returns:
            ID de la conversación
        """
        if conversation_id and conversation_id in self.conversations:
            return conversation_id
        
        # Crear nueva conversación
        new_id = str(uuid.uuid4())
        self.conversations[new_id] = {
            "id": new_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "messages": [],
            "context": {}
        }
        return new_id
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Agrega un mensaje a la conversación
        
        Args:
            conversation_id: ID de la conversación
            role: Rol del mensaje (user, assistant, system)
            content: Contenido del mensaje
            metadata: Metadatos adicionales (opcional)
        """
        if conversation_id not in self.conversations:
            self.get_or_create_conversation(conversation_id)
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        self.conversations[conversation_id]["messages"].append(message)
        self.conversations[conversation_id]["updated_at"] = datetime.now().isoformat()
    
    def get_conversation_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene el historial de una conversación
        
        Args:
            conversation_id: ID de la conversación
            limit: Límite de mensajes a retornar (opcional)
        
        Returns:
            Lista de mensajes
        """
        if conversation_id not in self.conversations:
            return []
        
        messages = self.conversations[conversation_id]["messages"]
        if limit:
            return messages[-limit:]
        return messages
    
    def update_context(
        self,
        conversation_id: str,
        context: Dict[str, Any]
    ):
        """
        Actualiza el contexto de una conversación
        
        Args:
            conversation_id: ID de la conversación
            context: Contexto a actualizar
        """
        if conversation_id not in self.conversations:
            self.get_or_create_conversation(conversation_id)
        
        self.conversations[conversation_id]["context"].update(context)
    
    def get_context(self, conversation_id: str) -> Dict[str, Any]:
        """
        Obtiene el contexto de una conversación
        
        Args:
            conversation_id: ID de la conversación
        
        Returns:
            Contexto de la conversación
        """
        if conversation_id not in self.conversations:
            return {}
        
        return self.conversations[conversation_id].get("context", {})
    
    def clear_conversation(self, conversation_id: str):
        """Limpia una conversación"""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
    
    def get_conversation_summary(self, conversation_id: str) -> Dict[str, Any]:
        """Obtiene un resumen de la conversación"""
        if conversation_id not in self.conversations:
            return {}
        
        conv = self.conversations[conversation_id]
        return {
            "id": conv["id"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "message_count": len(conv["messages"]),
            "context": conv["context"]
        }


