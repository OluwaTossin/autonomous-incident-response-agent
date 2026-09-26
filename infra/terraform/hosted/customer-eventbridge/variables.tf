variable "aira_event_bus_arn" {
  description = "AIRA-hosted EventBridge bus ARN supplied during integration onboarding."
  type        = string
}
variable "integration_id" {
  description = "Non-secret AIRA integration identifier used only for resource naming and support correlation."
  type        = string
}
variable "alarm_name_prefixes" {
  description = "Optional supported alarm-name prefixes. Empty forwards all alarm state changes in this region."
  type        = list(string)
  default     = []
}
