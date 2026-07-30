import { DashboardOverview } from "@/src/features/dashboard/dashboard-overview";
import { getDashboardSnapshot } from "@/src/lib/api/server-dal";

export default async function DashboardPage() {
  return <DashboardOverview initialData={await getDashboardSnapshot()} />;
}
