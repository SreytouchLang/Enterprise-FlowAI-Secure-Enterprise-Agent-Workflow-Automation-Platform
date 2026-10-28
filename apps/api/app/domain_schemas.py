"""Strict schemas for business tools and the allowlisted workflow language."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InvoiceLine(StrictModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    unit_price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def exact_numbers(cls, value):
        if isinstance(value, float):
            raise ValueError("Send monetary values as decimal strings, not floating point numbers")
        return value


class InvoiceData(StrictModel):
    vendor_name: str = Field(min_length=1, max_length=200)
    invoice_number: str = Field(min_length=1, max_length=100)
    invoice_date: date
    due_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    subtotal: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tax: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    total: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    line_items: list[InvoiceLine] = Field(min_length=1, max_length=200)

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def exact_numbers(cls, value):
        if isinstance(value, float):
            raise ValueError("Send monetary values as decimal strings")
        return value


class DocumentAction(StrictModel):
    document_id: str = Field(min_length=1, max_length=36)
    provider: Literal["openai", "anthropic"] = "openai"
    model: str | None = Field(default=None, max_length=100)


class InvoiceExtract(DocumentAction):
    department_id: str
    expected_vendor: str | None = Field(default=None, max_length=200)


class ManualInvoice(StrictModel):
    department_id: str
    document_id: str | None = None
    data: InvoiceData
    expected_vendor: str | None = Field(default=None, max_length=200)


class TemplateTask(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    required_document: str | None = Field(default=None, max_length=200)


class TemplateInput(StrictModel):
    department_id: str
    name: str = Field(min_length=1, max_length=120)
    tasks: list[TemplateTask] = Field(min_length=1, max_length=60)


class OnboardingInput(StrictModel):
    department_id: str
    employee_name: str = Field(min_length=1, max_length=160)
    employee_email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=250)
    start_date: date
    template_id: str | None = None


class TaskUpdate(StrictModel):
    completed: bool | None = None
    assigned_to: str | None = None


class Evidence(StrictModel):
    document_id: str
    quote: str = Field(min_length=5, max_length=1500)


class LegalAnalysis(StrictModel):
    document_type: str = Field(max_length=100)
    parties: list[str] = Field(max_length=30)
    effective_date: date | None = None
    termination_date: date | None = None
    renewal_type: str = Field(max_length=200)
    summary: str = Field(max_length=5000)
    obligations: list[str] = Field(max_length=40)
    termination_clauses: list[str] = Field(max_length=30)
    review_flags: list[str] = Field(max_length=30)
    changes: list[str] = Field(default_factory=list, max_length=40)
    evidence: list[Evidence] = Field(min_length=1, max_length=30)
    requires_human_review: Literal[True] = True


class LegalInput(DocumentAction):
    department_id: str
    comparison_document_id: str | None = None


class SummaryData(StrictModel):
    summary: str = Field(min_length=1, max_length=6000)
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


class PropertySourceInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    fields: dict[str, str | int | float | None] = Field(max_length=30)


class PropertyInput(StrictModel):
    department_id: str
    property_id: str = Field(min_length=1, max_length=80)
    sources: list[PropertySourceInput] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_source_names(self):
        names = [source.name for source in self.sources]
        if len(names) != len(set(names)):
            raise ValueError("Source names must be unique")
        return self


class PropertyReviewInput(StrictModel):
    resolved_fields: dict[str, str | int | float | None] = Field(max_length=30)
    comment: str = Field(min_length=1, max_length=2000)


class EmptyConfig(StrictModel):
    pass


class DocumentConfig(StrictModel):
    document_id: str | None = None
    input_field: str = Field(default="document_id", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,70}$")


class ClassificationConfig(StrictModel):
    categories: dict[str, list[str]] = Field(min_length=1, max_length=20)
    fallback: str = Field(default="unclassified", max_length=80)


class RagConfig(StrictModel):
    query: str | None = Field(default=None, max_length=2000)
    input_field: str = Field(default="query", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,70}$")
    limit: int = Field(default=5, ge=1, le=10)


class ExtractionConfig(StrictModel):
    schema_name: Literal["invoice", "legal"] = Field(default="invoice", alias="schema")
    provider: Literal["openai", "anthropic"] = "openai"
    model: str | None = Field(default=None, max_length=100)


class ConditionConfig(StrictModel):
    field: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.]{0,100}$")
    operator: Literal["eq", "ne", "gt", "gte", "lt", "exists"] = "eq"
    value: str | int | bool | None = None


class ValidationConfig(StrictModel):
    schema_name: Literal["invoice", "required_fields"] = Field(default="required_fields", alias="schema")
    fields: list[str] = Field(default_factory=list, max_length=40)


class ApprovalConfig(StrictModel):
    title: str = Field(default="Manager review", min_length=1, max_length=200)
    expires_hours: int = Field(default=48, ge=1, le=168)
    assigned_to: str | None = None


class NotificationConfig(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    message: str = Field(default="Workflow update", max_length=1000)


class TransformConfig(StrictModel):
    assign: dict[str, str | int | bool | None] = Field(max_length=30)

    @field_validator("assign")
    @classmethod
    def protected_fields(cls, value):
        if any(key.startswith("_") or key in {"document_ids", "text", "citations"} for key in value):
            raise ValueError("System context fields cannot be assigned")
        return value


NODE_CONFIGS: dict[str, type[BaseModel]] = {
    "start": EmptyConfig,
    "document_input": DocumentConfig,
    "text_extraction": EmptyConfig,
    "classification": ClassificationConfig,
    "rag_search": RagConfig,
    "llm_extraction": ExtractionConfig,
    "condition": ConditionConfig,
    "validation": ValidationConfig,
    "approval": ApprovalConfig,
    "notification": NotificationConfig,
    "transform": TransformConfig,
    "end": EmptyConfig,
}


class WorkflowNode(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    type: str
    config: dict = Field(default_factory=dict)
    position: dict[str, float] | None = None

    @model_validator(mode="after")
    def allowlisted_node(self):
        if self.type not in NODE_CONFIGS:
            raise ValueError("Unsupported workflow node type")
        self.config = NODE_CONFIGS[self.type].model_validate(self.config).model_dump(by_alias=True)
        return self


class WorkflowEdge(StrictModel):
    source: str
    target: str
    branch: Literal["true", "false"] | None = None


class WorkflowDefinition(StrictModel):
    nodes: list[WorkflowNode] = Field(min_length=2, max_length=64)
    edges: list[WorkflowEdge] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validated_dag(self):
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("Node IDs must be unique")
        starts = [node.id for node in self.nodes if node.type == "start"]
        ends = [node.id for node in self.nodes if node.type == "end"]
        if len(starts) != 1 or not ends:
            raise ValueError("Workflow requires exactly one start and at least one end")
        outgoing: dict[str, list[WorkflowEdge]] = {node: [] for node in nodes}
        incoming = {node: 0 for node in nodes}
        for edge in self.edges:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError("Edges must reference existing nodes")
            outgoing[edge.source].append(edge)
            incoming[edge.target] += 1
        for node in self.nodes:
            edges = outgoing[node.id]
            if node.type == "end":
                if edges:
                    raise ValueError("End nodes cannot have outgoing edges")
            elif node.type == "condition":
                if len(edges) != 2 or {edge.branch for edge in edges} != {"true", "false"}:
                    raise ValueError("Conditions require true and false branches")
            elif len(edges) != 1 or edges[0].branch is not None:
                raise ValueError("Non-condition nodes require one unlabelled outgoing edge")
        if incoming[starts[0]]:
            raise ValueError("Start cannot have incoming edges")
        visited, active = set(), set()

        def visit(node_id):
            if node_id in active:
                raise ValueError("Workflow cycles are forbidden")
            if node_id in visited:
                return
            active.add(node_id)
            for edge in outgoing[node_id]:
                visit(edge.target)
            active.remove(node_id)
            visited.add(node_id)

        visit(starts[0])
        if len(visited) != len(nodes):
            raise ValueError("All nodes must be reachable from start")
        return self


class WorkflowCreate(StrictModel):
    department_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    definition: WorkflowDefinition


class WorkflowUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    definition: WorkflowDefinition | None = None


class WorkflowStart(StrictModel):
    input: dict[str, Any] = Field(default_factory=dict, max_length=50)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("input")
    @classmethod
    def no_reserved_fields(cls, value):
        import json

        if len(json.dumps(value)) > 50000:
            raise ValueError("Workflow input exceeds 50KB")
        if any(key.startswith("_") or key in {"document_ids", "text", "citations"} for key in value):
            raise ValueError("Reserved workflow input field")
        return value


class DecisionInput(StrictModel):
    comment: str = Field(default="", max_length=2000)
