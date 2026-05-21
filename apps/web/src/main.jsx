import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const apiBaseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL ?? "/api");
const AuthContext = createContext(null);

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

function apiUrl(path) {
  return `${apiBaseUrl}${path}`;
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [authState, setAuthState] = useState("loading");

  const loadUser = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" });
      if (response.status === 401) {
        setUser(null);
        setAuthState("anonymous");
        return null;
      }
      if (!response.ok) {
        throw new Error(`Login-Status konnte nicht geladen werden: ${response.status}`);
      }
      const result = await response.json();
      setUser(result.user);
      setAuthState("authenticated");
      return result.user;
    } catch {
      setUser(null);
      setAuthState("anonymous");
      return null;
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = useCallback(async (email, password) => {
    const response = await fetch(`${apiBaseUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || "Login fehlgeschlagen");
    }
    const result = await response.json();
    setUser(result.user);
    setAuthState("authenticated");
    window.history.replaceState(null, "", "/");
  }, []);

  const logout = useCallback(async () => {
    await fetch(`${apiBaseUrl}/auth/logout`, { method: "POST", credentials: "include" }).catch(() => null);
    setUser(null);
    setAuthState("anonymous");
    window.history.pushState(null, "", "/login");
  }, []);

  const apiFetch = useCallback(
    async (path, options = {}) => {
      const response = await fetch(`${apiBaseUrl}${path}`, {
        ...options,
        credentials: "include",
      });
      if (response.status === 401) {
        setUser(null);
        setAuthState("anonymous");
        window.history.pushState(null, "", "/login");
      }
      return response;
    },
    [],
  );

  const value = useMemo(
    () => ({ apiFetch, authState, loadUser, login, logout, user }),
    [apiFetch, authState, loadUser, login, logout, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function useAuth() {
  return useContext(AuthContext);
}

function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}

function AuthGate() {
  const { authState } = useAuth();
  const isLoginPath = window.location.pathname === "/login";

  if (authState === "loading") {
    return <main className="app"><p className="empty">Login wird geprueft ...</p></main>;
  }

  if (authState === "authenticated" && isLoginPath) {
    window.history.replaceState(null, "", "/");
    return <UploadApp />;
  }

  if (authState !== "authenticated") {
    return <LoginPage />;
  }

  return <UploadApp />;
}

function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submitLogin(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await login(email, password);
    } catch (loginError) {
      setError(loginError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="app login-page">
      <form className="login-panel" onSubmit={submitLogin}>
        <p className="eyebrow">buchhaltung-ai</p>
        <h1>Login</h1>
        <label>
          E-Mail
          <input
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
          />
        </label>
        <label>
          Passwort
          <input
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
          />
        </label>
        {error ? <p className="error">{error}</p> : null}
        <button disabled={isSubmitting} type="submit">
          {isSubmitting ? "Prüfe ..." : "Einloggen"}
        </button>
      </form>
    </main>
  );
}

function UploadApp() {
  const { apiFetch, logout, user } = useAuth();
  const [tenantId, setTenantId] = useState("demo-mandant");
  const [isDragging, setIsDragging] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [extractingIds, setExtractingIds] = useState([]);
  const [activeView, setActiveView] = useState("review");
  const [deletingIds, setDeletingIds] = useState([]);
  const [approvingIds, setApprovingIds] = useState([]);
  const [savingSuggestionIds, setSavingSuggestionIds] = useState([]);
  const [savingPaymentIds, setSavingPaymentIds] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [exporting, setExporting] = useState("");
  const [exportMonth, setExportMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [tenantProfile, setTenantProfile] = useState(defaultTenantProfile("construction"));

  const canUpload = useMemo(() => tenantId.trim().length > 0, [tenantId]);
  const activeTenantId = tenantId.trim();
  const queueStats = useMemo(
    () => ({
      pending: documents.filter((document) => document.status === "review_pending").length,
      extracted: documents.filter((document) => document.status === "extracted").length,
      approved: documents.filter((document) => document.status === "review_approved").length,
    }),
    [documents],
  );

  const loadDocuments = useCallback(async () => {
    if (!activeTenantId) {
      setDocuments([]);
      return;
    }

    const response = await apiFetch(`/documents?tenant_id=${encodeURIComponent(activeTenantId)}`);

    if (!response.ok) {
      throw new Error(`Review-Queue konnte nicht geladen werden: ${response.status}`);
    }

    const result = await response.json();
    setDocuments(result.documents ?? []);
  }, [activeTenantId, apiFetch]);

  useEffect(() => {
    loadDocuments().catch((loadError) => setError(loadError.message));
  }, [loadDocuments]);

  useEffect(() => {
    setSelectedDocumentIds((current) =>
      current.filter((id) => documents.some((document) => document.id === id)),
    );
  }, [documents]);

  const loadTenantProfile = useCallback(async () => {
    if (!activeTenantId) return;
    const response = await apiFetch(`/masterdata/tenant-profile?tenant_id=${encodeURIComponent(activeTenantId)}`);
    if (!response.ok) return;
    const result = await response.json();
    setTenantProfile(result.tenant_profile ?? defaultTenantProfile("general"));
  }, [activeTenantId, apiFetch]);

  useEffect(() => {
    loadTenantProfile();
  }, [loadTenantProfile]);

  const uploadFile = useCallback(
    async (file) => {
      setError("");
      setNotice("");

      const formData = new FormData();
      formData.append("tenant_id", activeTenantId);
      formData.append("file", file);

      const response = await apiFetch("/documents/upload", {
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
    [activeTenantId, apiFetch, loadDocuments],
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
        const response = await apiFetch(`/documents/${documentId}/extract`, {
          method: "POST",
        });

        if (!response.ok) {
          throw new Error(`Extraktion fehlgeschlagen: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Extraktion erstellt: ${result.document.original_filename}`);
      } catch (extractError) {
        setError(extractError.message);
      } finally {
        setExtractingIds((current) => current.filter((id) => id !== documentId));
      }
    },
    [apiFetch, loadDocuments],
  );

  const deleteDocument = useCallback(
    async (document) => {
      const confirmed = window.confirm(
        `Beleg "${document.original_filename}" wirklich aus der Review-Queue löschen?`,
      );
      if (!confirmed) return;

      setError("");
      setNotice("");
      setDeletingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}`, {
          method: "DELETE",
        });

        if (!response.ok) {
          throw new Error(`Löschen fehlgeschlagen: ${response.status}`);
        }

        await loadDocuments();
        setNotice(`Beleg gelöscht: ${document.original_filename}`);
      } catch (deleteError) {
        setError(deleteError.message);
      } finally {
        setDeletingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const prepareReview = useCallback(
    async (document) => {
      setError("");
      setNotice("");
      setApprovingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}/review`, {
          method: "POST",
        });

        if (!response.ok) {
          throw new Error(`Buchungsvorschlag fehlgeschlagen: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Buchungsvorschlag erstellt: ${result.document.original_filename}`);
      } catch (prepareError) {
        setError(prepareError.message);
      } finally {
        setApprovingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const approveDocument = useCallback(
    async (document) => {
      const confirmed = window.confirm(
        `Beleg "${document.original_filename}" final freigeben? Danach sind die Vorschlagszeilen gesperrt.`,
      );
      if (!confirmed) return;

      setError("");
      setNotice("");
      setApprovingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}/approve`, {
          method: "POST",
        });

        if (!response.ok) {
          throw new Error(`Finale Freigabe fehlgeschlagen: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Beleg final freigegeben: ${result.document.original_filename}`);
      } catch (approveError) {
        setError(approveError.message);
      } finally {
        setApprovingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const reopenReview = useCallback(
    async (document) => {
      const confirmed = window.confirm(
        `Freigabe für "${document.original_filename}" wieder zur Bearbeitung öffnen?`,
      );
      if (!confirmed) return;

      setError("");
      setNotice("");
      setApprovingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}/reopen-review`, {
          method: "POST",
        });

        if (!response.ok) {
          throw new Error(`Bearbeitung konnte nicht geöffnet werden: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Bearbeitung wieder geöffnet: ${result.document.original_filename}`);
      } catch (reopenError) {
        setError(reopenError.message);
      } finally {
        setApprovingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const saveBookingSuggestion = useCallback(
    async (document, suggestion, values) => {
      setError("");
      setNotice("");
      setSavingSuggestionIds((current) => [...current, suggestion.id]);
      try {
        const response = await apiFetch(`/documents/${document.id}/booking-suggestions/${suggestion.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(normalizeBookingSuggestion(values)),
        });

        if (!response.ok) {
          throw new Error(`Buchungszeile konnte nicht gespeichert werden: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Buchungszeile gespeichert: ${result.document.original_filename}`);
      } catch (saveError) {
        setError(saveError.message);
      } finally {
        setSavingSuggestionIds((current) => current.filter((id) => id !== suggestion.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const selectPaymentDecision = useCallback(
    async (document, term) => {
      setError("");
      setNotice("");
      setSavingPaymentIds((current) => [...current, document.id]);
      try {
        const response = await apiFetch(`/documents/${document.id}/payment-decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ payment_type: term.type }),
        });

        if (!response.ok) {
          throw new Error(`Zahlungsentscheidung konnte nicht gespeichert werden: ${response.status}`);
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Zahlungsentscheidung gespeichert: ${result.document.original_filename}`);
      } catch (paymentError) {
        setError(paymentError.message);
      } finally {
        setSavingPaymentIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const toggleDocumentSelection = useCallback((documentId) => {
    setSelectedDocumentIds((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    );
  }, []);

  const openDocument = useCallback((document) => {
    window.open(apiUrl(`/documents/${document.id}/file?disposition=inline`), "_blank", "noopener");
  }, []);

  const downloadDocument = useCallback(
    async (document) => {
      setError("");
      setNotice("");
      setExporting(document.id);
      try {
        const response = await apiFetch(`/documents/${document.id}/file?disposition=attachment`);
        if (!response.ok) {
          throw new Error(`Download fehlgeschlagen: ${response.status}`);
        }
        await downloadResponse(response, safeVisibleFilename(document.normalized_filename || document.original_filename));
      } catch (downloadError) {
        setError(downloadError.message);
      } finally {
        setExporting("");
      }
    },
    [apiFetch],
  );

  const exportSelectedDocuments = useCallback(async () => {
    if (!selectedDocumentIds.length) {
      setError("Bitte zuerst Belege auswählen.");
      return;
    }
    setError("");
    setNotice("");
    setExporting("selected");
    try {
      const response = await apiFetch("/documents/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: activeTenantId, document_ids: selectedDocumentIds }),
      });
      if (!response.ok) {
        throw new Error(`ZIP-Export fehlgeschlagen: ${response.status}`);
      }
      await downloadResponse(response, `belege-${activeTenantId}-auswahl.zip`);
      setNotice(`${selectedDocumentIds.length} Belege als ZIP erstellt.`);
    } catch (exportError) {
      setError(exportError.message);
    } finally {
      setExporting("");
    }
  }, [activeTenantId, apiFetch, selectedDocumentIds]);

  const exportMonthDocuments = useCallback(async () => {
    const [year, month] = exportMonth.split("-").map((value) => Number(value));
    if (!year || !month) {
      setError("Bitte einen Monat auswählen.");
      return;
    }
    setError("");
    setNotice("");
    setExporting("month");
    try {
      const response = await apiFetch(
        `/documents/export/month?tenant_id=${encodeURIComponent(activeTenantId)}&year=${year}&month=${month}`,
      );
      if (!response.ok) {
        throw new Error(response.status === 404 ? "Keine Belege für diesen Monat gefunden." : `Monats-Export fehlgeschlagen: ${response.status}`);
      }
      await downloadResponse(response, `belege-${activeTenantId}-${exportMonth}.zip`);
      setNotice(`Monats-ZIP erstellt: ${exportMonth}`);
    } catch (exportError) {
      setError(exportError.message);
    } finally {
      setExporting("");
    }
  }, [activeTenantId, apiFetch, exportMonth]);

  const exportBookingRows = useCallback(async () => {
    const [year, month] = exportMonth.split("-").map((value) => Number(value));
    if (!year || !month) {
      setError("Bitte einen Monat auswählen.");
      return;
    }
    setError("");
    setNotice("");
    setExporting("bookings");
    try {
      const response = await apiFetch(
        `/documents/export/bookings?tenant_id=${encodeURIComponent(activeTenantId)}&year=${year}&month=${month}`,
      );
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "Keine freigegebenen Buchungszeilen für diesen Monat gefunden."
            : `Buchungsexport fehlgeschlagen: ${response.status}`,
        );
      }
      await downloadResponse(response, `buchungsentwurf-${activeTenantId}-${exportMonth}.csv`);
      setNotice(`Buchungsentwurf erstellt: ${exportMonth}`);
    } catch (exportError) {
      setError(exportError.message);
    } finally {
      setExporting("");
    }
  }, [activeTenantId, apiFetch, exportMonth]);

  return (
    <main className="app app-shell">
      <header className="app-header">
        <div className="brand-block">
          <p className="eyebrow">buchhaltung-ai</p>
          <h1>Belege</h1>
        </div>
        <div className="header-controls">
          <label className="tenant-control">
            <span>Mandant</span>
            <input
              value={tenantId}
              onChange={(event) => setTenantId(event.target.value)}
              placeholder="mandant"
            />
          </label>
          <div className="session-tools">
            <span>{user?.display_name || user?.email}</span>
            <button className="secondary-button" type="button" onClick={logout}>Logout</button>
          </div>
        </div>
      </header>

      <nav className="view-tabs" aria-label="Arbeitsbereiche">
        <button type="button" className={activeView === "review" ? "active" : ""} onClick={() => setActiveView("review")}>
          Review
        </button>
        {user?.role === "admin" ? (
          <>
            <button type="button" className={activeView === "masterdata" ? "active" : ""} onClick={() => setActiveView("masterdata")}>
              Stammdaten
            </button>
            <button type="button" className={activeView === "users" ? "active" : ""} onClick={() => setActiveView("users")}>
              Benutzer
            </button>
          </>
        ) : null}
      </nav>

      <section className="metric-strip">
        <Metric label="Offen" value={queueStats.pending} />
        <Metric label="Extrahiert" value={queueStats.extracted} />
        <Metric label="Freigegeben" value={queueStats.approved} />
        <Metric label="Zuordnung" value={tenantProfile.assignment_label_singular} />
      </section>

      {notice ? <p className="notice">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {activeView === "review" ? (
        <section className="review-board">
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
            <span>PDFs, Bilder oder exportierte Rechnungen für den ausgewählten Mandanten.</span>
            <input
              type="file"
              multiple
              disabled={!canUpload}
              onChange={(event) => handleFiles(event.target.files)}
            />
          </section>

          <section className="uploads">
        <div className="section-header">
          <div>
            <h2>Review-Queue</h2>
            <span>{documents.length} Belege</span>
          </div>
          <div className="queue-tools">
            <button
              className="secondary-button"
              type="button"
              onClick={exportSelectedDocuments}
              disabled={!selectedDocumentIds.length || exporting === "selected"}
            >
              {exporting === "selected" ? "Erstellt..." : `Auswahl ZIP (${selectedDocumentIds.length})`}
            </button>
            <label className="month-export">
              <span>Monat</span>
              <input type="month" value={exportMonth} onChange={(event) => setExportMonth(event.target.value)} />
            </label>
            <button
              className="secondary-button"
              type="button"
              onClick={exportMonthDocuments}
              disabled={exporting === "month"}
            >
              {exporting === "month" ? "Erstellt..." : "Monat ZIP"}
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={exportBookingRows}
              disabled={exporting === "bookings"}
            >
              {exporting === "bookings" ? "Erstellt..." : "Buchungsentwurf CSV"}
            </button>
          </div>
        </div>
        {documents.length === 0 ? (
          <p className="empty">Noch keine Belege für diesen Mandanten.</p>
        ) : (
          <div className="queue">
            {documents.map((document) => (
              <article key={document.id} className="document-card">
                <div className="document-head">
                  <div className="document-title">
                    <label className="document-select">
                      <input
                        type="checkbox"
                        checked={selectedDocumentIds.includes(document.id)}
                        onChange={() => toggleDocumentSelection(document.id)}
                      />
                      <span>Auswählen</span>
                    </label>
                    <div className="document-file-names">
                      <strong>{document.original_filename}</strong>
                      <span>{safeVisibleFilename(document.normalized_filename || document.tenant_id)}</span>
                    </div>
                  </div>
                  <div className="document-actions">
                    <span className="status">{formatStatus(document.status)}</span>
                    <button className="secondary-button" type="button" onClick={() => openDocument(document)}>
                      Ansehen
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => downloadDocument(document)}
                      disabled={exporting === document.id}
                    >
                      {exporting === document.id ? "Lädt..." : "Download"}
                    </button>
                    {document.extraction && !document.booking_suggestions?.length ? (
                      <button
                        type="button"
                        onClick={() => prepareReview(document)}
                        disabled={approvingIds.includes(document.id)}
                      >
                        {approvingIds.includes(document.id) ? "Erstellt..." : "Vorschlag"}
                      </button>
                    ) : null}
                    {document.booking_suggestions?.length && document.status !== "review_approved" ? (
                      <button
                        type="button"
                        onClick={() => approveDocument(document)}
                        disabled={approvingIds.includes(document.id)}
                      >
                        {approvingIds.includes(document.id) ? "Gibt frei..." : "Final freigeben"}
                      </button>
                    ) : null}
                    {document.booking_suggestions?.length && document.status === "review_approved" ? (
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => reopenReview(document)}
                        disabled={approvingIds.includes(document.id)}
                      >
                        {approvingIds.includes(document.id) ? "Öffnet..." : "Bearbeitung öffnen"}
                      </button>
                    ) : null}
                    <button
                      className="secondary-button danger-button"
                      type="button"
                      onClick={() => deleteDocument(document)}
                      disabled={deletingIds.includes(document.id)}
                    >
                      {deletingIds.includes(document.id) ? "Löscht..." : "Löschen"}
                    </button>
                  </div>
                </div>

                <div className="meta-grid">
                  <span>Hash <code>{document.sha256.slice(0, 16)}</code></span>
                  <span>Größe {formatSize(document.size_bytes)}</span>
                </div>

                {document.extraction ? (
                  <div className="extraction-panel">
                    <div className="extraction-grid">
                      <Field label="Lieferant" value={document.extraction.supplier_name} />
                      <Field label="Belegart" value={formatDocumentType(document.extraction.raw_result?.document_type)} />
                      <Field label="Rechnung" value={document.extraction.invoice_number} />
                      <Field label="Kunden-Nr." value={document.extraction.raw_result?.customer_number} />
                      <Field label="Datum" value={formatDate(document.extraction.invoice_date)} />
                      <Field label="Zuordnung" value={formatAssignment(document.extraction.raw_result, tenantProfile)} />
                      <Field label="Kostenart" value={formatCostCategory(document.extraction.raw_result?.cost_category)} />
                      <Field label={tenantProfile.assignment_code_label} value={<ProjectSummary rawResult={document.extraction.raw_result} tenantProfile={tenantProfile} />} />
                      <Field label="Zuordnungsart" value={formatAssignmentKind(document.extraction.raw_result?.assignment_kind, tenantProfile)} />
                      <Field label="Brutto" value={formatMoney(document.extraction.gross_amount)} />
                      <Field label="Netto" value={formatMoney(document.extraction.net_amount)} />
                      <Field label="USt" value={formatMoney(document.extraction.tax_amount)} />
                      <Field label="Zahlbar bis" value={formatDate(document.extraction.raw_result?.due_date)} />
                      <Field label="Skonto bis" value={formatDate(document.extraction.raw_result?.discount_due_date)} />
                      <Field label="Skonto-Basis" value={formatMoney(document.extraction.raw_result?.discount_base)} />
                      <Field label="Skonto" value={formatMoney(document.extraction.raw_result?.discount_amount)} />
                      <Field label="Zahlbetrag Skonto" value={formatMoney(discountedAmount(document.extraction.raw_result))} />
                      <Field label="Confidence" value={`${Math.round(document.extraction.confidence * 100)} %`} />
                    </div>
                    <AllocationLines lines={document.extraction.raw_result?.allocation_lines} tenantProfile={tenantProfile} />
                    <PaymentTerms
                      document={document}
                      rawResult={document.extraction.raw_result}
                      onSelect={selectPaymentDecision}
                      isSaving={savingPaymentIds.includes(document.id)}
                    />
                    <BookingSuggestions
                      document={document}
                      suggestions={document.booking_suggestions}
                      tenantProfile={tenantProfile}
                      onSave={saveBookingSuggestion}
                      savingIds={savingSuggestionIds}
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
                      {extractingIds.includes(document.id) ? "Läuft..." : "Extraktion starten"}
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
        </section>
      ) : null}

      {activeView === "masterdata" && user?.role === "admin" ? (
        <MasterdataAdmin apiFetch={apiFetch} tenantId={activeTenantId} tenantProfile={tenantProfile} onProfileSaved={setTenantProfile} />
      ) : null}

      {activeView === "users" && user?.role === "admin" ? (
        <UserAdmin apiFetch={apiFetch} currentUser={user} activeTenantId={activeTenantId} />
      ) : null}
    </main>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function UserAdmin({ apiFetch, currentUser, activeTenantId }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({
    email: "",
    password: "",
    display_name: "",
    role: "user",
    allowed_tenant_ids: activeTenantId,
  });
  const [message, setMessage] = useState("");

  const loadUsers = useCallback(async () => {
    const response = await apiFetch("/users");
    if (!response.ok) throw new Error(`Benutzer konnten nicht geladen werden: ${response.status}`);
    const result = await response.json();
    setUsers((result.users ?? []).map((account) => ({
      ...account,
      allowed_tenant_ids_text: (account.allowed_tenant_ids ?? []).join(", "),
    })));
  }, [apiFetch]);

  useEffect(() => {
    loadUsers().catch((error) => setMessage(error.message));
  }, [loadUsers]);

  useEffect(() => {
    setForm((current) => (current.allowed_tenant_ids ? current : { ...current, allowed_tenant_ids: activeTenantId }));
  }, [activeTenantId]);

  async function createUser(event) {
    event.preventDefault();
    setMessage("");
    const response = await apiFetch("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...form,
        allowed_tenant_ids: splitCommaList(form.allowed_tenant_ids),
      }),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      setMessage(result.detail || `Benutzer konnte nicht angelegt werden: ${response.status}`);
      return;
    }
    setForm({ email: "", password: "", display_name: "", role: "user", allowed_tenant_ids: activeTenantId });
    await loadUsers();
    setMessage("Benutzer angelegt.");
  }

  async function updateUser(userId, payload) {
    const response = await apiFetch(`/users/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      setMessage(result.detail || `Benutzer konnte nicht aktualisiert werden: ${response.status}`);
      return;
    }
    await loadUsers();
  }

  function updateUserDraft(userId, field, value) {
    setUsers((accounts) => accounts.map((account) => (account.id === userId ? { ...account, [field]: value } : account)));
  }

  return (
    <section className="admin-panel">
      <div className="section-header">
        <h2>Benutzer</h2>
        <span>{users.length} Konten</span>
      </div>
      <form className="compact-form" onSubmit={createUser}>
        <input placeholder="E-Mail" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required />
        <input placeholder="Name" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required />
        <input placeholder="Initiales Passwort" type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required />
        <select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
        <input
          placeholder="Mandanten, komma-getrennt"
          value={form.allowed_tenant_ids}
          onChange={(event) => setForm({ ...form, allowed_tenant_ids: event.target.value })}
        />
        <button type="submit">Anlegen</button>
      </form>
      {message ? <p className="notice">{message}</p> : null}
      <div className="table-list">
        {users.map((account) => (
          <div className="table-row" key={account.id}>
            <strong>{account.display_name}</strong>
            <span>{account.email}</span>
            <select value={account.role} onChange={(event) => updateUser(account.id, { role: event.target.value })}>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <input
              aria-label={`Mandanten fuer ${account.email}`}
              value={account.allowed_tenant_ids_text ?? (account.allowed_tenant_ids ?? []).join(", ")}
              disabled={account.role === "admin"}
              onChange={(event) => updateUserDraft(account.id, "allowed_tenant_ids_text", event.target.value)}
              onBlur={(event) => updateUser(account.id, { allowed_tenant_ids: splitCommaList(event.target.value) })}
            />
            <label className="inline-check">
              <input
                type="checkbox"
                checked={account.is_active}
                disabled={account.id === currentUser.id}
                onChange={(event) => updateUser(account.id, { is_active: event.target.checked })}
              />
              aktiv
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}

function MasterdataAdmin({ apiFetch, tenantId, tenantProfile, onProfileSaved }) {
  const [assignmentUnits, setAssignmentUnits] = useState([]);
  const [supplierRules, setSupplierRules] = useState([]);
  const [accountingRules, setAccountingRules] = useState([]);
  const [profileForm, setProfileForm] = useState(tenantProfile);
  const [assignmentForm, setAssignmentForm] = useState({
    code: "",
    label: "",
    kind: "cost_object",
    project_number: "",
    revenue_relevant: false,
    aliases: "",
  });
  const [supplierForm, setSupplierForm] = useState({
    match_text: "",
    supplier_name: "",
    customer_number: "",
    default_cost_category: "material",
    default_assignment_code: "",
  });
  const [accountingForm, setAccountingForm] = useState({
    name: "",
    supplier_match_text: "",
    cost_category: "material",
    debit_account: "",
    credit_account: "",
    tax_key: "",
    tax_rate: "19.00",
    discount_account: "",
  });
  const [message, setMessage] = useState("");

  useEffect(() => {
    setProfileForm(tenantProfile);
    setAssignmentForm((current) => ({
      ...current,
      kind: tenantProfile.default_assignment_kind || current.kind,
    }));
  }, [tenantProfile]);

  const loadMasterdata = useCallback(async () => {
    const [assignmentsResponse, suppliersResponse, accountingResponse] = await Promise.all([
      apiFetch(`/masterdata/assignment-units?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch(`/masterdata/supplier-rules?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch(`/masterdata/accounting-rules?tenant_id=${encodeURIComponent(tenantId)}`),
    ]);
    if (!assignmentsResponse.ok || !suppliersResponse.ok || !accountingResponse.ok) {
      throw new Error("Stammdaten konnten nicht geladen werden.");
    }
    const assignmentsResult = await assignmentsResponse.json();
    const suppliersResult = await suppliersResponse.json();
    const accountingResult = await accountingResponse.json();
    setAssignmentUnits(assignmentsResult.assignment_units ?? []);
    setSupplierRules(suppliersResult.supplier_rules ?? []);
    setAccountingRules(accountingResult.accounting_rules ?? []);
  }, [apiFetch, tenantId]);

  useEffect(() => {
    loadMasterdata().catch((error) => setMessage(error.message));
  }, [loadMasterdata]);

  async function createAssignment(event) {
    event.preventDefault();
    const response = await apiFetch(`/masterdata/assignment-units?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...assignmentForm,
        aliases: splitAliases(assignmentForm.aliases),
      }),
    });
    if (!response.ok) {
      setMessage(`Zuordnung konnte nicht angelegt werden: ${response.status}`);
      return;
    }
    setAssignmentForm({
      code: "",
      label: "",
      kind: tenantProfile.default_assignment_kind || "cost_object",
      project_number: "",
      revenue_relevant: false,
      aliases: "",
    });
    await loadMasterdata();
    setMessage("Zuordnung angelegt.");
  }

  async function updateAssignment(assignment, payload) {
    const response = await apiFetch(`/masterdata/assignment-units/${assignment.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: assignment.label,
        kind: assignment.kind,
        project_number: assignment.project_number,
        revenue_relevant: assignment.revenue_relevant,
        aliases: assignment.aliases ?? [],
        is_active: assignment.is_active,
        ...payload,
      }),
    });
    if (!response.ok) {
      setMessage(`Zuordnung konnte nicht aktualisiert werden: ${response.status}`);
      return;
    }
    await loadMasterdata();
  }

  async function saveTenantProfile(event) {
    event.preventDefault();
    const response = await apiFetch(`/masterdata/tenant-profile?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profileForm),
    });
    if (!response.ok) {
      setMessage(`Mandantenprofil konnte nicht gespeichert werden: ${response.status}`);
      return;
    }
    const result = await response.json();
    onProfileSaved(result.tenant_profile);
    setMessage("Mandantenprofil gespeichert.");
  }

  async function createSupplierRule(event) {
    event.preventDefault();
    const response = await apiFetch(`/masterdata/supplier-rules?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(supplierForm)),
    });
    if (!response.ok) {
      setMessage(`Lieferantenregel konnte nicht angelegt werden: ${response.status}`);
      return;
    }
    setSupplierForm({ match_text: "", supplier_name: "", customer_number: "", default_cost_category: "material", default_assignment_code: "" });
    await loadMasterdata();
    setMessage("Lieferantenregel angelegt.");
  }

  async function updateSupplierRule(rule, payload) {
    const response = await apiFetch(`/masterdata/supplier-rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        match_text: rule.match_text,
        supplier_name: rule.supplier_name,
        customer_number: rule.customer_number,
        default_cost_category: rule.default_cost_category,
        default_assignment_code: rule.default_assignment_code,
        is_active: rule.is_active,
        ...payload,
      }),
    });
    if (!response.ok) {
      setMessage(`Lieferantenregel konnte nicht aktualisiert werden: ${response.status}`);
      return;
    }
    await loadMasterdata();
  }

  async function createAccountingRule(event) {
    event.preventDefault();
    const response = await apiFetch(`/masterdata/accounting-rules?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(accountingForm)),
    });
    if (!response.ok) {
      setMessage(`Kontierungsregel konnte nicht angelegt werden: ${response.status}`);
      return;
    }
    setAccountingForm({
      name: "",
      supplier_match_text: "",
      cost_category: "material",
      debit_account: "",
      credit_account: "",
      tax_key: "",
      tax_rate: "19.00",
      discount_account: "",
    });
    await loadMasterdata();
    setMessage("Kontierungsregel angelegt.");
  }

  async function updateAccountingRule(rule, payload) {
    const response = await apiFetch(`/masterdata/accounting-rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: rule.name,
        supplier_match_text: rule.supplier_match_text,
        cost_category: rule.cost_category,
        debit_account: rule.debit_account,
        credit_account: rule.credit_account,
        tax_key: rule.tax_key,
        tax_rate: rule.tax_rate,
        discount_account: rule.discount_account,
        is_active: rule.is_active,
        ...payload,
      }),
    });
    if (!response.ok) {
      setMessage(`Kontierungsregel konnte nicht aktualisiert werden: ${response.status}`);
      return;
    }
    await loadMasterdata();
  }

  return (
    <section className="admin-panel">
      <div className="section-header">
        <div>
          <p className="eyebrow">Mandant</p>
          <h2>Stammdaten</h2>
        </div>
        <span className="tenant-chip">{tenantId}</span>
      </div>
      {message ? <p className="notice">{message}</p> : null}

      <div className="admin-grid">
        <section className="admin-card admin-card-wide">
          <div className="card-header">
            <div>
              <p className="eyebrow">Branche und Begrifflichkeit</p>
              <h3>Mandantenprofil</h3>
            </div>
            <StatusPill value={industryLabel(profileForm.industry)} />
          </div>
          <form className="form-grid profile-form" onSubmit={saveTenantProfile}>
            <FormField label="Mandantenname">
              <input placeholder="Mandantenname" value={profileForm.display_name || ""} onChange={(event) => setProfileForm({ ...profileForm, display_name: event.target.value })} required />
            </FormField>
            <FormField label="Branche">
              <select
                value={profileForm.industry || "general"}
                onChange={(event) => {
                  const nextTemplate = defaultTenantProfile(event.target.value);
                  setProfileForm({ ...profileForm, ...nextTemplate, display_name: profileForm.display_name || tenantId });
                }}
              >
                <option value="construction">Baubranche</option>
                <option value="fitness_studio">Sportstudio</option>
                <option value="container_transport">Container/Transport</option>
                <option value="general">Allgemein</option>
              </select>
            </FormField>
            <FormField label="Begriff einzeln">
              <input placeholder="Bauvorhaben" value={profileForm.assignment_label_singular || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_label_singular: event.target.value })} required />
            </FormField>
            <FormField label="Begriff mehrfach">
              <input placeholder="Bauvorhaben" value={profileForm.assignment_label_plural || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_label_plural: event.target.value })} required />
            </FormField>
            <FormField label="Feldname in Belegen">
              <input placeholder="Zuordnung" value={profileForm.assignment_code_label || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_code_label: event.target.value })} required />
            </FormField>
            <FormField label="Kürzel vor Code">
              <input placeholder="z.B. BV" value={profileForm.assignment_code_prefix || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_code_prefix: event.target.value })} />
            </FormField>
            <label className="toggle-field">
              <input type="checkbox" checked={profileForm.allow_multiple_assignments ?? true} onChange={(event) => setProfileForm({ ...profileForm, allow_multiple_assignments: event.target.checked })} />
              <span>Mehrere Zuordnungen pro Beleg erlauben</span>
            </label>
            <button type="submit">Profil speichern</button>
          </form>
        </section>

        <section className="admin-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Kosten- und Umsatzzuordnung</p>
              <h3>{tenantProfile.assignment_label_plural}</h3>
            </div>
            <StatusPill value={`${assignmentUnits.length} Einträge`} />
          </div>
          <form className="form-grid assignment-form" onSubmit={createAssignment}>
            <FormField label="Code">
              <input placeholder="Wewe20" value={assignmentForm.code} onChange={(event) => setAssignmentForm({ ...assignmentForm, code: event.target.value })} required />
            </FormField>
            <FormField label="Name">
              <input placeholder="Weseler Weg 20" value={assignmentForm.label} onChange={(event) => setAssignmentForm({ ...assignmentForm, label: event.target.value })} required />
            </FormField>
            <FormField label="Art">
              <select value={assignmentForm.kind} onChange={(event) => setAssignmentForm({ ...assignmentForm, kind: event.target.value })}>
                <option value="construction_project">Bauvorhaben</option>
                <option value="location">Standort</option>
                <option value="construction_or_dropoff_site">Bauvorhaben / Stellplatz</option>
                <option value="cost_object">Kostenobjekt</option>
                <option value="vehicle">Fahrzeug</option>
                <option value="subscription">Abo/Vertrag</option>
                <option value="department">Bereich</option>
              </select>
            </FormField>
            {usesProjectNumber(assignmentForm.kind) ? (
              <FormField label="Projektnummer">
                <input placeholder="25-00008" value={assignmentForm.project_number || ""} onChange={(event) => setAssignmentForm({ ...assignmentForm, project_number: event.target.value })} />
              </FormField>
            ) : null}
            <FormField label="Aliase">
              <input placeholder="Aliase, komma-getrennt" value={assignmentForm.aliases} onChange={(event) => setAssignmentForm({ ...assignmentForm, aliases: event.target.value })} />
            </FormField>
            <label className="toggle-field">
              <input type="checkbox" checked={assignmentForm.revenue_relevant} onChange={(event) => setAssignmentForm({ ...assignmentForm, revenue_relevant: event.target.checked })} />
              <span>umsatzrelevant</span>
            </label>
            <button type="submit">{tenantProfile.assignment_label_singular} anlegen</button>
          </form>
          <div className="data-table assignment-table">
            <div className="data-row data-head">
              <span>Code</span>
              <span>Projektnummer</span>
              <span>Name</span>
              <span>Art</span>
              <span>Status</span>
              <span>Aktiv</span>
            </div>
            {assignmentUnits.map((assignment) => (
              <div className="data-row" key={assignment.id}>
                <strong>{formatAssignmentCode(assignment.code, assignment.kind, tenantProfile)}</strong>
                <span>{usesProjectNumber(assignment.kind) ? assignment.project_number || "-" : "-"}</span>
                <span>{assignment.label}</span>
                <span>{formatAssignmentKind(assignment.kind, tenantProfile)}</span>
                <StatusPill value={assignment.revenue_relevant ? "umsatzrelevant" : "intern"} tone={assignment.revenue_relevant ? "green" : "gray"} />
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={assignment.is_active}
                    onChange={(event) => updateAssignment(assignment, { is_active: event.target.checked })}
                  />
                  <span>{assignment.is_active ? "aktiv" : "inaktiv"}</span>
                </label>
              </div>
            ))}
          </div>
        </section>

        <section className="admin-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Erkennung und Defaults</p>
              <h3>Lieferantenregeln</h3>
            </div>
            <StatusPill value={`${supplierRules.length} Regeln`} />
          </div>
          <form className="form-grid supplier-form" onSubmit={createSupplierRule}>
            <FormField label="Erkennungstext">
              <input placeholder="Holz Junge" value={supplierForm.match_text} onChange={(event) => setSupplierForm({ ...supplierForm, match_text: event.target.value })} required />
            </FormField>
            <FormField label="Lieferant">
              <input placeholder="Holz Junge GmbH" value={supplierForm.supplier_name} onChange={(event) => setSupplierForm({ ...supplierForm, supplier_name: event.target.value })} required />
            </FormField>
            <FormField label="Unsere Kunden-Nr.">
              <input placeholder="109324" value={supplierForm.customer_number} onChange={(event) => setSupplierForm({ ...supplierForm, customer_number: event.target.value })} />
            </FormField>
            <FormField label="Kostenart">
              <select value={supplierForm.default_cost_category} onChange={(event) => setSupplierForm({ ...supplierForm, default_cost_category: event.target.value })}>
                <option value="material">Material</option>
                <option value="subcontractor">Fremdleistung</option>
                <option value="fuel_vehicle">Fahrzeug/Tanken</option>
                <option value="software_subscription">Software/Abo</option>
                <option value="security_subscription">Überwachung/Abo</option>
                <option value="general_overhead">Sonstige Gemeinkosten</option>
              </select>
            </FormField>
            <FormField label={tenantProfile.assignment_code_label}>
              <input placeholder="optional" value={supplierForm.default_assignment_code} onChange={(event) => setSupplierForm({ ...supplierForm, default_assignment_code: event.target.value })} />
            </FormField>
            <button type="submit">Regel anlegen</button>
          </form>
          <div className="data-table supplier-table">
            <div className="data-row data-head">
              <span>Lieferant</span>
              <span>Erkennung</span>
              <span>Kunden-Nr.</span>
              <span>Kostenart</span>
              <span>{tenantProfile.assignment_code_label}</span>
              <span>Aktiv</span>
            </div>
            {supplierRules.map((rule) => (
              <div className="data-row" key={rule.id}>
                <strong>{rule.supplier_name}</strong>
                <span>{rule.match_text}</span>
                <span>{rule.customer_number || "-"}</span>
                <span>{formatCostCategory(rule.default_cost_category)}</span>
                <span>{rule.default_assignment_code || "-"}</span>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={rule.is_active}
                    onChange={(event) => updateSupplierRule(rule, { is_active: event.target.checked })}
                  />
                  <span>{rule.is_active ? "aktiv" : "inaktiv"}</span>
                </label>
              </div>
            ))}
          </div>
        </section>

        <section className="admin-card admin-card-wide">
          <div className="card-header">
            <div>
              <p className="eyebrow">Buchungsentwurf und Export</p>
              <h3>Kontierungsregeln</h3>
            </div>
            <StatusPill value={`${accountingRules.length} Regeln`} />
          </div>
          <form className="form-grid accounting-form" onSubmit={createAccountingRule}>
            <FormField label="Name">
              <input placeholder="Material 19%" value={accountingForm.name} onChange={(event) => setAccountingForm({ ...accountingForm, name: event.target.value })} required />
            </FormField>
            <FormField label="Lieferant enthält">
              <input placeholder="optional, z.B. Lüchau" value={accountingForm.supplier_match_text} onChange={(event) => setAccountingForm({ ...accountingForm, supplier_match_text: event.target.value })} />
            </FormField>
            <FormField label="Kostenart">
              <select value={accountingForm.cost_category} onChange={(event) => setAccountingForm({ ...accountingForm, cost_category: event.target.value })}>
                <option value="">Alle Kostenarten</option>
                <option value="material">Material</option>
                <option value="subcontractor">Fremdleistung</option>
                <option value="fuel_vehicle">Fahrzeug/Tanken</option>
                <option value="software_subscription">Software/Abo</option>
                <option value="security_subscription">Überwachung/Abo</option>
                <option value="general_overhead">Sonstige Gemeinkosten</option>
              </select>
            </FormField>
            <FormField label="Aufwandskonto">
              <input placeholder="z.B. 3400" value={accountingForm.debit_account} onChange={(event) => setAccountingForm({ ...accountingForm, debit_account: event.target.value })} required />
            </FormField>
            <FormField label="Gegenkonto">
              <input placeholder="z.B. Kreditor/Sammelkonto" value={accountingForm.credit_account} onChange={(event) => setAccountingForm({ ...accountingForm, credit_account: event.target.value })} required />
            </FormField>
            <FormField label="Steuerschlüssel">
              <input placeholder="optional" value={accountingForm.tax_key} onChange={(event) => setAccountingForm({ ...accountingForm, tax_key: event.target.value })} />
            </FormField>
            <FormField label="Steuersatz">
              <input placeholder="19.00" value={accountingForm.tax_rate} onChange={(event) => setAccountingForm({ ...accountingForm, tax_rate: event.target.value })} />
            </FormField>
            <FormField label="Skontokonto">
              <input placeholder="optional" value={accountingForm.discount_account} onChange={(event) => setAccountingForm({ ...accountingForm, discount_account: event.target.value })} />
            </FormField>
            <button type="submit">Kontierungsregel anlegen</button>
          </form>
          <div className="data-table accounting-table">
            <div className="data-row data-head">
              <span>Name</span>
              <span>Lieferant</span>
              <span>Kostenart</span>
              <span>Soll</span>
              <span>Haben</span>
              <span>Steuer</span>
              <span>Skonto</span>
              <span>Aktiv</span>
            </div>
            {accountingRules.map((rule) => (
              <div className="data-row" key={rule.id}>
                <strong>{rule.name}</strong>
                <span>{rule.supplier_match_text || "-"}</span>
                <span>{formatCostCategory(rule.cost_category)}</span>
                <span>{rule.debit_account}</span>
                <span>{rule.credit_account}</span>
                <span>{[rule.tax_key, rule.tax_rate ? `${rule.tax_rate} %` : null].filter(Boolean).join(" / ") || "-"}</span>
                <span>{rule.discount_account || "-"}</span>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={rule.is_active}
                    onChange={(event) => updateAccountingRule(rule, { is_active: event.target.checked })}
                  />
                  <span>{rule.is_active ? "aktiv" : "inaktiv"}</span>
                </label>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function FormField({ label, children }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function StatusPill({ value, tone = "green" }) {
  return <span className={`status-pill ${tone}`}>{value}</span>;
}

function Field({ label, value }) {
  return (
    <span className="field">
      <small>{label}</small>
      <strong>{value || "-"}</strong>
    </span>
  );
}

function ProjectSummary({ rawResult, tenantProfile }) {
  const lines = projectSummaryLines(rawResult, tenantProfile);
  if (!lines.length) return "-";

  return <span className="project-summary">{lines.join("\n")}</span>;
}

function AllocationLines({ lines, tenantProfile }) {
  if (!lines?.length) return null;

  return (
    <div className="allocation-lines">
      <h3>Aufteilung</h3>
      <div className="allocation-table">
        {lines.map((line) => (
          <div key={`${line.delivery_address}-${line.amount}`} className="allocation-row">
            <span>
              {line.assignment_code
                ? formatAssignmentCode(line.assignment_code, line.assignment_kind, tenantProfile)
                : line.project_code
                  ? `BV ${displayProjectCode(line.project_code)}`
                  : `${tenantProfile.assignment_label_singular} ungeklaert`},{" "}
              {line.address || line.delivery_address},{" "}
              {formatMoney(line.amount)} Netto
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PaymentTerms({ document, rawResult, onSelect, isSaving }) {
  const terms = paymentTermLines(rawResult);
  if (!terms.length) return null;
  const selectedType = document.payment_decision?.payment_type;
  const isLocked = document.status === "review_approved";

  return (
    <div className="payment-terms">
      <h3>Zahlung und Skonto</h3>
      <div className="payment-table">
        <div className="payment-row payment-head">
          <span>Option</span>
          <span>Fällig</span>
          <span>Betrag</span>
          <span>Skonto</span>
          <span>Auswahl</span>
        </div>
        {terms.map((term) => (
          <div className="payment-row" key={`${term.type}-${term.due_date || "ohne-datum"}`}>
            <strong>{term.label}</strong>
            <span>{formatDate(term.due_date)}</span>
            <span>{formatMoney(term.amount)}</span>
            <span>{term.discount_amount ? formatMoney(term.discount_amount) : "-"}</span>
            {selectedType === term.type ? (
              <StatusPill value="gewählt" tone="green" />
            ) : (
              <button
                className="secondary-button"
                type="button"
                onClick={() => onSelect(document, term)}
                disabled={isLocked || isSaving}
              >
                {isSaving ? "Speichert..." : "Wählen"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function BookingSuggestions({ document, suggestions, tenantProfile, onSave, savingIds = [] }) {
  const [drafts, setDrafts] = useState({});

  useEffect(() => {
    setDrafts(
      Object.fromEntries(
        (suggestions ?? []).map((suggestion) => [suggestion.id, bookingSuggestionDraft(suggestion)]),
      ),
    );
  }, [suggestions]);

  if (!suggestions?.length) return null;

  const isLocked = document.status === "review_approved";

  function updateDraft(suggestionId, patch) {
    setDrafts((current) => ({
      ...current,
      [suggestionId]: {
        ...current[suggestionId],
        ...patch,
      },
    }));
  }

  return (
    <div className="booking-suggestions">
      <div className="card-header">
        <div>
          <p className="eyebrow">Freigabe</p>
          <h3>{isLocked ? "Final freigegeben" : "Buchungsvorschlag prüfen"}</h3>
        </div>
        <StatusPill value={`${suggestions.length} Zeilen`} />
      </div>
      <div className="booking-table">
        <div className="booking-edit-row booking-head">
          <span>Nr.</span>
          <span>Beschreibung</span>
          <span>Zuordnung</span>
          <span>Kostenart</span>
          <span>Netto</span>
          <span>USt</span>
          <span>Brutto</span>
          <span>Status</span>
        </div>
        {suggestions.map((suggestion) => {
          const draft = drafts[suggestion.id] ?? bookingSuggestionDraft(suggestion);
          return (
            <div className="booking-edit-row" key={suggestion.id}>
              <strong>{suggestion.line_no}</strong>
              <input
                value={draft.description}
                onChange={(event) => updateDraft(suggestion.id, { description: event.target.value })}
                disabled={isLocked}
                aria-label={`Beschreibung Zeile ${suggestion.line_no}`}
              />
              <div className="assignment-edit">
                <input
                  value={draft.assignment_code}
                  onChange={(event) => updateDraft(suggestion.id, { assignment_code: event.target.value })}
                  disabled={isLocked}
                  aria-label={`Zuordnung Zeile ${suggestion.line_no}`}
                />
                <select
                  value={draft.assignment_kind}
                  onChange={(event) => updateDraft(suggestion.id, { assignment_kind: event.target.value })}
                  disabled={isLocked}
                  aria-label={`Zuordnungsart Zeile ${suggestion.line_no}`}
                >
                  <option value="">-</option>
                  <option value="construction_project">Bauvorhaben</option>
                  <option value="construction_or_dropoff_site">Bauvorhaben / Stellplatz</option>
                  <option value="location">Standort</option>
                  <option value="cost_object">Kostenobjekt</option>
                  <option value="vehicle">Fahrzeug</option>
                  <option value="subscription">Abo/Vertrag</option>
                  <option value="department">Bereich</option>
                </select>
              </div>
              <select
                value={draft.cost_category}
                onChange={(event) => updateDraft(suggestion.id, { cost_category: event.target.value })}
                disabled={isLocked}
                aria-label={`Kostenart Zeile ${suggestion.line_no}`}
              >
                <option value="">-</option>
                <option value="material">Material</option>
                <option value="subcontractor">Fremdleistung</option>
                <option value="fuel_vehicle">Fahrzeug/Tanken</option>
                <option value="software_subscription">Software/Abo</option>
                <option value="security_subscription">Überwachung/Abo</option>
                <option value="general_overhead">Sonstige Gemeinkosten</option>
              </select>
              <MoneyInput
                value={draft.net_amount}
                onChange={(value) => updateDraft(suggestion.id, { net_amount: value })}
                disabled={isLocked}
                label={`Netto Zeile ${suggestion.line_no}`}
              />
              <MoneyInput
                value={draft.tax_amount}
                onChange={(value) => updateDraft(suggestion.id, { tax_amount: value })}
                disabled={isLocked}
                label={`USt Zeile ${suggestion.line_no}`}
              />
              <MoneyInput
                value={draft.gross_amount}
                onChange={(value) => updateDraft(suggestion.id, { gross_amount: value })}
                disabled={isLocked}
                label={`Brutto Zeile ${suggestion.line_no}`}
              />
              {isLocked ? (
                <StatusPill value={formatBookingStatus(suggestion.status)} tone="gray" />
              ) : (
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => onSave(document, suggestion, draft)}
                  disabled={savingIds.includes(suggestion.id)}
                >
                  {savingIds.includes(suggestion.id) ? "Speichert..." : "Speichern"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MoneyInput({ value, onChange, disabled, label }) {
  return (
    <input
      inputMode="decimal"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={label}
    />
  );
}

function bookingSuggestionDraft(suggestion) {
  return {
    booking_type: suggestion.booking_type || "incoming_invoice",
    cost_category: suggestion.cost_category || "",
    assignment_code: suggestion.assignment_code || "",
    assignment_kind: suggestion.assignment_kind || "",
    description: suggestion.description || "",
    net_amount: moneyDraftValue(suggestion.net_amount),
    tax_amount: moneyDraftValue(suggestion.tax_amount),
    gross_amount: moneyDraftValue(suggestion.gross_amount),
    currency: suggestion.currency || "EUR",
  };
}

function normalizeBookingSuggestion(values) {
  return {
    booking_type: values.booking_type || "incoming_invoice",
    cost_category: values.cost_category || null,
    assignment_code: values.assignment_code?.trim() || null,
    assignment_kind: values.assignment_kind || null,
    description: values.description?.trim() || null,
    net_amount: decimalOrNull(values.net_amount),
    tax_amount: decimalOrNull(values.tax_amount),
    gross_amount: decimalOrNull(values.gross_amount),
    currency: values.currency || "EUR",
  };
}

function moneyDraftValue(value) {
  if (value === null || value === undefined || value === "") return "";
  return String(value).replace(".", ",");
}

function decimalOrNull(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  return String(value).trim().replace(",", ".");
}

async function downloadResponse(response, fallbackFilename) {
  const blob = await response.blob();
  const filename = filenameFromDisposition(response.headers.get("content-disposition")) || fallbackFilename || "belege.zip";
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

function filenameFromDisposition(disposition) {
  if (!disposition) return null;
  const utfMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utfMatch) return decodeURIComponent(utfMatch[1]);
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] || null;
}

function safeVisibleFilename(filename) {
  return String(filename || "beleg.pdf")
    .replace(/[<>:"/\\|?*]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\.+$/, "") || "beleg.pdf";
}

function formatSize(sizeBytes) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  return `${Math.round(sizeBytes / 1024)} KB`;
}

function formatStatus(status) {
  const labels = {
    review_pending: "Prüfen",
    extracted: "Extrahiert",
    review_ready: "Vorschlag",
    review_approved: "Freigegeben",
  };
  return labels[status] ?? status;
}

function formatBookingStatus(status) {
  const labels = {
    approved: "freigegeben",
    reviewed: "geprüft",
    suggested: "Vorschlag",
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

function formatAssignment(rawResult, tenantProfile = assignmentProfileFromRaw(rawResult)) {
  if (rawResult?.assignment_code) return formatAssignmentCode(rawResult.assignment_code, rawResult.assignment_kind, tenantProfile);
  if (rawResult?.project_code) return `BV ${rawResult.project_code}`;
  const labels = {
    general_cost: "Allgemeine Kosten",
    assignment_unresolved: `${tenantProfile.assignment_label_singular} ungeklaert`,
    assignment_split: `${tenantProfile.assignment_label_plural} aufgeteilt`,
    project_split: "BV aufgeteilt",
    project_unresolved: "BV ungeklaert",
    assigned: "Zugeordnet",
  };
  return labels[rawResult?.assignment_type] ?? null;
}

function formatAssignmentKind(value, tenantProfile = defaultTenantProfile("general")) {
  const labels = {
    construction_project: "Bauvorhaben",
    construction_or_dropoff_site: "Bauvorhaben / Stellplatz",
    location: "Standort",
    cost_object: "Kostenobjekt",
    vehicle: "Fahrzeug",
    subscription: "Abo/Vertrag",
    department: "Bereich",
  };
  return labels[value] ?? tenantProfile.assignment_label_singular ?? value;
}

function usesProjectNumber(kind) {
  return ["construction_project", "construction_or_dropoff_site"].includes(kind);
}

function projectSummaryLines(rawResult, tenantProfile = defaultTenantProfile("general")) {
  if (rawResult?.assignment_code) {
    const number = displayProjectNumber({
      project_number: rawResult.project_number,
      project_code: rawResult.project_code || rawResult.assignment_code,
    });
    const code = formatAssignmentCode(rawResult.assignment_code, rawResult.assignment_kind, tenantProfile);
    return [[number, code].filter(Boolean).join(" ")];
  }
  if (rawResult?.allocation_lines?.length) {
    return rawResult.allocation_lines
      .map((line) => {
        const code = line.assignment_code
          ? formatAssignmentCode(line.assignment_code, line.assignment_kind, tenantProfile)
          : line.project_code
            ? `BV ${displayProjectCode(line.project_code, { compact: true })}`
            : `${tenantProfile.assignment_label_singular} ungeklaert`;
        return [displayProjectNumber(line), code].filter(Boolean).join(" ");
      });
  }
  if (rawResult?.project_code) {
    const code = `BV ${displayProjectCode(rawResult.project_code, { compact: true })}`;
    return [[displayProjectNumber(rawResult), code].filter(Boolean).join(" ")];
  }
  return [];
}

function displayProjectCode(projectCode, options = {}) {
  if (options.compact && projectCode === "Wewe20") return "Wewe";
  const labels = {
    Heu92: "Hk92",
  };
  return labels[projectCode] ?? projectCode;
}

function displayProjectNumber(project) {
  const fallback = projectNumberFallback(project?.project_code);
  if (project?.project_code === "Hk92" || project?.project_code === "Heu92") return fallback;
  return project?.project_number || fallback;
}

function projectNumberFallback(projectCode) {
  const numbers = {
    Wewe20: "25-00008",
    Heu92: "2026-00007",
    Hk92: "2026-00007",
  };
  return numbers[projectCode] ?? null;
}

function formatAssignmentCode(code, kind, tenantProfile) {
  if (!code) return null;
  if (tenantProfile.assignment_code_prefix) return `${tenantProfile.assignment_code_prefix} ${code}`;
  return `${formatAssignmentKind(kind, tenantProfile)} ${code}`;
}

function assignmentProfileFromRaw(rawResult) {
  return {
    ...defaultTenantProfile("general"),
    assignment_label_singular: rawResult?.assignment_label_singular || defaultTenantProfile("general").assignment_label_singular,
    assignment_label_plural: rawResult?.assignment_label_plural || defaultTenantProfile("general").assignment_label_plural,
    assignment_code_label: rawResult?.assignment_code_label || defaultTenantProfile("general").assignment_code_label,
    assignment_code_prefix: rawResult?.assignment_code_prefix ?? defaultTenantProfile("general").assignment_code_prefix,
  };
}

function formatCostCategory(value) {
  if (!value) return "-";
  const labels = {
    fuel_vehicle: "Fahrzeug/Tanken",
    general_overhead: "Sonstige Gemeinkosten",
    material: "Material",
    security_subscription: "Überwachung/Abo",
    software_subscription: "Software/Abo",
    subcontractor: "Fremdleistung",
  };
  return labels[value] ?? value;
}

function industryLabel(value) {
  const labels = {
    construction: "Baubranche",
    container_transport: "Container/Transport",
    fitness_studio: "Sportstudio",
    general: "Allgemein",
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
  const discountTerm = paymentTermLines(rawResult).find((term) => term.type !== "full_amount");
  if (discountTerm?.amount) return discountTerm.amount;
  if (rawResult?.discounted_payable_amount) return rawResult.discounted_payable_amount;
  if (!rawResult?.gross_amount || !rawResult?.discount_amount) return null;
  return Number(rawResult.gross_amount) - Math.abs(Number(rawResult.discount_amount));
}

function paymentTermLines(rawResult) {
  if (rawResult?.payment_terms?.length) return rawResult.payment_terms;
  const terms = [];
  if (rawResult?.gross_amount) {
    terms.push({
      type: "full_amount",
      label: rawResult.document_type === "credit_note" ? "Gutschrift verrechnen" : "Ohne Abzug zahlen",
      due_date: rawResult.due_date,
      amount: rawResult.gross_amount,
      discount_amount: null,
    });
  }
  const amount = legacyDiscountedAmount(rawResult);
  if (amount && rawResult?.discount_due_date) {
    terms.push({
      type: rawResult.document_type === "credit_note" ? "credit_note_settlement" : "cash_discount",
      label: rawResult.document_type === "credit_note" ? "Verrechnung mit Skonto" : "Skontozahlung",
      due_date: rawResult.discount_due_date,
      amount,
      discount_amount: rawResult.discount_amount,
    });
  }
  return terms;
}

function legacyDiscountedAmount(rawResult) {
  if (rawResult?.discounted_payable_amount) return rawResult.discounted_payable_amount;
  if (!rawResult?.gross_amount || !rawResult?.discount_amount) return null;
  return Number(rawResult.gross_amount) - Math.abs(Number(rawResult.discount_amount));
}

function splitAliases(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitCommaList(value) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function emptyToNull(value) {
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => [key, entry === "" ? null : entry]),
  );
}

function defaultTenantProfile(industry) {
  const templates = {
    construction: {
      industry: "construction",
      display_name: "demo-mandant",
      assignment_label_singular: "Bauvorhaben",
      assignment_label_plural: "Bauvorhaben",
      assignment_code_label: "Bauvorhaben",
      assignment_code_prefix: "BV",
      default_assignment_kind: "construction_project",
      allow_multiple_assignments: true,
    },
    fitness_studio: {
      industry: "fitness_studio",
      display_name: "",
      assignment_label_singular: "Standort",
      assignment_label_plural: "Standorte",
      assignment_code_label: "Standort",
      assignment_code_prefix: "",
      default_assignment_kind: "location",
      allow_multiple_assignments: false,
    },
    container_transport: {
      industry: "container_transport",
      display_name: "",
      assignment_label_singular: "Bauvorhaben / Stellplatz",
      assignment_label_plural: "Bauvorhaben / Stellplätze",
      assignment_code_label: "Bauvorhaben / Stellplatz",
      assignment_code_prefix: "",
      default_assignment_kind: "construction_or_dropoff_site",
      allow_multiple_assignments: true,
    },
    general: {
      industry: "general",
      display_name: "",
      assignment_label_singular: "Kostenstelle",
      assignment_label_plural: "Kostenstellen",
      assignment_code_label: "Kostenstelle",
      assignment_code_prefix: "",
      default_assignment_kind: "cost_object",
      allow_multiple_assignments: true,
    },
  };
  return templates[industry] ?? templates.general;
}

createRoot(document.getElementById("root")).render(<App />);
