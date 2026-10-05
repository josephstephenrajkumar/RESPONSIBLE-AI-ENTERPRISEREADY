import { createAction, Property } from '@activepieces/pieces-framework';
import { DescribeAutomationJobCommand, DescribeFlowCommand, ListFlowsCommand, StartAutomationJobCommand } from '@aws-sdk/client-quicksight';
import { authValue, errorMessage, parseJsonInput } from '../../../../aws-common/aws';
import { accountId, client, quickAuth, sleep, type QuickAuth } from '../common';

export const listQuickFlowsAction = createAction({
  auth: quickAuth,
  name: 'list_flows',
  displayName: 'List Quick Flows',
  description: 'Quick Flows in the account with their publish state and run counts. Running a flow from outside Quick is not exposed by the public API yet; to run research or a flow on demand, use Quick Automate or call back through a Quick chat agent (MCP).',
  props: {},
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    try {
      const out = await client(auth).send(new ListFlowsCommand({ AwsAccountId: await accountId(auth), MaxResults: 100 }));
      return { flows: (out.FlowSummaryList || []).map((f) => ({ flowId: f.FlowId, name: f.Name, description: f.Description, publishState: f.PublishState, runCount: f.RunCount, userCount: f.UserCount, lastUpdated: f.LastUpdatedTime })) };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const describeQuickFlowAction = createAction({
  auth: quickAuth,
  name: 'describe_flow',
  displayName: 'Describe Quick Flow',
  description: 'Metadata and definition of a Quick Flow (the definition format is internal to Quick and may change).',
  props: {
    flowId: Property.ShortText({ displayName: 'Flow id', required: true }),
    publishState: Property.StaticDropdown({ displayName: 'Version', required: false, defaultValue: 'PUBLISHED', options: { options: [{ label: 'Published', value: 'PUBLISHED' }, { label: 'Draft', value: 'DRAFT' }] } }),
  },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    try {
      const out = await client(auth).send(new DescribeFlowCommand({ AwsAccountId: await accountId(auth), FlowId: context.propsValue.flowId, PublishState: (context.propsValue.publishState || 'PUBLISHED') as never }));
      return out;
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const startAutomationJobAction = createAction({
  auth: quickAuth,
  name: 'start_automation_job',
  displayName: 'Start Quick Automate job',
  description: 'Runs a deployed Quick Automate automation with an input payload and optionally waits for its output.',
  props: {
    automationGroupId: Property.ShortText({ displayName: 'Automation group id', required: true }),
    automationId: Property.ShortText({ displayName: 'Automation id', required: true }),
    inputPayload: Property.Json({ displayName: 'Input payload (JSON)', required: false }),
    waitSeconds: Property.Number({ displayName: 'Wait up to (seconds)', description: '0 = return the job id immediately.', required: false, defaultValue: 120 }),
  },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    const account = await accountId(auth);
    const { automationGroupId, automationId, inputPayload, waitSeconds } = context.propsValue;
    const payload = parseJsonInput(inputPayload, 'Input payload');
    try {
      const started = await client(auth).send(new StartAutomationJobCommand({ AwsAccountId: account, AutomationGroupId: automationGroupId, AutomationId: automationId, InputPayload: payload === undefined ? undefined : JSON.stringify(payload) }));
      const jobId = started.JobId as string;
      const deadline = Date.now() + Math.min(Number(waitSeconds) || 0, 900) * 1000;
      let last: Record<string, unknown> = { jobId, arn: started.Arn, status: 'STARTED' };
      while (Date.now() < deadline) {
        await sleep(5000);
        const job = await client(auth).send(new DescribeAutomationJobCommand({ AwsAccountId: account, AutomationGroupId: automationGroupId, AutomationId: automationId, JobId: jobId, IncludeOutputPayload: true }));
        let output: unknown = job.OutputPayload;
        try { output = job.OutputPayload ? JSON.parse(job.OutputPayload) : undefined; } catch { /* keep string */ }
        last = { jobId, arn: job.Arn, status: job.JobStatus, startedAt: job.StartedAt, endedAt: job.EndedAt, output };
        if (job.EndedAt || ['SUCCEEDED', 'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'].includes(String(job.JobStatus))) break;
      }
      return last;
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const describeAutomationJobAction = createAction({
  auth: quickAuth,
  name: 'describe_automation_job',
  displayName: 'Describe Quick Automate job',
  description: 'Status and output of a Quick Automate job.',
  props: {
    automationGroupId: Property.ShortText({ displayName: 'Automation group id', required: true }),
    automationId: Property.ShortText({ displayName: 'Automation id', required: true }),
    jobId: Property.ShortText({ displayName: 'Job id', required: true }),
  },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    const { automationGroupId, automationId, jobId } = context.propsValue;
    try {
      const job = await client(auth).send(new DescribeAutomationJobCommand({ AwsAccountId: await accountId(auth), AutomationGroupId: automationGroupId, AutomationId: automationId, JobId: jobId, IncludeInputPayload: true, IncludeOutputPayload: true }));
      return { jobId, status: job.JobStatus, startedAt: job.StartedAt, endedAt: job.EndedAt, input: job.InputPayload, output: job.OutputPayload };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});
