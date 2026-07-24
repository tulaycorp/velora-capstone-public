import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function DashboardSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-live="polite">
      <span className="sr-only">Loading overview dashboard...</span>
      
      {/* Metric Cards Grid */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="border-border">
            <CardContent className="p-6">
              <Skeleton className="h-4 w-20 opacity-75" />
              <Skeleton className="mt-2.5 h-8 w-16" />
              <Skeleton className="mt-2 h-3.5 w-32 opacity-50" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Middle Grid */}
      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        {/* Recent Products Card */}
        <Card className="overflow-hidden border-border">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle>
              <Skeleton className="h-5 w-36" />
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader className="bg-muted/40 text-muted-foreground border-b border-border">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[88px]"><Skeleton className="h-3 w-10" /></TableHead>
                  <TableHead><Skeleton className="h-3 w-16" /></TableHead>
                  <TableHead><Skeleton className="h-3 w-14" /></TableHead>
                  <TableHead><Skeleton className="h-3 w-12" /></TableHead>
                  <TableHead><Skeleton className="h-3 w-16" /></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i} className="border-b border-border/50">
                    <TableCell className="py-3">
                      <Skeleton className="h-10 w-10 rounded-md" />
                    </TableCell>
                    <TableCell className="py-3">
                      <div className="space-y-1.5">
                        <Skeleton className="h-4 w-40" />
                        <Skeleton className="h-3.5 w-24 opacity-60" />
                      </div>
                    </TableCell>
                    <TableCell className="py-3">
                      <Skeleton className="h-5 w-16 rounded-full" />
                    </TableCell>
                    <TableCell className="py-3">
                      <Skeleton className="h-5 w-24 rounded-full" />
                    </TableCell>
                    <TableCell className="py-3">
                      <Skeleton className="h-5.5 w-16 rounded-full" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Product Studio Flow */}
        <Card className="border-border">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle>
              <Skeleton className="h-5 w-44" />
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-border">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3">
                  <Skeleton className="h-4 w-4 rounded-full opacity-60" />
                  <Skeleton className="h-4 w-48" />
                </div>
              ))}
            </div>
          </CardContent>
          <CardFooter className="border-t border-border px-4 py-3">
            <Skeleton className="h-9 w-full" />
          </CardFooter>
        </Card>
      </div>

      {/* Bottom Grid */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* Blueprint Health */}
        <Card className="overflow-hidden border-border">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle>
              <Skeleton className="h-5 w-32" />
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="flex items-start justify-between gap-3 rounded-md border border-border bg-background p-3"
              >
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-44" />
                  <Skeleton className="h-5 w-20 rounded-full" />
                  <Skeleton className="h-3.5 w-16 opacity-60" />
                </div>
                <Skeleton className="h-5.5 w-16 rounded-full" />
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Publishing Jobs */}
        <Card className="overflow-hidden border-border">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle>
              <Skeleton className="h-5 w-32" />
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="flex items-start justify-between gap-3 rounded-md border border-border bg-background p-3"
              >
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3.5 w-28 opacity-60" />
                </div>
                <Skeleton className="h-5.5 w-16 rounded-full" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function BlueprintsSkeleton() {
  return (
    <div className="mt-5 overflow-hidden rounded-lg border border-border bg-card animate-pulse" role="status" aria-live="polite">
      <span className="sr-only">Loading blueprints...</span>
      <Table>
        <TableHeader className="bg-muted/40 text-muted-foreground border-b border-border">
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[34%]"><Skeleton className="h-4 w-20" /></TableHead>
            <TableHead className="w-[24%]"><Skeleton className="h-4 w-12" /></TableHead>
            <TableHead className="w-[22%]"><Skeleton className="h-4 w-16" /></TableHead>
            <TableHead className="w-[19%]"><Skeleton className="h-4 w-10" /></TableHead>
            <TableHead className="w-[1%] text-left"><Skeleton className="h-4 w-12" /></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 4 }).map((_, i) => (
            <TableRow key={i} className="border-b border-border/50">
              <TableCell className="align-top py-3">
                <div className="space-y-2">
                  <Skeleton className="h-4.5 w-48" />
                  <Skeleton className="h-3.5 w-36 opacity-60" />
                  <Skeleton className="h-3 w-28 opacity-40" />
                </div>
              </TableCell>
              <TableCell className="align-top py-3">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-5 w-5 rounded-full" />
                  <Skeleton className="h-4 w-24" />
                </div>
              </TableCell>
              <TableCell className="align-top py-3">
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3.5 w-36 font-mono opacity-60" />
                </div>
              </TableCell>
              <TableCell className="align-top py-3">
                <Skeleton className="h-4.5 w-12 font-mono" />
              </TableCell>
              <TableCell className="align-top py-3">
                <Skeleton className="h-8 w-16 rounded-md" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function ProductsSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-live="polite">
      <span className="sr-only">Loading products...</span>
      {/* Tabs Placeholder */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          <Skeleton className="h-8.5 w-24 rounded-md" />
          <Skeleton className="h-8.5 w-24 rounded-md" />
        </div>
        <Skeleton className="h-4.5 w-24 opacity-60" />
      </div>

      {/* Products Table */}
      <div className="overflow-hidden rounded-lg border border-border bg-card animate-pulse">
        <Table>
          <TableHeader className="bg-muted/55 border-b border-border">
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[88px] px-4" />
              <TableHead className="min-w-[280px] px-4"><Skeleton className="h-4 w-12" /></TableHead>
              <TableHead className="px-4"><Skeleton className="h-4 w-10" /></TableHead>
              <TableHead className="min-w-[220px] px-4"><Skeleton className="h-4 w-12" /></TableHead>
              <TableHead className="min-w-[220px] px-4"><Skeleton className="h-4 w-16" /></TableHead>
              <TableHead className="px-4 text-left"><Skeleton className="h-4 w-12" /></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 4 }).map((_, i) => (
              <TableRow key={i} className="border-b border-border/50">
                <TableCell className="h-[78px] px-4 py-3">
                  <Skeleton className="h-12 w-12 rounded-md" />
                </TableCell>
                <TableCell className="h-[78px] px-4 py-3">
                  <div className="space-y-1.5">
                    <Skeleton className="h-4 w-52" />
                    <Skeleton className="h-3 w-28 opacity-60" />
                  </div>
                </TableCell>
                <TableCell className="h-[78px] px-4 py-3">
                  <Skeleton className="h-4 w-20" />
                </TableCell>
                <TableCell className="h-[78px] px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-5 w-5 rounded-full" />
                    <Skeleton className="h-4 w-28" />
                  </div>
                </TableCell>
                <TableCell className="h-[78px] px-4 py-3">
                  <Skeleton className="h-4.5 w-24" />
                </TableCell>
                <TableCell className="h-[78px] px-4 py-3">
                  <div className="flex gap-2">
                    <Skeleton className="h-8.5 w-16 rounded-md" />
                    <Skeleton className="h-8.5 w-8 rounded-md" />
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export function ProductStudioSkeleton() {
  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]" role="status" aria-live="polite">
      <span className="sr-only">Loading Product Studio...</span>
      
      {/* Primary Editing Frame */}
      <div className="overflow-hidden rounded-lg border border-border bg-card space-y-6 pb-6">
        <div className="flex flex-col gap-3 border-b border-border bg-background/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0 space-y-1.5">
            <Skeleton className="h-4.5 w-40" />
            <div className="flex items-center gap-3">
              <Skeleton className="h-3 w-24 opacity-60" />
              <Skeleton className="h-3 w-16 opacity-60" />
              <Skeleton className="h-3 w-16 opacity-60" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-5.5 w-20 rounded-full" />
            <Skeleton className="h-5.5 w-20 rounded-full" />
          </div>
        </div>

        {/* SurfaceSection: Images */}
        <div className="px-5 sm:px-6 space-y-4">
          <Skeleton className="h-5 w-20" /> {/* Section Title */}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4.5 w-24 opacity-65" />
              <div className="flex min-h-80 flex-col items-center justify-center rounded-md border border-dashed border-input bg-background/40 p-6 text-center">
                <Skeleton className="h-9 w-9 rounded-md opacity-40" />
                <Skeleton className="mt-3 h-4 w-36" />
                <Skeleton className="mt-4 h-9 w-full rounded-md" />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4.5 w-32 opacity-65" />
              <Skeleton className="min-h-80 w-full rounded-md" />
            </div>
          </div>

          <div className="border-t border-border pt-6 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <Skeleton className="h-4.5 w-24" />
              <Skeleton className="h-3 w-28 opacity-60" />
            </div>
            <div className="rounded-md border border-border bg-background/40 p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <Skeleton className="h-3.5 w-20 opacity-60" />
                <Skeleton className="h-3.5 w-28 opacity-60" />
              </div>
              <div className="grid auto-rows-fr grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-5">
                <Skeleton className="relative aspect-square rounded-md sm:col-span-2 sm:row-span-2" />
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="aspect-square rounded-md" />
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* SurfaceSection: Listing */}
        <div className="border-t border-border pt-6 px-5 sm:px-6 space-y-4">
          <Skeleton className="h-5 w-16" />
          <div className="grid gap-5">
            <div className="grid gap-2">
              <Skeleton className="h-4 w-10 opacity-65" />
              <Skeleton className="h-9 w-full rounded-md" />
            </div>
            <div className="grid gap-2">
              <Skeleton className="h-4 w-32 opacity-65" />
              <Skeleton className="h-[200px] w-full rounded-md" />
            </div>
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_220px]">
              <div className="rounded-md border border-border bg-background/40 p-4 space-y-3">
                <Skeleton className="h-4 w-12" />
                <div className="flex gap-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-16 rounded-md" />
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-10 opacity-65" />
                <Skeleton className="h-9 w-full rounded-md" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Side Rail */}
      <aside className="overflow-hidden rounded-lg border border-border bg-card space-y-6">
        <div className="border-b border-border bg-background/35 px-5 py-4 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-4.5 w-28" />
            <Skeleton className="h-5.5 w-16 rounded-full" />
          </div>
          <Skeleton className="h-9 w-full rounded-md" />
        </div>
        
        {/* Blueprint Context section */}
        <div className="px-5 space-y-3">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-9 w-full rounded-md" />
          <div className="rounded-md border border-border bg-background p-3 space-y-2.5">
            <div className="flex justify-between"><Skeleton className="h-3.5 w-16" /><Skeleton className="h-3.5 w-24" /></div>
            <div className="flex justify-between"><Skeleton className="h-3.5 w-24" /><Skeleton className="h-3.5 w-20" /></div>
            <div className="flex justify-between"><Skeleton className="h-3.5 w-16" /><Skeleton className="h-3.5 w-16" /></div>
          </div>
        </div>

        {/* Pricing section */}
        <div className="px-5 pb-6 border-t border-border pt-5 space-y-3">
          <Skeleton className="h-4 w-16" />
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4.5 w-20 opacity-65" />
            <Skeleton className="h-9 w-full rounded-md" />
          </div>
        </div>
      </aside>
    </div>
  );
}

