import { Skeleton, TableSkeleton } from "@freelancer-os/ui";

export default function Loading() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-busy="true" aria-label="Loading page">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <TableSkeleton rows={5} columns={4} />
    </div>
  );
}
