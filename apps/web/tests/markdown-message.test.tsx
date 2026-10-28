import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownMessage } from "@/components/markdown-message";

describe("assistant Markdown", () => {
  it("renders structured answers with headings, lists, code, and tables", () => {
    render(
      <MarkdownMessage
        content={[
          "## Invoice review",
          "",
          "- **Manager approval** required",
          "- Check `invoice_number`",
          "",
          "| Field | Value |",
          "| --- | --- |",
          "| Total | $2,500.00 |",
        ].join("\n")}
      />,
    );
    expect(screen.getByRole("heading", { name: "Invoice review" })).toBeVisible();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Manager approval").tagName).toBe("STRONG");
    expect(screen.getByText("invoice_number").tagName).toBe("CODE");
    expect(screen.getByRole("cell", { name: "$2,500.00" })).toBeVisible();
  });

  it("does not execute HTML, activate script links, or fetch embedded images", () => {
    const { container } = render(
      <MarkdownMessage
        content={[
          '<script>alert("untrusted")</script>',
          '<iframe src="https://example.test/track"></iframe>',
          '<img src="https://example.test/raw" onerror="alert(1)">',
          "",
          "[Unsafe action](javascript:alert%281%29)",
          "",
          "![Source illustration](https://example.test/track?confidential=value)",
          "",
          "[Policy](https://example.test/policy)",
        ].join("\n")}
      />,
    );
    expect(container.querySelector("script, iframe, img")).toBeNull();
    expect(screen.queryByRole("link", { name: "Unsafe action" })).toBeNull();
    expect(screen.getByText("Source illustration")).toBeVisible();
    const link = screen.getByRole("link", { name: "Policy" });
    expect(link).toHaveAttribute("href", "https://example.test/policy");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
