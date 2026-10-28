import { describe, it, expect } from "vitest";
import {
  defaultDefinition,
  validateWorkflow,
  type Definition,
} from "@/lib/workflow";
describe("workflow validation", () => {
  it("accepts a connected approval process", () =>
    expect(validateWorkflow(defaultDefinition)).toEqual([]));
  it("rejects cycles and terminal outgoing connections", () => {
    const def = structuredClone(defaultDefinition);
    def.edges.push({ source: "end", target: "start" });
    expect(validateWorkflow(def)).toEqual(
      expect.arrayContaining([
        "Cycles are not allowed. Use a bounded, directed workflow.",
        "End nodes cannot have outgoing connections.",
      ]),
    );
  });
  it("rejects disconnected nodes and invalid references", () => {
    const def = structuredClone(defaultDefinition);
    def.nodes.push({ id: "orphan", type: "notification", config: {} });
    def.edges.push({ source: "unknown", target: "end" });
    expect(validateWorkflow(def)).toContain(
      "Connect every node to the start node.",
    );
    expect(validateWorkflow(def)).toContain(
      "All connections must reference existing nodes.",
    );
  });
  it("requires both condition branches", () => {
    const def: Definition = {
      nodes: [
        { id: "start", type: "start", config: {} },
        { id: "decision", type: "condition", config: {} },
        { id: "end", type: "end", config: {} },
      ],
      edges: [
        { source: "start", target: "decision" },
        { source: "decision", target: "end", branch: "true" },
      ],
    };
    expect(validateWorkflow(def)).toContain(
      "Condition decision needs true and false connections.",
    );
    def.edges.push({ source: "decision", target: "end", branch: "false" });
    expect(validateWorkflow(def)).toEqual([]);
  });
});
