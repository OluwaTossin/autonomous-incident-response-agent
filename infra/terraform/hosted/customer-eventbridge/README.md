# Customer CloudWatch Alarm Forwarder

Instantiate this module with the customer's AWS provider in every supported CloudWatch
alarm region. It creates a regional EventBridge rule and least-privilege forwarding role
targeting the AIRA event-bus ARN supplied during onboarding. It creates no access keys and
contains no AIRA secret.

An empty `alarm_name_prefixes` list forwards every CloudWatch alarm state change in that
region. Prefer explicit prefixes for the initial narrow integration. AIRA operations must
also register the account/region/integration route and allowlist the account in the hosted
platform plan; the event payload itself never selects a tenant.

This module is an onboarding artifact only. V3.22 did not apply it in any customer account.
