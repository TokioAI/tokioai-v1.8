/**
 * Proveedor de LLM usando Google Gemini
 */

// Polyfills para Node.js 16 (fetch, Headers, etc.)
import fetch, { Headers, Request, Response } from 'node-fetch';
if (!globalThis.fetch) {
  (globalThis as any).fetch = fetch;
  (globalThis as any).Headers = Headers;
  (globalThis as any).Request = Request;
  (globalThis as any).Response = Response;
}

// Nota: TextDecoderStream no está disponible en Node.js 16
// El método chatStream() maneja esto con un fallback a sendMessage() + streaming simulado

import { GoogleGenerativeAI } from '@google/generative-ai';
import { LLMProvider, Message, StreamChunk } from './base.js';

export class GeminiLLM extends LLMProvider {
  private genAI: GoogleGenerativeAI;
  private model: string;

  constructor(apiKey: string, model: string = 'gemini-2.0-flash') {
    super();
    this.genAI = new GoogleGenerativeAI(apiKey);
    this.model = model;
  }

  async chat(messages: Message[]): Promise<string> {
    // Convertir mensajes al formato de Gemini
    const systemInstruction = messages.find(m => m.role === 'system')?.content || '';
    const conversationMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: m.content }]
      }));

    const model = this.genAI.getGenerativeModel({ 
      model: this.model,
      systemInstruction: systemInstruction || undefined,
      generationConfig: {
        maxOutputTokens: 8192, // Aumentar tokens de salida para respuestas más largas
        temperature: 0.7,
      }
    });

    const chat = model.startChat({
      history: conversationMessages.slice(0, -1) as any,
    });

    const lastMessage = conversationMessages[conversationMessages.length - 1];
    const result = await chat.sendMessage(lastMessage.parts[0].text);
    const response = await result.response;
    
    return response.text();
  }

  /**
   * Implementación de streaming usando Gemini
   * Nota: En Node.js 16, sendMessageStream requiere TextDecoderStream que no está disponible
   * Por lo tanto, usamos sendMessage y simulamos streaming para compatibilidad
   */
  async chatStream(
    messages: Message[],
    onChunk?: (chunk: StreamChunk) => void
  ): Promise<string> {
    // Convertir mensajes al formato de Gemini
    const systemInstruction = messages.find(m => m.role === 'system')?.content || '';
    const conversationMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: m.content }]
      }));

    const model = this.genAI.getGenerativeModel({ 
      model: this.model,
      systemInstruction: systemInstruction || undefined,
      generationConfig: {
        maxOutputTokens: 8192,
        temperature: 0.7,
      }
    });

    const chat = model.startChat({
      history: conversationMessages.slice(0, -1) as any,
    });

    const lastMessage = conversationMessages[conversationMessages.length - 1];
    let fullResponse = '';
    
    // En Node.js 16, TextDecoderStream no está disponible
    // Usamos sendMessage y simulamos streaming dividiendo la respuesta
    try {
      // Intentar usar sendMessageStream si está disponible (Node.js 18+)
      const stream = await chat.sendMessageStream(lastMessage.parts[0].text);
      
      for await (const chunk of stream.stream) {
        const chunkText = chunk.text();
        if (chunkText) {
          fullResponse += chunkText;
          if (onChunk) {
            onChunk({ text: chunkText, isComplete: false });
          }
        }
      }
      
      // Verificar si hay función calling en la respuesta
      const response = await stream.response;
      const candidates = response.candidates;
      
      if (candidates && candidates[0]?.content?.parts) {
        for (const part of candidates[0].content.parts) {
          if (part.functionCall) {
            // Intentar parsear los argumentos
            let args = {};
            try {
              if (typeof part.functionCall.args === 'string') {
                args = JSON.parse(part.functionCall.args);
              } else {
                args = part.functionCall.args || {};
              }
            } catch (e) {
              // Si falla el parseo, usar args tal cual
              args = part.functionCall.args || {};
            }
            
            if (onChunk) {
              onChunk({
                text: '',
                isComplete: false,
                functionCall: {
                  name: part.functionCall.name || '',
                  arguments: args
                }
              });
            }
          }
        }
      }
    } catch (error: any) {
      // Si falla por TextDecoderStream, usar sendMessage y simular streaming
      if (error.message && error.message.includes('TextDecoderStream')) {
        const result = await chat.sendMessage(lastMessage.parts[0].text);
        const response = await result.response;
        fullResponse = response.text();
        
        // Simular streaming dividiendo la respuesta en palabras
        if (onChunk && fullResponse) {
          const words = fullResponse.split(/(\s+)/);
          for (const word of words) {
            if (word) {
              await new Promise(resolve => setTimeout(resolve, 10)); // Pequeño delay
              onChunk({ text: word, isComplete: false });
            }
          }
        }
        
        // Verificar función calling
        const candidates = response.candidates;
        if (candidates && candidates[0]?.content?.parts) {
          for (const part of candidates[0].content.parts) {
            if (part.functionCall) {
              let args = {};
              try {
                if (typeof part.functionCall.args === 'string') {
                  args = JSON.parse(part.functionCall.args);
                } else {
                  args = part.functionCall.args || {};
                }
              } catch (e) {
                args = part.functionCall.args || {};
              }
              
              if (onChunk) {
                onChunk({
                  text: '',
                  isComplete: false,
                  functionCall: {
                    name: part.functionCall.name || '',
                    arguments: args
                  }
                });
              }
            }
          }
        }
      } else {
        // Otro tipo de error, relanzar
        throw error;
      }
    }
    
    if (onChunk) {
      onChunk({ text: '', isComplete: true });
    }
    
    return fullResponse;
  }
}
