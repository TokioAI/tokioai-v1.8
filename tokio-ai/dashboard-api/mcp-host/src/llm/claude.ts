/**
 * Proveedor de LLM usando Anthropic Claude
 */
import Anthropic from '@anthropic-ai/sdk';
import { LLMProvider, Message, StreamChunk } from './base.js';

export class ClaudeProvider extends LLMProvider {
  private client: Anthropic;
  private model: string;
  
  constructor(apiKey: string, model: string = 'claude-sonnet-4-20250514') {
    super();
    this.client = new Anthropic({ apiKey });
    this.model = model;
  }
  
  async chat(messages: Message[]): Promise<string> {
    const systemMsg = messages.find(m => m.role === 'system')?.content;
    const userMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({ 
        role: m.role === 'assistant' ? 'assistant' : 'user', 
        content: m.content 
      }));
    
    const response = await this.client.messages.create({
      model: this.model,
      max_tokens: 8192,
      system: systemMsg,
      messages: userMessages as any
    });
    
    return response.content[0].type === 'text' ? response.content[0].text : '';
  }
  
  async chatStream(
    messages: Message[],
    onChunk?: (chunk: StreamChunk) => void
  ): Promise<string> {
    const systemMsg = messages.find(m => m.role === 'system')?.content;
    const userMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({ 
        role: m.role === 'assistant' ? 'assistant' : 'user', 
        content: m.content 
      }));
    
    const stream = await this.client.messages.stream({
      model: this.model,
      max_tokens: 8192,
      system: systemMsg,
      messages: userMessages as any
    });
    
    let fullResponse = '';
    for await (const chunk of stream) {
      if (chunk.type === 'content_block_delta' && chunk.delta.type === 'text_delta') {
        const text = chunk.delta.text;
        fullResponse += text;
        onChunk?.({ text, isComplete: false });
      }
    }
    onChunk?.({ text: '', isComplete: true });
    return fullResponse;
  }
}
