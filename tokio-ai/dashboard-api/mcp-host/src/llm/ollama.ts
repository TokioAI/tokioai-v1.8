/**
 * Proveedor de LLM usando Ollama (local, sin API key)
 */
import { LLMProvider, Message, StreamChunk } from './base.js';

export class OllamaProvider extends LLMProvider {
  private baseUrl: string;
  private model: string;
  
  constructor(baseUrl: string = 'http://localhost:11434', model: string = 'llama3.2') {
    super();
    this.baseUrl = baseUrl;
    this.model = model;
  }
  
  async chat(messages: Message[]): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.model,
        messages: messages.map(m => ({
          role: m.role === 'system' ? 'system' : m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content
        })),
        stream: false
      })
    });
    
    if (!response.ok) {
      throw new Error(`Ollama API error: ${response.statusText}`);
    }
    
    const data = await response.json() as { message?: { content?: string } };
    return data.message?.content || '';
  }
  
  async chatStream(
    messages: Message[],
    onChunk?: (chunk: StreamChunk) => void
  ): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.model,
        messages: messages.map(m => ({
          role: m.role === 'system' ? 'system' : m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content
        })),
        stream: true
      })
    });
    
    if (!response.ok) {
      throw new Error(`Ollama API error: ${response.statusText}`);
    }
    
    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    
    if (!reader) {
      throw new Error('No response body reader available');
    }
    
    let buffer = '';
    let fullResponse = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        if (line.trim()) {
          try {
            const data = JSON.parse(line) as { message?: { content?: string }; done?: boolean };
            const text = data.message?.content || '';
            if (text) {
              fullResponse += text;
              onChunk?.({ text, isComplete: false });
            }
            if (data.done) {
              onChunk?.({ text: '', isComplete: true });
              return fullResponse;
            }
          } catch (e) {
            // Ignorar líneas que no son JSON válido
          }
        }
      }
    }
    
    onChunk?.({ text: '', isComplete: true });
    return fullResponse;
  }
}
