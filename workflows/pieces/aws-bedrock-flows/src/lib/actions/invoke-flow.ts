import { createAction, Property } from '@activepieces/pieces-framework';
import { InvokeFlowCommand } from '@aws-sdk/client-bedrock-agent-runtime';
import { authValue, errorMessage, parseJsonInput } from '../../../../aws-common/aws';
import { bedrockFlowsAuth, flowAliasDropdown, flowDropdown, runtime } from '../common';

export const invokeFlowAction = createAction({
  auth: bedrockFlowsAuth,
  name: 'invoke_flow',
  displayName: 'Invoke flow',
  description: 'Run a Bedrock Flow with one input document and collect its outputs. Prompt nodes inside the flow run on Bedrock models outside the LiteLLM proxy.',
  props: {
    flowIdentifier: flowDropdown,
    flowAliasIdentifier: flowAliasDropdown,
    input: Property.LongText({ displayName: 'Input', description: 'Text, or a JSON object/array when the flow input node expects a document.', required: true }),
    inputNodeName: Property.ShortText({ displayName: 'Input node name', required: false, defaultValue: 'FlowInputNode' }),
    inputNodeOutputName: Property.ShortText({ displayName: 'Input node output name', required: false, defaultValue: 'document' }),
    enableTrace: Property.Checkbox({ displayName: 'Include trace', required: false, defaultValue: false }),
  },
  async run(context) {
    const auth = authValue(context.auth);
    const { flowIdentifier, flowAliasIdentifier, input, inputNodeName, inputNodeOutputName, enableTrace } = context.propsValue;
    let document: unknown = input;
    const trimmed = (input || '').trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try { document = parseJsonInput(trimmed, 'Input'); } catch { document = input; }
    }
    try {
      const response = await runtime(auth).send(
        new InvokeFlowCommand({
          flowIdentifier: String(flowIdentifier),
          flowAliasIdentifier: String(flowAliasIdentifier),
          enableTrace: Boolean(enableTrace),
          inputs: [{ content: { document: document as never }, nodeName: inputNodeName || 'FlowInputNode', nodeOutputName: inputNodeOutputName || 'document' }],
        }),
      );
      const outputs: { nodeName?: string; document: unknown }[] = [];
      const traces: unknown[] = [];
      let completionReason: string | undefined;
      for await (const event of response.responseStream || []) {
        if (event.flowOutputEvent) outputs.push({ nodeName: event.flowOutputEvent.nodeName, document: event.flowOutputEvent.content?.document });
        if (event.flowCompletionEvent) completionReason = event.flowCompletionEvent.completionReason;
        if (event.flowTraceEvent && enableTrace) traces.push(event.flowTraceEvent);
      }
      const first = outputs[0]?.document;
      return { output: first, outputs, completionReason, executionId: response.executionId, traces: enableTrace ? traces : undefined };
    } catch (error) {
      throw new Error(errorMessage(error));
    }
  },
});
