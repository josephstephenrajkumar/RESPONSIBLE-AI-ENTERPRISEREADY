// Shared AWS authentication for the Responsible AI custom pieces.
//
// In AWS the engine task role is the identity (no key stored anywhere); an optional role ARN
// is assumed from it with STS. Access keys are accepted only for local development.
// Dropdown and action contexts receive the connection value either as the props object or
// wrapped in { props }, so every piece reads it through `authValue()`.
import { PieceAuth, Property } from '@activepieces/pieces-framework';
import { GetCallerIdentityCommand, STSClient } from '@aws-sdk/client-sts';
import { fromNodeProviderChain, fromTemporaryCredentials } from '@aws-sdk/credential-providers';
import type { AwsCredentialIdentityProvider } from '@smithy/types';

export type AwsAuthValue = {
  region: string;
  roleArn?: string;
  externalId?: string;
  accessKeyId?: string;
  secretAccessKey?: string;
  sessionToken?: string;
  [key: string]: unknown;
};

export const awsAuthProps = {
  region: Property.ShortText({
    displayName: 'Region',
    description: 'AWS region of the service (for example ap-southeast-1 or us-east-1).',
    required: true,
    defaultValue: 'ap-southeast-1',
  }),
  roleArn: Property.ShortText({
    displayName: 'Role ARN to assume (optional)',
    description: 'Assumed from the engine task role with STS. Leave empty to use the task role directly.',
    required: false,
  }),
  externalId: Property.ShortText({
    displayName: 'External id (optional)',
    description: 'Sent with AssumeRole; use it for per-tenant roles so only this engine can assume them.',
    required: false,
  }),
  accessKeyId: Property.ShortText({
    displayName: 'Access key id (local development only)',
    description: 'Leave empty in AWS: the engine task role is used. Never paste production keys.',
    required: false,
  }),
  secretAccessKey: PieceAuth.SecretText({
    displayName: 'Secret access key (local development only)',
    required: false,
  }),
  sessionToken: PieceAuth.SecretText({
    displayName: 'Session token (optional)',
    required: false,
  }),
};

export function authValue<T = AwsAuthValue>(auth: unknown): T {
  const a = auth as { props?: T } | T;
  return ((a as { props?: T })?.props ?? a) as T;
}

export function awsCredentials(auth: AwsAuthValue): AwsCredentialIdentityProvider {
  const base: AwsCredentialIdentityProvider =
    auth.accessKeyId && auth.secretAccessKey
      ? async () => ({
          accessKeyId: String(auth.accessKeyId),
          secretAccessKey: String(auth.secretAccessKey),
          sessionToken: auth.sessionToken ? String(auth.sessionToken) : undefined,
        })
      : fromNodeProviderChain();
  if (auth.roleArn) {
    return fromTemporaryCredentials({
      masterCredentials: base,
      params: { RoleArn: String(auth.roleArn), RoleSessionName: 'responsible-ai-workflow', DurationSeconds: 900, ExternalId: auth.externalId ? String(auth.externalId) : undefined },
      clientConfig: { region: auth.region },
    });
  }
  return base;
}

export function clientConfig(auth: AwsAuthValue) {
  return { region: auth.region, credentials: awsCredentials(auth) };
}

export async function callerIdentity(auth: AwsAuthValue): Promise<{ account?: string; arn?: string }> {
  const out = await new STSClient(clientConfig(auth)).send(new GetCallerIdentityCommand({}));
  return { account: out.Account, arn: out.Arn };
}

export async function validateAws(auth: unknown): Promise<{ valid: true } | { valid: false; error: string }> {
  const value = authValue(auth);
  if (!value?.region) return { valid: false, error: 'Region is required' };
  try {
    await callerIdentity(value);
    return { valid: true };
  } catch (error) {
    return { valid: false, error: `AWS credentials not usable: ${(error as Error).message}. In AWS the engine task role is used (no keys); locally supply access keys or a role ARN the host credentials can assume.` };
  }
}

export function makeAwsAuth<T extends Record<string, unknown>>(extraProps: T, description: string) {
  return PieceAuth.CustomAuth({
    description,
    required: true,
    props: { ...awsAuthProps, ...extraProps },
    validate: async ({ auth }) => validateAws(auth),
  });
}

export function errorMessage(error: unknown): string {
  const e = error as { name?: string; message?: string; $metadata?: { httpStatusCode?: number } };
  return `${e?.name || 'Error'}: ${e?.message || String(error)}${e?.$metadata?.httpStatusCode ? ` (HTTP ${e.$metadata.httpStatusCode})` : ''}`;
}

export function parseJsonInput(value: unknown, label: string): unknown {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON`);
  }
}

export function svgLogo(fill: string, glyph: string): string {
  return (
    'data:image/svg+xml;utf8,' +
    encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="${fill}"/>${glyph}</svg>`)
  );
}