export function ProductDetailSkeleton() {
  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]" role="status" aria-live="polite">
      <span className="sr-only">Loading product details...</span>

      <div className="overflow-hidden rounded-lg border border-border bg-card space-y-6 pb-6">
        <div className="flex flex-col gap-3 border-b border-border bg-background/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0 space-y-1.5">
            <Skeleton className="h-4.5 w-40" />
            <div className="flex items-center gap-3">
              <Skeleton className="h-3 w-24 opacity-60" />
              <Skeleton className="h-3 w-16 opacity-60" />
              <Skeleton className="h-3 w-16 opacity-60" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-5.5 w-20 rounded-full" />
            <Skeleton className="h-5.5 w-20 rounded-full" />
          </div>
        </div>

        <div className="px-5 sm:px-6 space-y-4">
          <Skeleton className="h-5 w-20" />
          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4.5 w-24 opacity-65" />
              <div className="flex min-h-80 flex-col items-center justify-center rounded-md border border-dashed border-input bg-background/40 p-6 text-center">
                <Skeleton className="h-9 w-9 rounded-md opacity-40" />
                <Skeleton className="mt-3 h-4 w-36" />
                <Skeleton className="mt-4 h-9 w-full rounded-md" />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4.5 w-32 opacity-65" />
              <Skeleton className="min-h-80 w-full rounded-md" />
            </div>
          </div>

          <div className="border-t border-border pt-6 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <Skeleton className="h-4.5 w-24" />
              <Skeleton className="h-3 w-28 opacity-60" />
            </div>
            <div className="rounded-md border border-border bg-background/40 p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <Skeleton className="h-3.5 w-20 opacity-60" />
                <Skeleton className="h-3.5 w-28 opacity-60" />
              </div>
              <div className="grid auto-rows-fr grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-5">
                <Skeleton className="relative aspect-square rounded-md sm:col-span-2 sm:row-span-2" />
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="aspect-square rounded-md" />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="border-t border-border pt-6 px-5 sm:px-6 space-y-4">
          <Skeleton className="h-5 w-16" />
          <div className="grid gap-5">
            <div className="grid gap-2">
              <Skeleton className="h-4 w-20 opacity-65" />
              <Skeleton className="h-9 w-full rounded-md" />
            </div>
            <div className="grid gap-2">
              <Skeleton className="h-4 w-32 opacity-65" />
              <Skeleton className="h-[200px] w-full rounded-md" />
            </div>
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_220px]">
              <div className="rounded-md border border-border bg-background/40 p-4 space-y-3">
                <Skeleton className="h-4 w-12" />
                <div className="flex gap-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-16 rounded-md" />
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-10 opacity-65" />
                <Skeleton className="h-9 w-full rounded-md" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <aside className="overflow-hidden rounded-lg border border-border bg-card space-y-6">
        <div className="border-b border-border bg-background/35 px-5 py-4 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-4.5 w-28" />
            <Skeleton className="h-5.5 w-16 rounded-full" />
          </div>
          <Skeleton className="h-9 w-full rounded-md" />
        </div>

        <div className="px-5 space-y-3">
          <Skeleton className="h-4 w-16" />
          <div className="rounded-md border border-border bg-background p-3 space-y-2.5">
            <div className="flex justify-between"><Skeleton className="h-3.5 w-16" /><Skeleton className="h-3.5 w-24" /></div>
            <div className="flex justify-between"><Skeleton className="h-3.5 w-24" /><Skeleton className="h-3.5 w-20" /></div>
            <div className="flex justify-between"><Skeleton className="h-3.5 w-16" /><Skeleton className="h-3.5 w-16" /></div>
          </div>
        </div>

        <div className="px-5 pb-6 border-t border-border pt-5 space-y-3">
          <Skeleton className="h-4 w-16" />
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4.5 w-20 opacity-65" />
            <Skeleton className="h-9 w-full rounded-md" />
          </div>
        </div>

        <div className="px-5 pb-6 border-t border-border pt-5 space-y-3">
          <Skeleton className="h-4 w-24" />
          <div className="flex justify-between">
            <Skeleton className="h-3.5 w-16" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <div className="flex justify-between">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-md border border-border bg-background p-3">
                <Skeleton className="h-3.5 w-32" />
              </div>
            ))}
          </div>
          <Skeleton className="h-9 w-full rounded-md" />
        </div>
      </aside>
    </div>
  );
}

