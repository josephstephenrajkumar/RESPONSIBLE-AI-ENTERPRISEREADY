import { createAction, Property } from '@activepieces/pieces-framework';
import { InvokeAgentCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import { authValue, errorMessage, parseJsonInput } from '../../../../aws-common/aws';
import { agentDropdown, aliasDropdown, bedrockAgentsAuth, runtime } from '../common';

export const invokeAgentAction = createAction({
  auth: bedrockAgentsAuth,
  name: 'invoke_agent',
  displayName: 'Invoke agent',
  description: 'Send a message to a Bedrock Agent and return its completion, citations and (optionally) the trace. Note: the agent runs on Bedrock models outside the LiteLLM proxy and the Responsible AI pipeline; pass its answer through a Responsible AI Gateway chat step before showing it to users if policy checks are required.',
  props: {
    agentId: agentDropdown,
    agentAliasId: aliasDropdown,
    inputText: Property.LongText({ displayName: 'Message', required: true }),
    sessionId: Property.ShortText({ displayName: 'Session id', description: 'Keeps the agent conversation across turns; for a chat app use the chat session id.', required: false }),
    sessionAttributes: Property.Json({ displayName: 'Session attributes (JSON)', required: false }),
    enableTrace: Property.Checkbox({ displayName: 'Include trace', required: false, defaultValue: false }),
  },
  async run(context) {
    const auth = authValue(context.auth);
    const { agentId, agentAliasId, inputText, sessionId, sessionAttributes, enableTrace } = context.propsValue;
    const attrs = parseJsonInput(sessionAttributes, 'Session attributes') as Record<string, string> | undefined;
    try {
      const response = await runtime(auth).send(
        new InvokeAgentCommand({
          agentId: String(agentId),
          agentAliasId: String(agentAliasId),
          sessionId: sessionId || `wf-${Date.now()}`,
          inputText,
          enableTrace: Boolean(enableTrace),
          sessionState: attrs ? { sessionAttributes: attrs } : undefined,
        }),
      );
      const decoder = new TextDecoder();
      let completion = '';
      const citations: unknown[] = [];
      const traces: unknown[] = [];
      for await (const event of response.completion || []) {
        if (event.chunk?.bytes) completion += decoder.decode(event.chunk.bytes);
        if (event.chunk?.attribution?.citations) citations.push(...event.chunk.attribution.citations);
        if (event.trace && enableTrace) traces.push(event.trace);
      }
      return { completion, citations, sessionId: response.sessionId, traces: enableTrace ? traces : undefined };
    } catch (error) {
      throw new Error(errorMessage(error));
    }
  },
});
