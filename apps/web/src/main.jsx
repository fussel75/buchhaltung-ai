import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const apiBaseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL ?? "/api");

function resolveApiBaseUrl(configuredUrl) {
  if (typeof window === "undefined") return configuredUrl;

  const currentHost = window.location.hostname;
  const isLocalPage = ["localhost", "127.0.0.1", "::1"].includes(currentHost);
  if (isLocalPage) return configuredUrl;

  try {
    const url = new URL(configuredUrl, window.location.origin);
    if (["localhost", "127.0.0.1", "::1"].includes(url.hostname)) {
      return "/api";
    }
  } catch {
    return configuredUrl;
  }

  return configuredUrl;
}

function App() {
  const [tenantId, setTenantId] = useState("demo-mandant");
  const [isDragging, setIsDragging] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [extractingIds, setExtractingIds] = useState([]);

  const canUpload = useMemo(() => tenantId.trim().length > 0, [tenantId]);
  const activeTenantId = tenantId.trim();

  const loadDocuments = useCallback(async () => {
    if (!activeTenantId) {
      setDocuments([]);
      return;
    }

    const response = await fetch(
      `${apiBaseUrl}/documents?tenant_id=${encodeURIComponent(activeTenantId)}`,
    );

    if (!response.ok) {
      throw new Error(`Review-Queue konnte nicht geladen werden: ${response.status}`);
    }

    const result = await response.json();
    setDocuments(result.documents ?? []);
  }, [activeTenantId]);

  useEffect(() => {
    loadDocuments().catch((loadError) => setError(loadError.message));
  }, [loadDocuments]);

  const uploadFile = useCallback(
    async (file) => {
      setError("");
      setNotice("");

      const formData = new FormData();
      formData.append("tenant_id", activeTenantId);
      formData.append("file", file);

      const response = await fetch(`${apiBaseUrl}/documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Upload fehlgeschlagen: ${response.status}`);
      }

      const result = await response.json();
      await loadDocuments();
      setNotice(
        result.is_duplicate
          ? `Dublette erkannt: ${result.document.original_filename} ist bereits in der Review-Queue.`
          : `Beleg gespeichert: ${result.document.original_filename}`,
      );
    },
    [activeTenantId, loadDocuments],
  );

  const handleFiles = useCallback(
    async (files) => {
      if (!canUpload) return;
      try {
        for (const file of files) {
          await uploadFile(file);
        }
      } catch (uploadError) {
        setError(uploadError.message);
      }
    },
    [canUpload, uploadFile],
  );

  const startExtraction = useCallback(
    async (documentId) => {
      setError("");
      setNotice("");
      setExtractingIds((current) => [...current, documentId]);

      try {
        const response = await fetch(`${apiBaseUrl}/documents/${documentId}/extract`, {
          method: "POST",
        });

        if (!response.ok) {
          throw new Error(`Extraktion fehlgeschlagen: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Mock-Extraktion erstellt: ${result.document.original_filename}`);
      } catch (extractError) {
        setError(extractError.message);
      } finally {
        setExtractingIds((current) => current.filter((id) => id !== documentId));
      }
    },
    [loadDocuments],
  );

  return (
    <main className="app">
      <section className="toolbar">
        <div>
          <p className="eyebrow">buchhaltung-ai</p>
          <h1>Beleg-Upload</h1>
        </div>
        <label>
          Mandant
          <input
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            placeholder="mandant"
          />
        </label>
      </section>

      <section
        className={isDragging ? "dropzone active" : "dropzone"}
        onDragEnter={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
      >
        <strong>Belege hier ablegen</strong>
        <span>PDFs, Bilder oder exportierte Rechnungen fuer den ausgewaehlten Mandanten.</span>
        <input
          type="file"
          multiple
          disabled={!canUpload}
          onChange={(event) => handleFiles(event.target.files)}
        />
      </section>

      {notice ? <p className="notice">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <section className="uploads">
        <div className="section-header">
          <h2>Review-Queue</h2>
          <span>{documents.length} Belege</span>
        </div>
        {documents.length === 0 ? (
          <p className="empty">Noch keine Belege fuer diesen Mandanten.</p>
        ) : (
          <div className="queue">
            {documents.map((document) => (
              <article key={document.id} className="document-card">
                <div className="document-head">
                  <div>
                    <strong>{document.original_filename}</strong>
                    <span>{document.normalized_filename || document.tenant_id}</span>
                  </div>
                  <span className="status">{formatStatus(document.status)}</span>
                </div>

                <div className="meta-grid">
                  <span>Hash <code>{document.sha256.slice(0, 16)}</code></span>
                  <span>Groesse {formatSize(document.size_bytes)}</span>
                </div>

                {document.extraction ? (
                  <div className="extraction-grid">
                    <Field label="Lieferant" value={document.extraction.supplier_name} />
                    <Field label="Belegart" value={formatDocumentType(document.extraction.raw_result?.document_type)} />
                    <Field label="Rechnung" value={document.extraction.invoice_number} />
                    <Field label="Kunden-Nr." value={document.extraction.raw_result?.customer_number} />
                    <Field label="Datum" value={formatDate(document.extraction.invoice_date)} />
                    <Field label="Zuordnung" value={formatAssignment(document.extraction.raw_result)} />
                    <Field label="Kostenart" value={formatCostCategory(document.extraction.raw_result?.cost_category)} />
                    <Field label="Bauvorhaben" value={document.extraction.raw_result?.project_code} />
                    <Field label="Brutto" value={formatMoney(document.extraction.gross_amount)} />
                    <Field label="Netto" value={formatMoney(document.extraction.net_amount)} />
                    <Field label="USt" value={formatMoney(document.extraction.tax_amount)} />
                    <Field
                      label="Zahlbar bis"
                      value={formatDate(document.extraction.raw_result?.due_date)}
                    />
                    <Field
                      label="Skonto bis"
                      value={formatDate(document.extraction.raw_result?.discount_due_date)}
                    />
                    <Field
                      label="Skonto-Basis"
                      value={formatMoney(document.extraction.raw_result?.discount_base)}
                    />
                    <Field
                      label="Skonto"
                      value={formatMoney(document.extraction.raw_result?.discount_amount)}
                    />
                    <Field
                      label="Zahlbetrag Skonto"
                      value={formatMoney(discountedAmount(document.extraction.raw_result))}
                    />
                    <Field
                      label="Confidence"
                      value={`${Math.round(document.extraction.confidence * 100)} %`}
                    />
                  </div>
                ) : (
                  <div className="pending-extraction">
                    <span>Extraktion ausstehend</span>
                    <button
                      type="button"
                      onClick={() => startExtraction(document.id)}
                      disabled={extractingIds.includes(document.id)}
                    >
                      {extractingIds.includes(document.id) ? "Laeuft..." : "Extraktion starten"}
                    </button>
                  </div>
                )}

                {document.extraction?.warnings?.length ? (
                  <ul className="warnings">
                    {document.extraction.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function Field({ label, value }) {
  return (
    <span className="field">
      <small>{label}</small>
      <strong>{value || "-"}</strong>
    </span>
  );
}

function formatSize(sizeBytes) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  return `${Math.round(sizeBytes / 1024)} KB`;
}

function formatStatus(status) {
  const labels = {
    review_pending: "Pruefen",
    extracted: "Extrahiert",
  };
  return labels[status] ?? status;
}

function formatDocumentType(value) {
  const labels = {
    credit_note: "Gutschrift",
    incoming_invoice: "Eingangsrechnung",
  };
  return labels[value] ?? value;
}

function formatAssignment(rawResult) {
  if (rawResult?.project_code) return `BV ${rawResult.project_code}`;
  const labels = {
    general_cost: "Allgemeine Kosten",
    project_unresolved: "BV ungeklärt",
    project: "Bauvorhaben",
  };
  return labels[rawResult?.assignment_type] ?? null;
}

function formatCostCategory(value) {
  const labels = {
    fuel_vehicle: "Fahrzeug/Tanken",
    general_overhead: "Sonstige Gemeinkosten",
    material: "Material",
    materials_subcontractor: "Material/Fremdleistung",
    security_subscription: "Überwachung/Abo",
    software_subscription: "Software/Abo",
    subcontractor: "Fremdleistung",
  };
  return labels[value] ?? value;
}

function formatMoney(value) {
  if (!value) return "-";
  return `${Number(value).toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} EUR`;
}

function formatDate(value) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function discountedAmount(rawResult) {
  if (rawResult?.discounted_payable_amount) return rawResult.discounted_payable_amount;
  if (!rawResult?.gross_amount || !rawResult?.discount_amount) return null;
  return Number(rawResult.gross_amount) - Math.abs(Number(rawResult.discount_amount));
}

createRoot(document.getElementById("root")).render(<App />);
