# Network Module

Planned resources:

- VPC
- Public subnets for CloudFront/API Gateway edge-facing dependencies where needed
- Private subnets for ECS and Aurora
- Route tables
- NAT Gateway for ECS outbound calls to Groq
- Security groups

The AI Gateway should not accept direct public inbound traffic. API Gateway is the public HTTPS entry point.
