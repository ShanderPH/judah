import { AgentsOverview } from "@/src/features/agents/agents-overview";
import { getAgentsSnapshot } from "@/src/lib/api/server-dal";

export default async function AgentsPage() {
  return <AgentsOverview initialData={await getAgentsSnapshot()} />;
}
