/**
 * Interfaz base para proveedores de LLM
 */

export interface Message {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface StreamChunk {
  text: string;
  isComplete: boolean;
  functionCall?: {
    name: string;
    arguments: Record<string, any>;
  };
}

export abstract class LLMProvider {
  abstract chat(messages: Message[]): Promise<string>;
  
  /**
   * Stream de respuesta del LLM con soporte para función calling
   * @param messages Mensajes de la conversación
   * @param onChunk Callback que se ejecuta con cada chunk de texto
   * @returns Promise que resuelve con la respuesta completa
   */
  async chatStream(
    messages: Message[],
    onChunk?: (chunk: StreamChunk) => void
  ): Promise<string> {
    // Implementación por defecto: llama a chat() y emula streaming
    const response = await this.chat(messages);
    if (onChunk) {
      // Emular streaming token por token para compatibilidad
      const words = response.split(/(\s+)/);
      let accumulated = '';
      for (const word of words) {
        accumulated += word;
        onChunk({ text: word, isComplete: false });
        // Pequeño delay para simular streaming
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      onChunk({ text: '', isComplete: true });
    }
    return response;
  }
}
