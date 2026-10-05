import { createAction, Property } from '@activepieces/pieces-framework';
import { RetrieveAndGenerateCommand, RetrieveCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import { authValue, errorMessage } from '../../../../aws-common/aws';
import { bedrockAgentsAuth, knowledgeBaseDropdown, runtime } from '../common';

export const retrieveAction = createAction({
  auth: bedrockAgentsAuth,
  name: 'retrieve',
  displayName: 'Retrieve from knowledge base',
  description: 'Semantic search over a Bedrock Knowledge Base; returns the matching passages with scores and sources (no generation, so it stays outside any model call).',
  props: {
    knowledgeBaseId: knowledgeBaseDropdown,
    query: Property.LongText({ displayName: 'Query', required: true }),
    numberOfResults: Property.Number({ displayName: 'Number of results', required: false, defaultValue: 5 }),
  },
  async run(context) {
    const auth = authValue(context.auth);
    const { knowledgeBaseId, query, numberOfResults } = context.propsValue;
    try {
      const out = await runtime(auth).send(
        new RetrieveCommand({
          knowledgeBaseId: String(knowledgeBaseId),
          retrievalQuery: { text: query },
          retrievalConfiguration: { vectorSearchConfiguration: { numberOfResults: Number(numberOfResults) || 5 } },
        }),
      );
      return {
        results: (out.retrievalResults || []).map((r) => ({ text: r.content?.text, score: r.score, location: r.location, metadata: r.metadata })),
      };
    } catch (error) {
      throw new Error(errorMessage(error));
    }
  },
});

export const retrieveAndGenerateAction = createAction({
  auth: bedrockAgentsAuth,
  name: 'retrieve_and_generate',
  displayName: 'Retrieve and generate (RAG)',
  description: 'Answer a question from a Bedrock Knowledge Base with a Bedrock model. The generation happens on Bedrock, outside the LiteLLM proxy; prefer Retrieve + a Responsible AI Gateway chat step when governance must apply.',
  props: {
    knowledgeBaseId: knowledgeBaseDropdown,
    modelArn: Property.ShortText({ displayName: 'Model ARN or id', description: 'For example anthropic.claude-3-5-sonnet-20241022-v2:0 or a full foundation-model ARN.', required: true }),
    query: Property.LongText({ displayName: 'Question', required: true }),
    sessionId: Property.ShortText({ displayName: 'Session id', required: false }),
  },
  async run(context) {
    const auth = authValue(context.auth);
    const { knowledgeBaseId, modelArn, query, sessionId } = context.propsValue;
    const arn = modelArn.startsWith('arn:') ? modelArn : `arn:aws:bedrock:${auth.region}::foundation-model/${modelArn}`;
    try {
      const out = await runtime(auth).send(
        new RetrieveAndGenerateCommand({
          input: { text: query },
          sessionId: sessionId || undefined,
          retrieveAndGenerateConfiguration: { type: 'KNOWLEDGE_BASE', knowledgeBaseConfiguration: { knowledgeBaseId: String(knowledgeBaseId), modelArn: arn } },
        }),
      );
      return { output: out.output?.text, citations: out.citations, sessionId: out.sessionId };
    } catch (error) {
      throw new Error(errorMessage(error));
    }
  },
});
