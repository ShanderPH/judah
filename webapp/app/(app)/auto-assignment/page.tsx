import { AutoAssignmentOverview } from "@/src/features/auto-assignment/auto-assignment-overview";
import { getAutoAssignmentSnapshot } from "@/src/lib/api/server-dal";

export default async function AutoAssignmentPage() {
  return <AutoAssignmentOverview initialData={await getAutoAssignmentSnapshot()} />;
}
