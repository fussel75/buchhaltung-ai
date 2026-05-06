import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";

function App() {
  const [tenantId, setTenantId] = useState("demo-mandant");
  const [isDragging, setIsDragging] = useState(false);
  const [uploads, setUploads] = useState([]);
  const [notice, setNotice] = useState("");

  const canUpload = useMemo(() => tenantId.trim().length > 0, [tenantId]);

  const loadDocuments = useCallback(async () => {
    if (!canUpload) {
      setUploads([]);
      return;
    }

    const params = new URLSearchParams({ tenant_id: tenantId.trim() });
    const response = await fetch(`${apiBaseUrl}/documents?${params}`);

    if (!response.ok) {
      throw new Error(`Belegliste konnte nicht geladen werden: ${response.status}`);
    }

    const result = await response.json();
    setUploads(result.documents);
  }, [canUpload, tenantId]);

  useEffect(() => {
    loadDocuments().catch((error) => setNotice(error.message));
  }, [loadDocuments]);

  const uploadFile = useCallback(
    async (file) => {
      setNotice("");
      const formData = new FormData();
      formData.append("tenant_id", tenantId.trim());
      formData.append("file", file);

      const response = await fetch(`${apiBaseUrl}/documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Upload fehlgeschlagen: ${response.status}`);
      }

      const result = await response.json();
      if (result.duplicate) {
        setNotice(`Duplikat erkannt: ${result.document.original_filename}`);
      } else {
        setNotice(`Beleg gespeichert: ${result.document.original_filename}`);
      }
      await loadDocuments();
    },
    [loadDocuments, tenantId],
  );

  const handleFiles = useCallback(
    async (files) => {
      if (!canUpload) return;
      for (const file of files) {
        await uploadFile(file);
      }
    },
    [canUpload, uploadFile],
  );

  const extractDocument = useCallback(
    async (documentId) => {
      setNotice("");
      const response = await fetch(`${apiBaseUrl}/documents/${documentId}/extract`, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error(`Extraktion fehlgeschlagen: ${response.status}`);
      }

      setNotice("Mock-Extraktion abgeschlossen.");
      await loadDocuments();
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

      <section className="uploads">
        <h2>Letzte Uploads</h2>
        {notice ? <p className="notice">{notice}</p> : null}
        {uploads.length === 0 ? (
          <p className="empty">Noch keine Belege hochgeladen.</p>
        ) : (
          <div className="table">
            {uploads.map((upload) => (
              <article key={upload.id} className="row">
                <div className="document-main">
                  <div>
                    <strong>{upload.original_filename}</strong>
                    <span>{upload.tenant_id} · {upload.status}</span>
                  </div>
                  {upload.extraction ? (
                    <div className="extraction">
                      <span>Lieferant: {upload.extraction.fields.vendor_name}</span>
                      <span>Confidence: {Math.round(upload.extraction.confidence * 100)}%</span>
                      {upload.extraction.warnings.map((warning) => (
                        <span key={warning} className="warning">{warning}</span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <code>{upload.sha256.slice(0, 16)}</code>
                <span>{Math.round(upload.size_bytes / 1024)} KB</span>
                <button
                  type="button"
                  onClick={() => extractDocument(upload.id).catch((error) => setNotice(error.message))}
                >
                  Extraktion starten
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
