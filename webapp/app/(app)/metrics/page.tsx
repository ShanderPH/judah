import { MetricsOverview } from "@/src/features/metrics/metrics-overview";
import { getMetricsSnapshot } from "@/src/lib/api/server-dal";

export default async function MetricsPage() {
  return <MetricsOverview initialData={await getMetricsSnapshot()} />;
}
