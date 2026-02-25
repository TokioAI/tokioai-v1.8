/**
 * Factory para crear el provider LLM según configuración
 */
import { LLMProvider } from './base.js';
import { GeminiLLM } from './gemini.js';
import { ClaudeProvider } from './claude.js';
import { OpenAIProvider } from './openai.js';
import { OllamaProvider } from './ollama.js';

export function createLLMProvider(): LLMProvider {
  const provider = process.env.LLM_PROVIDER || 'gemini';
  const apiKey = process.env.GEMINI_API_KEY || '';
  const anthropicKey = process.env.ANTHROPIC_API_KEY || '';
  const openaiKey = process.env.OPENAI_API_KEY || '';
  const ollamaUrl = process.env.OLLAMA_BASE_URL || 'http://localhost:11434';
  const ollamaModel = process.env.OLLAMA_MODEL || 'llama3.2';
  const model = process.env.GEMINI_MODEL || 'gemini-2.0-flash';
  
  switch (provider.toLowerCase()) {
    case 'claude':
      if (!anthropicKey) {
        throw new Error('ANTHROPIC_API_KEY no configurado para provider Claude');
      }
      return new ClaudeProvider(anthropicKey, process.env.CLAUDE_MODEL || 'claude-sonnet-4-20250514');
    
    case 'openai':
      if (!openaiKey) {
        throw new Error('OPENAI_API_KEY no configurado para provider OpenAI');
      }
      return new OpenAIProvider(openaiKey, process.env.OPENAI_MODEL || 'gpt-4o');
    
    case 'ollama':
      return new OllamaProvider(ollamaUrl, ollamaModel);
    
    case 'gemini':
    default:
      if (!apiKey) {
        throw new Error('GEMINI_API_KEY no configurado para provider Gemini');
      }
      return new GeminiLLM(apiKey, model);
  }
}
