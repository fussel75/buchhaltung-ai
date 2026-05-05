import React, { useCallback, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";

function App() {
  const [tenantId, setTenantId] = useState("demo-mandant");
  const [isDragging, setIsDragging] = useState(false);
  const [uploads, setUploads] = useState([]);

  const canUpload = useMemo(() => tenantId.trim().length > 0, [tenantId]);

  const uploadFile = useCallback(
    async (file) => {
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
      setUploads((current) => [result, ...current]);
    },
    [tenantId],
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
        {uploads.length === 0 ? (
          <p className="empty">Noch keine Belege hochgeladen.</p>
        ) : (
          <div className="table">
            {uploads.map((upload) => (
              <article key={upload.sha256 + upload.storage_path} className="row">
                <div>
                  <strong>{upload.original_filename}</strong>
                  <span>{upload.tenant_id}</span>
                </div>
                <code>{upload.sha256.slice(0, 16)}</code>
                <span>{Math.round(upload.size_bytes / 1024)} KB</span>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
