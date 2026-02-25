/**
 * Proveedor de LLM usando OpenAI
 */
import OpenAI from 'openai';
import { LLMProvider, Message, StreamChunk } from './base.js';

export class OpenAIProvider extends LLMProvider {
  private client: OpenAI;
  private model: string;
  
  constructor(apiKey: string, model: string = 'gpt-4o') {
    super();
    this.client = new OpenAI({ apiKey });
    this.model = model;
  }
  
  async chat(messages: Message[]): Promise<string> {
    const response = await this.client.chat.completions.create({
      model: this.model,
      messages: messages.map(m => ({
        role: m.role === 'system' ? 'system' : m.role === 'assistant' ? 'assistant' : 'user',
        content: m.content
      })),
      max_tokens: 8192,
      temperature: 0.7
    });
    
    return response.choices[0]?.message?.content || '';
  }
  
  async chatStream(
    messages: Message[],
    onChunk?: (chunk: StreamChunk) => void
  ): Promise<string> {
    const stream = await this.client.chat.completions.create({
      model: this.model,
      messages: messages.map(m => ({
        role: m.role === 'system' ? 'system' : m.role === 'assistant' ? 'assistant' : 'user',
        content: m.content
      })),
      max_tokens: 8192,
      temperature: 0.7,
      stream: true
    });
    
    let fullResponse = '';
    for await (const chunk of stream) {
      const text = chunk.choices[0]?.delta?.content || '';
      if (text) {
        fullResponse += text;
        onChunk?.({ text, isComplete: false });
      }
    }
    onChunk?.({ text: '', isComplete: true });
    return fullResponse;
  }
}
