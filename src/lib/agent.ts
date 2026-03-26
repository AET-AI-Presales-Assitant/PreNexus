import { GoogleGenerativeAI, SchemaType } from '@google/generative-ai';
import { Document, getEmbedding, cosineSimilarity, RoleLevels, Role } from './vectorStore';

export interface AgentTrace {
  id: string;
  step: string;
  details: string;
  status: 'pending' | 'success' | 'warning' | 'error';
}

export class RAGAgent {
  private ai: GoogleGenerativeAI;
  
  constructor(apiKey: string) {
    this.ai = new GoogleGenerativeAI(apiKey);
  }

  async execute(
    query: string,
    documents: Document[],
    userRole: Role,
    onTrace: (trace: Omit<AgentTrace, 'id'>) => void,
    history: { role: 'user' | 'agent', content: string }[] = []
  ): Promise<string> {
    const accessibleDocs = documents.filter(doc => RoleLevels[userRole] >= RoleLevels[doc.role]);
    const docTopics = accessibleDocs.map(d => d.title);

    // Prepare history text for prompts
    const historyText = history.length > 0 
      ? history.map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`).join('\n')
      : 'No previous conversation history.';

    // Intent Detection for "What can I ask?"
    const metaKeywords = ['có thể hỏi', 'thông tin gì', 'topic', 'chủ đề', 'danh sách', 'hỏi gì', 'what can i ask', 'available info', 'help'];
    const isMetaQuery = metaKeywords.some(k => query.toLowerCase().includes(k));

    if (isMetaQuery) {
      onTrace({ step: 'Intent Detection', details: 'User is asking about available information.', status: 'success' });
      const prompt = `
        The user is asking what information or topics are available in the system.
        Based on the following list of document titles accessible to a ${userRole}, 
        provide a polite and professional response listing these topics.
        
        Accessible Topics:
        ${docTopics.map(t => `- ${t}`).join('\n')}
        
        Instructions:
        - Respond in the SAME LANGUAGE as the user's query ("${query}").
        - List the topics clearly.
        - Be polite and inviting.
        - Mention that your answers are based on these specific documents.
        - If no documents are available, apologize politely.
      `;
      const model = this.ai.getGenerativeModel({ model: process.env.GEMINI_MODEL || 'gemini-1.5-flash' });
      const response = await model.generateContent(prompt);
      return response.response.text() || "I'm sorry, I don't see any documents accessible to your role right now.";
    }

    let currentQuery = query;
    let contextDocs: Document[] = [];
    let answer = '';
    let iterations = 0;
    const maxIterations = 2;

    while (iterations < maxIterations) {
      iterations++;
      
      // 1. Retrieval
      onTrace({ step: `Retrieval (Iter ${iterations})`, details: `Searching for: "${currentQuery}"`, status: 'pending' });
      const queryEmbedding = await getEmbedding(currentQuery, this.ai);
      
      // Calculate similarity
      const scoredDocs = accessibleDocs.map(doc => ({
        ...doc,
        score: doc.embedding ? cosineSimilarity(queryEmbedding, doc.embedding) : 0
      })).sort((a, b) => b.score - a.score);

      contextDocs = scoredDocs.filter(d => d.score > 0.4).slice(0, 3); // Slightly lower threshold for better recall
      
      const contextText = contextDocs.length > 0 
        ? contextDocs.map(d => `[${d.title}]: ${d.content}`).join('\n\n')
        : 'No relevant documents found.';

      onTrace({ 
        step: `Retrieval (Iter ${iterations})`, 
        details: `Found ${contextDocs.length} relevant documents (RBAC filtered).`, 
        status: 'success' 
      });

      // 2. Generation
      onTrace({ step: `Generation (Iter ${iterations})`, details: 'Generating answer based on context...', status: 'pending' });
      
      const prompt = `
        You are an intelligent, professional, and polite company assistant.
        Answer the user's query using ONLY the provided context and taking into account the conversation history if relevant.
        
        CONVERSATION HISTORY:
        ${historyText}

        CONTEXT:
        ${contextText}

        QUERY: ${currentQuery}

        INSTRUCTIONS:
        1. If the context contains the answer, provide a clear, helpful, and polite response.
        2. If the context DOES NOT contain the answer, do NOT make up information. Instead, respond politely stating that you don't have information on that specific topic in your current knowledge base, but you're happy to assist with other company-related questions.
        3. Maintain a helpful and professional tone at all times.
        4. Respond in the same language as the user's query ("${query}").
        5. Provide the answer in plain text format only. Do NOT use markdown formatting like bold (**), italics (*), lists (- or *), headers (#), or any other markdown syntax.
      `;
      const model = this.ai.getGenerativeModel({ model: process.env.GEMINI_MODEL || 'gemini-1.5-flash' });
      const response = await model.generateContent(prompt);
      answer = response.response.text() || '';
      
      onTrace({ step: `Generation (Iter ${iterations})`, details: 'Answer generated.', status: 'success' });

      // 3. Reflection
      if (iterations < maxIterations) {
        onTrace({ step: `Self-Reflection (Iter ${iterations})`, details: 'Evaluating if answer is sufficient...', status: 'pending' });
        
        const reflectionPrompt = `
          You are an intelligent critic. Evaluate the following answer based on the query and context.
          Does the answer fully and accurately address the query using only the provided context? 
          Is there missing information that might be found with a different search query?

          Query: ${query}
          Context Used: ${contextText}
          Answer: ${answer}

          Respond strictly in JSON format matching this schema:
          {
            "isSufficient": boolean,
            "reasoning": string,
            "newSearchQuery": string (if not sufficient, provide a better search query, else empty string)
          }
        `;
        const reflectionModel = this.ai.getGenerativeModel({
          model: process.env.GEMINI_MODEL || 'gemini-1.5-flash',
          generationConfig: { 
            responseMimeType: 'application/json',
            responseSchema: {
              type: SchemaType.OBJECT,
              properties: {
                isSufficient: { type: SchemaType.BOOLEAN },
                reasoning: { type: SchemaType.STRING },
                newSearchQuery: { type: SchemaType.STRING }
              },
              required: ['isSufficient', 'reasoning', 'newSearchQuery']
            }
          }
        });
        const reflectionResponse = await reflectionModel.generateContent(reflectionPrompt);
        
        try {
          const reflection = JSON.parse(reflectionResponse.response.text() || '{}');
          if (reflection.isSufficient) {
            onTrace({ step: `Self-Reflection (Iter ${iterations})`, details: `Answer is sufficient. Reasoning: ${reflection.reasoning}`, status: 'success' });
            break; // Exit loop
          } else {
            onTrace({ step: `Self-Reflection (Iter ${iterations})`, details: `Answer insufficient. Refining query to: "${reflection.newSearchQuery}"`, status: 'warning' });
            currentQuery = reflection.newSearchQuery || query;
            continue; // Loop again
          }
        } catch (e) {
          onTrace({ step: `Self-Reflection (Iter ${iterations})`, details: 'Failed to parse reflection.', status: 'error' });
          break;
        }
      } else {
        break;
      }
    }

    // 4. Evaluation
    onTrace({ step: 'Evaluation', details: 'Checking for hallucinations...', status: 'pending' });
    
    const evalPrompt = `
      You are an expert evaluator for AI agents. Your task is to detect "hallucinations" — information in the Answer that is NOT supported by the provided Context.
      
      CONTEXT:
      ${contextDocs.map(d => `[${d.title}]: ${d.content}`).join('\n\n')}

      ANSWER: ${answer}

      Respond strictly in JSON format matching this schema:
      {
        "hasHallucination": boolean,
        "hallucinatedDetails": string (provide specific details of the hallucination if found, otherwise empty),
        "confidenceScore": number (0-1, where 1 is absolute certainty)
      }
    `;
      const evalModel = this.ai.getGenerativeModel({
        model: process.env.GEMINI_MODEL || 'gemini-1.5-flash',
        generationConfig: { 
          responseMimeType: 'application/json',
          responseSchema: {
            type: SchemaType.OBJECT,
            properties: {
              hasHallucination: { type: SchemaType.BOOLEAN },
              hallucinatedDetails: { type: SchemaType.STRING },
              confidenceScore: { type: SchemaType.NUMBER }
            },
            required: ['hasHallucination', 'hallucinatedDetails', 'confidenceScore']
          }
        }
      });
      const evalResponse = await evalModel.generateContent(evalPrompt);

      try {
        const evaluation = JSON.parse(evalResponse.response.text() || '{}');
        if (evaluation.hasHallucination) {
          onTrace({ step: 'Evaluation', details: `Hallucination detected! ${evaluation.hallucinatedDetails}`, status: 'error' });
          answer = `[WARNING: Potential Hallucination Detected]\n\n${answer}`;
        } else {
          onTrace({ step: 'Evaluation', details: `Passed. Confidence: ${evaluation.confidenceScore}`, status: 'success' });
        }
      } catch (e) {
        onTrace({ step: 'Evaluation', details: 'Failed to parse evaluation.', status: 'error' });
      }

    return answer;
  }
}

export async function analyzeDocument(input: string | { inlineData: { data: string, mimeType: string } }, ai: GoogleGenerativeAI): Promise<{title: string, content: string, role: Role, topic: string}> {
  const prompt = `
    You are a document analyzer. Analyze the provided document content and:
    1. Extract a concise, professional title.
    2. Clean up, format, and structure the content for an internal knowledge base (Markdown format).
    3. Recommend the appropriate Role-Based Access Control (RBAC) level ('Guest', 'Employee', or 'Admin').
    4. Identify the main topic/category. MUST be one of these EXACT values:
       - "Skills, capabilities, Tech stack, solution"
       - "Case studies, past project"
       - "Presale checklist or workflow"
       - "General" (if it doesn't fit the above)

    Respond strictly in JSON format matching this schema:
    {
      "title": string,
      "content": string,
      "role": "Guest" | "Employee" | "Admin",
      "topic": string
    }
  `;

  const model = ai.getGenerativeModel({
    model: process.env.GEMINI_MODEL || 'gemini-1.5-flash',
    generationConfig: {
      responseMimeType: 'application/json',
      responseSchema: {
        type: SchemaType.OBJECT,
        properties: {
          title: { type: SchemaType.STRING },
          content: { type: SchemaType.STRING },
          role: { type: SchemaType.STRING },
          topic: { type: SchemaType.STRING }
        },
        required: ['title', 'content', 'role', 'topic']
      }
    }
  });

  const parts = typeof input === 'string' ? [prompt, input] : [prompt, input];
  const response = await model.generateContent(parts);

  return JSON.parse(response.response.text() || '{}');
}
