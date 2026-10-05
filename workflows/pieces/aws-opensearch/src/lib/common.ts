import { Property } from '@activepieces/pieces-framework';
import { Sha256 } from '@aws-crypto/sha256-js';
import { HttpRequest } from '@smithy/protocol-http';
import { SignatureV4 } from '@smithy/signature-v4';
import { awsCredentials, makeAwsAuth, type AwsAuthValue } from '../../../aws-common/aws';

export type OpenSearchAuth = AwsAuthValue & { endpoint: string; service: 'es' | 'aoss' };

export const openSearchAuth = makeAwsAuth(
  {
    endpoint: Property.ShortText({
      displayName: 'Endpoint',
      description: 'https://<domain-endpoint> for a managed domain or https://<collection-id>.<region>.aoss.amazonaws.com for a serverless collection.',
      required: true,
    }),
    service: Property.StaticDropdown({
      displayName: 'Service',
      required: true,
      defaultValue: 'es',
      options: { options: [{ label: 'Managed domain (es)', value: 'es' }, { label: 'Serverless collection (aoss)', value: 'aoss' }] },
    }),
  },
  'Amazon OpenSearch Service. Requests are signed with SigV4 by the engine task role (or an assumed role). The role must also be allowed in the domain access policy or the serverless data-access policy.',
);

export async function signedRequest(auth: OpenSearchAuth, method: string, path: string, body?: unknown, query?: Record<string, string>): Promise<{ status: number; body: unknown }> {
  const url = new URL(auth.endpoint.replace(/\/+$/, ''));
  const payload = body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body);
  const request = new HttpRequest({
    method,
    protocol: url.protocol,
    hostname: url.hostname,
    path: path.startsWith('/') ? path : `/${path}`,
    query,
    headers: { host: url.hostname, ...(payload !== undefined ? { 'content-type': payload.startsWith('{') || payload.startsWith('[') ? 'application/json' : 'application/x-ndjson' } : {}) },
    body: payload,
  });
  const signer = new SignatureV4({ credentials: awsCredentials(auth), region: auth.region, service: auth.service === 'aoss' ? 'aoss' : 'es', sha256: Sha256 });
  const signed = await signer.sign(request);
  const qs = query ? '?' + new URLSearchParams(query).toString() : '';
  const response = await fetch(`${url.protocol}//${url.hostname}${request.path}${qs}`, { method, headers: signed.headers as Record<string, string>, body: payload });
  const text = await response.text();
  let parsed: unknown = text;
  try { parsed = text ? JSON.parse(text) : null; } catch { /* keep text */ }
  if (response.status >= 400) {
    throw new Error(`OpenSearch ${method} ${request.path} failed with HTTP ${response.status}: ${typeof parsed === 'string' ? parsed.slice(0, 500) : JSON.stringify(parsed).slice(0, 500)}`);
  }
  return { status: response.status, body: parsed };
}

export const indexProp = Property.ShortText({ displayName: 'Index', required: true });