export function SettingsSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-live="polite">
      <span className="sr-only">Loading organization settings...</span>
      
      {/* Access Management Section */}
      <Card className="border-border">
        <CardHeader className="border-b border-border bg-background/15 px-5 py-4">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-4 rounded-full opacity-65" />
            <Skeleton className="h-4.5 w-36" />
          </div>
        </CardHeader>
        <CardContent className="p-5 space-y-5">
          {/* Invite Code block */}
          <div className="rounded-xl border border-border bg-background/35 px-4 py-4 space-y-2">
            <Skeleton className="h-5 w-20 rounded-full" />
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-60 opacity-60" />
          </div>

          {/* Pending Requests block */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-5 w-6 rounded-full" />
            </div>
            <div className="rounded-lg border border-border p-4">
              <Skeleton className="h-4.5 w-44" />
              <Skeleton className="mt-1 h-3.5 w-64 opacity-60" />
            </div>
          </div>

          {/* Members block */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-5 w-6 rounded-full" />
            </div>
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader className="bg-muted/30 border-b border-border">
                  <TableRow className="hover:bg-transparent">
                    <TableHead><Skeleton className="h-3.5 w-10" /></TableHead>
                    <TableHead><Skeleton className="h-3.5 w-10" /></TableHead>
                    <TableHead><Skeleton className="h-3.5 w-12" /></TableHead>
                    <TableHead className="w-[180px]"><Skeleton className="h-3.5 w-14" /></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Array.from({ length: 2 }).map((_, i) => (
                    <TableRow key={i} className="border-b border-border/50">
                      <TableCell className="py-3">
                        <Skeleton className="h-4.5 w-28" />
                        <Skeleton className="mt-1 h-3.5 w-36 opacity-60" />
                      </TableCell>
                      <TableCell className="py-3">
                        <Skeleton className="h-5.5 w-14 rounded-full" />
                      </TableCell>
                      <TableCell className="py-3">
                        <Skeleton className="h-3.5 w-24" />
                      </TableCell>
                      <TableCell className="py-3">
                        <Skeleton className="h-8.5 w-16 rounded-md" />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Provider Setup Section */}
      <Card className="border-border">
        <CardHeader className="border-b border-border bg-background/15 px-5 py-4">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-4 rounded-full opacity-65" />
            <Skeleton className="h-4.5 w-28" />
          </div>
        </CardHeader>
        <CardContent className="p-5 space-y-4">
          {/* Provider selector grid */}
          <div className="grid gap-4 lg:grid-cols-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 rounded-xl border border-border p-4">
                <Skeleton className="h-10 w-10 rounded-lg" />
                <div className="space-y-1.5 flex-1">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3 w-32 opacity-60" />
                </div>
                <Skeleton className="h-5.5 w-20 rounded-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function GenericPageSkeleton() {
  return (
    <div className="flex flex-col gap-4 animate-pulse" role="status" aria-live="polite">
      <span className="sr-only">Loading page data...</span>
      <Skeleton className="h-24 w-full rounded-lg" />
      <Skeleton className="h-[320px] w-full rounded-lg" />
    </div>
  );
}
