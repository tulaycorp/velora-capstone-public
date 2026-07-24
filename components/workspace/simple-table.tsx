import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";

export type Column<T> = {
  key: keyof T | string;
  label: string;
  className?: string;
  render?: (row: T) => React.ReactNode;
};

export function SimpleTable<T extends object>({
  columns,
  rows,
  className,
  tableClassName,
}: {
  columns: Column<T>[];
  rows: T[];
  className?: string;
  tableClassName?: string;
}) {
  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-card", className)}>
      <Table className={tableClassName}>
        <TableHeader className="bg-muted/60 text-muted-foreground">
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => (
              <TableHead
                key={String(column.key)}
                className={cn("h-11 px-4 text-xs font-semibold", column.className)}
              >
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow
              key={index}
              className="border-border hover:bg-muted/35"
            >
              {columns.map((column) => (
                <TableCell
                  key={String(column.key)}
                  className={cn(
                    "h-[72px] px-4 py-3 align-middle text-card-foreground",
                    column.className
                  )}
                >
                  {column.render
                    ? column.render(row)
                    : String((row as Record<string, unknown>)[String(column.key)] ?? "")}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
