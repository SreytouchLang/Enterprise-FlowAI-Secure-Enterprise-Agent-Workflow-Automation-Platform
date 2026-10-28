"use client";
import { Plus, Trash2 } from "lucide-react";
import { Field } from "./common";
import { Button } from "./ui/button";
type Line = {
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
};
type Invoice = {
  vendor_name: string;
  invoice_number: string;
  invoice_date: string;
  due_date: string;
  currency: string;
  subtotal: string;
  tax: string;
  total: string;
  line_items: Line[];
};
export function InvoiceFields({
  value,
  onChange,
}: {
  value: string;
  onChange: (json: string) => void;
}) {
  let invoice: Invoice;
  try {
    invoice = JSON.parse(value);
  } catch {
    return (
      <p role="alert">
        Invoice fields could not be read. Close this dialog and open the record
        again.
      </p>
    );
  }
  function update(key: keyof Invoice, next: unknown) {
    onChange(JSON.stringify({ ...invoice, [key]: next }, null, 2));
  }
  function line(index: number, key: keyof Line, value: string) {
    update(
      "line_items",
      invoice.line_items.map((item, i) =>
        i === index ? { ...item, [key]: value } : item,
      ),
    );
  }
  return (
    <div className="form-stack">
      <div className="form-grid">
        <Field label="Vendor name">
          <input
            value={invoice.vendor_name}
            onChange={(e) => update("vendor_name", e.target.value)}
            required
          />
        </Field>
        <Field label="Invoice number">
          <input
            value={invoice.invoice_number}
            onChange={(e) => update("invoice_number", e.target.value)}
            required
          />
        </Field>
        <Field label="Invoice date">
          <input
            type="date"
            value={invoice.invoice_date}
            onChange={(e) => update("invoice_date", e.target.value)}
            required
          />
        </Field>
        <Field label="Due date">
          <input
            type="date"
            value={invoice.due_date}
            onChange={(e) => update("due_date", e.target.value)}
            required
          />
        </Field>
        <Field label="Currency">
          <select
            value={invoice.currency}
            onChange={(e) => update("currency", e.target.value)}
          >
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
            <option value="GBP">GBP</option>
            <option value="CAD">CAD</option>
            <option value="AUD">AUD</option>
          </select>
        </Field>
      </div>
      <div>
        <h3>Line items</h3>
        {invoice.line_items.map((item, index) => (
          <div
            key={index}
            style={{
              marginTop: 13,
              padding: 14,
              border: "1px solid var(--line)",
              borderRadius: 8,
            }}
          >
            <div className="inline-actions" style={{ marginBottom: 10 }}>
              <Field label={`Item ${index + 1} description`}>
                <input
                  value={item.description}
                  required
                  onChange={(e) => line(index, "description", e.target.value)}
                />
              </Field>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={invoice.line_items.length === 1}
                aria-label={`Remove item ${index + 1}`}
                onClick={() =>
                  update(
                    "line_items",
                    invoice.line_items.filter((_, i) => i !== index),
                  )
                }
              >
                <Trash2 size={14} />
              </Button>
            </div>
            <div className="form-grid">
              <Field label={`Item ${index + 1} quantity`}>
                <input
                  inputMode="decimal"
                  value={item.quantity}
                  required
                  onChange={(e) => line(index, "quantity", e.target.value)}
                />
              </Field>
              <Field label={`Item ${index + 1} unit price`}>
                <input
                  inputMode="decimal"
                  value={item.unit_price}
                  required
                  onChange={(e) => line(index, "unit_price", e.target.value)}
                />
              </Field>
              <Field label={`Item ${index + 1} amount`}>
                <input
                  inputMode="decimal"
                  value={item.amount}
                  required
                  onChange={(e) => line(index, "amount", e.target.value)}
                />
              </Field>
            </div>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          style={{ marginTop: 12 }}
          onClick={() =>
            update("line_items", [
              ...invoice.line_items,
              {
                description: "",
                quantity: "1",
                unit_price: "0.00",
                amount: "0.00",
              },
            ])
          }
        >
          <Plus size={13} />
          Add line item
        </Button>
      </div>
      <div className="form-grid">
        {(["subtotal", "tax", "total"] as const).map((key) => (
          <Field key={key} label={key.charAt(0).toUpperCase() + key.slice(1)}>
            <input
              inputMode="decimal"
              value={invoice[key]}
              required
              onChange={(e) => update(key, e.target.value)}
            />
          </Field>
        ))}
      </div>
      <p className="text-muted">
        Enter the amounts shown on the invoice. Totals, dates, duplicate
        numbers, and approval thresholds are validated when saved.
      </p>
    </div>
  );
}
