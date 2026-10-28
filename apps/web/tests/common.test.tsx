import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DataTable, ErrorState } from "@/components/common";
import { ApiError } from "@/lib/api";
describe("record views", () => {
  it("filters before paginating and provides a useful empty state", () => {
    const records = Array.from({ length: 12 }, (_, i) => ({
      id: String(i),
      name: `Record ${i}`,
    }));
    render(
      <DataTable
        items={records}
        filterKey={(r) => r.name}
        columns={[{ key: "name", label: "Name", render: (r) => r.name }]}
      />,
    );
    expect(screen.queryByText("Record 9")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Next page"));
    expect(screen.getByText("Record 9")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter records"), {
      target: { value: "Record 1" },
    });
    expect(screen.getByText("Showing 1–3 of 3")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter records"), {
      target: { value: "Missing" },
    });
    expect(screen.getByText("No records found")).toBeInTheDocument();
  });
  it("shows authorization failure explicitly", () => {
    render(
      <ErrorState error={new ApiError(403, "Department access denied")} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Access restricted");
    expect(screen.getByText("Department access denied")).toBeVisible();
  });
});
