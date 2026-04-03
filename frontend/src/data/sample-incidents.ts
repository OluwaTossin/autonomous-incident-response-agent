export interface SampleIncident {
  id: string;
  label: string;
  payload: Record<string, unknown>;
}

export const SAMPLE_INCIDENTS: SampleIncident[] = [
  {
    id: "payment-cpu",
    label: "Payment API — high CPU (production)",
    payload: {
      alert_title: "HighCPU on payment-api",
      service_name: "payment-api",
      environment: "production",
      metric_summary: "CPU 94%, p99 latency 820ms, error rate 3.2%",
      logs:
        "WARN fraud-module timeout; metrics CPU 91-97%; autoscaler scaling 3->6 replicas",
      time_of_occurrence: "2026-04-10T14:05:00Z",
    },
  },
  {
    id: "db-connections",
    label: "Orders DB — connection pool exhaustion",
    payload: {
      alert_title: "PostgreSQL too many connections",
      service_name: "orders-db",
      environment: "production",
      metric_summary: "Active connections 198/200, new connections rejected",
      logs:
        "FATAL: sorry, too many clients already\nDETAIL: remaining connection slots are reserved",
      time_of_occurrence: "2026-04-10T15:22:00Z",
    },
  },
  {
    id: "minimal",
    label: "Minimal payload (sparse)",
    payload: {
      alert_title: "Latency spike",
      service_name: "checkout-api",
      environment: "staging",
    },
  },
];
