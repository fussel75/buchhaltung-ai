import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const apiBaseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL ?? "/api");
const AuthContext = createContext(null);
const COST_CATEGORY_OPTIONS = [
  ["material", "Material"],
  ["subcontractor", "Fremdleistung"],
  ["fuel_vehicle", "Fahrzeug/Tanken"],
  ["software_subscription", "Software/Abo"],
  ["security_subscription", "Überwachung/Abo"],
  ["general_overhead", "Sonstige Gemeinkosten"],
];

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
    return <main className="app"><p className="empty">Login wird geprüft ...</p></main>;
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
  const [validatingIds, setValidatingIds] = useState([]);
  const [savingSuggestionIds, setSavingSuggestionIds] = useState([]);
  const [savingPaymentIds, setSavingPaymentIds] = useState([]);
  const [savingExtractionIds, setSavingExtractionIds] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [exporting, setExporting] = useState("");
  const [bookingPreview, setBookingPreview] = useState(null);
  const [exportMonth, setExportMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [uploadBatch, setUploadBatch] = useState(null);
  const [extractionBatch, setExtractionBatch] = useState(null);
  const [reviewBatch, setReviewBatch] = useState(null);
  const [bulkJobs, setBulkJobs] = useState([]);
  const [reviewFilter, setReviewFilter] = useState("all");
  const [expandedDocumentIds, setExpandedDocumentIds] = useState([]);
  const [approvalDocumentId, setApprovalDocumentId] = useState(null);
  const [focusedReviewDocumentId, setFocusedReviewDocumentId] = useState(null);
  const [approvalError, setApprovalError] = useState("");
  const [approvalIssues, setApprovalIssues] = useState([]);
  const [accountingRuleDraft, setAccountingRuleDraft] = useState(null);
  const [accountingRuleEditTarget, setAccountingRuleEditTarget] = useState(null);
  const [tenantProfile, setTenantProfile] = useState(defaultTenantProfile("construction"));
  const approvalValidationRequestRef = useRef(0);

  const canUpload = useMemo(() => tenantId.trim().length > 0, [tenantId]);
  const activeTenantId = tenantId.trim();
  const isUploading = uploadBatch?.state === "running";
  const isBulkExtracting = extractionBatch?.state === "running";
  const isBulkPreparingReview = reviewBatch?.state === "running";
  const isBookingExportBlockedByPreview = bookingPreview?.month === exportMonth && bookingPreview.isBlocked;
  const queueStats = useMemo(
    () => ({
      pending: documents.filter((document) => document.status === "review_pending").length,
      extracted: documents.filter((document) => document.status === "extracted").length,
      ready: documents.filter((document) => document.status === "review_ready").length,
      approved: documents.filter((document) => document.status === "review_approved").length,
    }),
    [documents],
  );
  const filteredDocuments = useMemo(
    () => documents.filter((document) => reviewFilter === "all" || document.status === reviewFilter),
    [documents, reviewFilter],
  );
  const extractableDocuments = useMemo(
    () => filteredDocuments.filter((document) => !document.extraction && document.status === "review_pending"),
    [filteredDocuments],
  );
  const reviewableDocuments = useMemo(
    () => filteredDocuments.filter((document) => document.status === "extracted" && document.extraction && !document.booking_suggestions?.length),
    [filteredDocuments],
  );
  const focusableReviewDocuments = useMemo(
    () => documents.filter((document) => document.extraction),
    [documents],
  );
  const activeBulkJobs = useMemo(
    () => bulkJobs.filter((job) => ["queued", "running"].includes(job.status)),
    [bulkJobs],
  );
  const approvalDocument = useMemo(
    () => documents.find((document) => document.id === approvalDocumentId) ?? null,
    [approvalDocumentId, documents],
  );
  const focusedReviewDocument = useMemo(
    () => documents.find((document) => document.id === focusedReviewDocumentId) ?? null,
    [focusedReviewDocumentId, documents],
  );
  const focusedReviewIndex = useMemo(
    () => focusableReviewDocuments.findIndex((document) => document.id === focusedReviewDocumentId),
    [focusableReviewDocuments, focusedReviewDocumentId],
  );
  const focusedReviewPositionLabel = focusedReviewIndex >= 0
    ? `${focusedReviewIndex + 1} / ${focusableReviewDocuments.length}`
    : "";
  const clearAccountingRuleDraft = useCallback(() => setAccountingRuleDraft(null), []);
  const clearAccountingRuleEditTarget = useCallback(() => setAccountingRuleEditTarget(null), []);

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

  const loadBulkJobs = useCallback(async () => {
    if (!activeTenantId) {
      setBulkJobs([]);
      return;
    }

    const response = await apiFetch(`/documents/bulk-jobs?tenant_id=${encodeURIComponent(activeTenantId)}&limit=8`);

    if (!response.ok) {
      throw new Error(`Auftragsverlauf konnte nicht geladen werden: ${response.status}`);
    }

    const result = await response.json();
    setBulkJobs(result.jobs ?? []);
  }, [activeTenantId, apiFetch]);

  const rememberBulkJob = useCallback((job) => {
    if (!job?.id) return;
    setBulkJobs((current) => [job, ...current.filter((existingJob) => existingJob.id !== job.id)].slice(0, 8));
  }, []);

  useEffect(() => {
    loadDocuments().catch((loadError) => setError(loadError.message));
  }, [loadDocuments]);

  useEffect(() => {
    loadBulkJobs().catch((loadError) => setError(loadError.message));
  }, [loadBulkJobs]);

  useEffect(() => {
    if (!activeBulkJobs.length) return undefined;
    const timer = window.setInterval(() => {
      loadBulkJobs().catch((loadError) => setError(loadError.message));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeBulkJobs.length, loadBulkJobs]);

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

  useEffect(() => {
    if (!approvalDocumentId) return undefined;

    function handleEscape(event) {
      if (event.key === "Escape" && !approvingIds.includes(approvalDocumentId)) {
        approvalValidationRequestRef.current += 1;
        setApprovalDocumentId(null);
      }
    }

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [approvalDocumentId, approvingIds]);

  function moveFocusedReview(delta) {
    if (focusedReviewIndex < 0 || focusableReviewDocuments.length < 2) return;

    const nextIndex = focusedReviewIndex + delta;
    if (nextIndex < 0 || nextIndex >= focusableReviewDocuments.length) return;

    const nextDocumentId = focusableReviewDocuments[nextIndex].id;
    setFocusedReviewDocumentId(nextDocumentId);
    setExpandedDocumentIds((current) =>
      current.includes(nextDocumentId) ? current : [...current, nextDocumentId],
    );
  }

  const uploadFile = useCallback(
    async (file) => {
      const formData = new FormData();
      formData.append("tenant_id", activeTenantId);
      formData.append("file", file);

      const response = await apiFetch("/documents/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.detail || `Upload fehlgeschlagen: ${response.status}`);
      }

      const result = await response.json();
      return result;
    },
    [activeTenantId, apiFetch],
  );

  const handleFiles = useCallback(
    async (files) => {
      const selectedFiles = Array.from(files || []).filter((file) => file?.name);
      if (!canUpload || selectedFiles.length === 0 || isUploading) return;

      const results = {
        saved: [],
        duplicates: [],
        failed: [],
      };

      setError("");
      setNotice("");
      setUploadBatch({
        state: "running",
        total: selectedFiles.length,
        done: 0,
        current: selectedFiles[0]?.name || "",
        saved: 0,
        duplicates: 0,
        failed: 0,
      });

      for (const [index, file] of selectedFiles.entries()) {
        setUploadBatch((current) => ({
          ...(current || {}),
          state: "running",
          current: file.name,
          done: index,
          total: selectedFiles.length,
        }));

        try {
          const result = await uploadFile(file);
          if (result.is_duplicate) {
            results.duplicates.push(result.document.original_filename || file.name);
          } else {
            results.saved.push(result.document.original_filename || file.name);
          }
        } catch (uploadError) {
          results.failed.push({
            name: file.name,
            message: uploadError.message,
          });
        } finally {
          setUploadBatch((current) => ({
            ...(current || {}),
            state: "running",
            done: index + 1,
            total: selectedFiles.length,
            saved: results.saved.length,
            duplicates: results.duplicates.length,
            failed: results.failed.length,
          }));
        }
      }

      await loadDocuments();
      setUploadBatch({
        state: "done",
        total: selectedFiles.length,
        done: selectedFiles.length,
        current: "",
        saved: results.saved.length,
        duplicates: results.duplicates.length,
        failed: results.failed.length,
      });

      const noticeParts = [];
      if (results.saved.length) noticeParts.push(`${results.saved.length} gespeichert`);
      if (results.duplicates.length) noticeParts.push(`${results.duplicates.length} Dubletten`);
      if (results.failed.length) noticeParts.push(`${results.failed.length} fehlgeschlagen`);
      setNotice(`Stapel verarbeitet: ${noticeParts.join(", ")}.`);

      if (results.failed.length) {
        setError(
          `Nicht hochgeladen: ${results.failed
            .slice(0, 3)
            .map((failure) => `${failure.name} (${failure.message})`)
            .join("; ")}${results.failed.length > 3 ? " ..." : ""}`,
        );
      }
    },
    [canUpload, isUploading, loadDocuments, uploadFile],
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
          const result = await response.json().catch(() => ({}));
          throw new Error(result.detail || `Extraktion fehlgeschlagen: ${response.status}`);
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

  const reextractDocument = useCallback(
    async (document) => {
      const confirmed = window.confirm(
        `Beleg "${document.original_filename}" neu extrahieren? Vorhandene Buchungsvorschläge, Freigaben und Zahlungsentscheidungen werden verworfen.`,
      );
      if (!confirmed) return;

      setError("");
      setNotice("");
      setExtractingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}/reextract`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true }),
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(formatApiError(result.detail, `Neu-Extraktion fehlgeschlagen: ${response.status}`));
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Neu extrahiert: ${result.document.original_filename}`);
      } catch (extractError) {
        setError(extractError.message);
      } finally {
        setExtractingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const startBulkExtraction = useCallback(async () => {
    const targets = extractableDocuments;
    if (!targets.length || isBulkExtracting) return;

    setError("");
    setNotice("");
    setExtractionBatch({
      state: "running",
      total: targets.length,
      done: 0,
      current: targets[0]?.original_filename || "",
      failed: 0,
    });
    setExtractingIds((current) => Array.from(new Set([...current, ...targets.map((document) => document.id)])));

    try {
      const response = await apiFetch("/documents/bulk/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          document_ids: targets.map((document) => document.id),
        }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Bulk-Extraktion fehlgeschlagen: ${response.status}`));
      }
      const result = await response.json();
      rememberBulkJob(result.job);
      setExtractionBatch(batchStateFromJob(result.job));
      const job = await waitForBulkJob(apiFetch, result.job.id, setExtractionBatch);
      rememberBulkJob(job);
      await loadBulkJobs();
      await loadDocuments();
      setNotice(`Bulk-Extraktion abgeschlossen: ${job.succeeded_count} extrahiert, ${job.failed_count} fehlgeschlagen.`);
      if (job.failed_count) {
        setError(formatBulkJobFailures(job, "Nicht extrahiert"));
      }
    } catch (extractError) {
      setError(extractError.message);
    } finally {
      setExtractingIds((current) => current.filter((id) => !targets.some((document) => document.id === id)));
    }
  }, [activeTenantId, apiFetch, extractableDocuments, isBulkExtracting, loadBulkJobs, loadDocuments, rememberBulkJob]);

  const startBulkReviewPreparation = useCallback(async () => {
    const targets = reviewableDocuments;
    if (!targets.length || isBulkPreparingReview) return;

    setError("");
    setNotice("");
    setReviewBatch({
      state: "running",
      total: targets.length,
      done: 0,
      current: targets[0]?.original_filename || "",
      failed: 0,
    });
    setApprovingIds((current) => Array.from(new Set([...current, ...targets.map((document) => document.id)])));

    try {
      const response = await apiFetch("/documents/bulk/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          document_ids: targets.map((document) => document.id),
        }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Bulk-Vorschläge fehlgeschlagen: ${response.status}`));
      }
      const result = await response.json();
      rememberBulkJob(result.job);
      setReviewBatch(batchStateFromJob(result.job));
      const job = await waitForBulkJob(apiFetch, result.job.id, setReviewBatch);
      rememberBulkJob(job);
      await loadBulkJobs();
      await loadDocuments();
      setNotice(`Buchungsvorschläge erstellt: ${job.succeeded_count} erstellt, ${job.failed_count} fehlgeschlagen.`);
      if (job.failed_count) {
        setError(formatBulkJobFailures(job, "Kein Vorschlag erstellt"));
      }
    } catch (reviewError) {
      setError(reviewError.message);
    } finally {
      setApprovingIds((current) => current.filter((id) => !targets.some((document) => document.id === id)));
    }
  }, [activeTenantId, apiFetch, isBulkPreparingReview, loadBulkJobs, loadDocuments, rememberBulkJob, reviewableDocuments]);

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
      if (document.status !== "review_ready") {
        const message = "Finale Freigabe ist nur im Status Vorschlag möglich.";
        setApprovalError(message);
        setApprovalIssues([]);
        setError(message);
        return;
      }

      setApprovalError("");
      setApprovalIssues([]);
      setError("");
      setNotice("");
      setApprovingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}/approve`, {
          method: "POST",
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          setApprovalIssues(extractApprovalIssues(result.detail));
          throw new Error(formatApprovalError(result.detail, response.status));
        }

        const result = await response.json();
        await loadDocuments();
        setApprovalDocumentId(null);
        setApprovalIssues([]);
        setNotice(`Beleg final freigegeben: ${result.document.original_filename}`);
      } catch (approveError) {
        setApprovalError(approveError.message);
        setError(approveError.message);
      } finally {
        setApprovingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const openApprovalDialog = useCallback(
    async (document) => {
      if (document.status !== "review_ready") {
        const message = "Finale Freigabe ist nur im Status Vorschlag möglich.";
        setApprovalError(message);
        setApprovalIssues([]);
        setError(message);
        return;
      }

      setApprovalDocumentId(document.id);
      setApprovalError("");
      setApprovalIssues([]);
      setError("");
      setNotice("");
      const requestId = approvalValidationRequestRef.current + 1;
      approvalValidationRequestRef.current = requestId;
      setValidatingIds((current) => [...current, document.id]);

      try {
        const response = await apiFetch(`/documents/${document.id}/review-validation`);
        if (!response.ok) {
          throw new Error(`Freigabeprüfung fehlgeschlagen: ${response.status}`);
        }
        const result = await response.json();
        const details = Array.isArray(result.details) ? result.details : [];
        const errors = Array.isArray(result.errors) ? result.errors : [];
        if (approvalValidationRequestRef.current !== requestId) return;
        setApprovalIssues(details);
        setApprovalError(errors.length ? formatApprovalError({ message: "Freigabe blockiert", errors }, 409) : "");
      } catch (validationError) {
        if (approvalValidationRequestRef.current !== requestId) return;
        setApprovalError(validationError.message);
        setError(validationError.message);
      } finally {
        setValidatingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch],
  );

  function prepareAccountingRuleFromApproval(issue) {
    if (user?.role !== "admin") {
      setNotice("Kontierungsregel braucht Pflege. Bitte einen Admin bitten, die Regel unter Stammdaten zu prüfen.");
      return;
    }
    if (issue?.code !== "missing_accounting_rule") {
      setAccountingRuleEditTarget({
        id: `${Date.now()}-${issue?.accounting_rule_id || issue?.accounting_rule_name || issue?.cost_category || ""}`,
        rule_id: issue?.accounting_rule_id || "",
        accounting_rule_name: issue?.accounting_rule_name || issue?.suggested_name || "",
        supplier_name: issue?.supplier_name || "",
        cost_category: issue?.cost_category || "",
        focus_field: issue?.code === "missing_discount_account" ? "discount_account" : "debit_account",
      });
      approvalValidationRequestRef.current += 1;
      setApprovalDocumentId(null);
      setApprovalError("");
      setApprovalIssues([]);
      setActiveView("masterdata");
      setNotice("Kontierungsregel wird geöffnet. Bitte fehlende Konten ergänzen und speichern.");
      return;
    }
    const supplierName = issue?.supplier_name || approvalDocument?.extraction?.supplier_name || "";
    const costCategory = issue?.cost_category ?? approvalDocument?.booking_suggestions?.[0]?.cost_category ?? "";
    const suggestedName = issue?.suggested_name || defaultAccountingRuleName(supplierName, costCategory);

    setAccountingRuleDraft({
      id: `${Date.now()}-${costCategory}-${supplierName}`,
      form: {
        name: suggestedName,
        supplier_match_text: supplierName,
        cost_category: costCategory,
        debit_account: "",
        credit_account: "",
        tax_key: "",
        tax_rate: "19.00",
        discount_account: "",
      },
    });
    approvalValidationRequestRef.current += 1;
    setApprovalDocumentId(null);
    setApprovalError("");
    setApprovalIssues([]);
    setActiveView("masterdata");
    setNotice("Kontierungsregel vorbereitet. Bitte Aufwandskonto und Gegenkonto ergänzen und speichern.");
  }

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

  const saveExtraction = useCallback(
    async (document, values) => {
      setError("");
      setNotice("");
      setSavingExtractionIds((current) => [...current, document.id]);
      try {
        const response = await apiFetch(`/documents/${document.id}/extraction`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(normalizeExtractionUpdate(values)),
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(formatApiError(result.detail, `Extraktionsdaten konnten nicht gespeichert werden: ${response.status}`));
        }

        const result = await response.json();
        await loadDocuments();
        setNotice(`Extraktionsdaten gespeichert: ${result.document.original_filename}. Bitte Buchungsvorschlag neu erstellen.`);
      } catch (saveError) {
        setError(saveError.message);
      } finally {
        setSavingExtractionIds((current) => current.filter((id) => id !== document.id));
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

  const toggleDocumentDetails = useCallback((documentId) => {
    setExpandedDocumentIds((current) =>
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
        const result = await response.json().catch(() => ({}));
        throw new Error(
          response.status === 404
            ? "Keine freigegebenen Buchungszeilen für diesen Monat gefunden."
            : formatApiError(result.detail, `Buchungsexport fehlgeschlagen: ${response.status}`),
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

  const loadBookingPreview = useCallback(async () => {
    const [year, month] = exportMonth.split("-").map((value) => Number(value));
    if (!year || !month) {
      setError("Bitte einen Monat auswählen.");
      return;
    }
    setError("");
    setNotice("");
    setExporting("booking-preview");
    try {
      const response = await apiFetch(
        `/documents/export/bookings?tenant_id=${encodeURIComponent(activeTenantId)}&year=${year}&month=${month}&format=json`,
      );
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "Keine freigegebenen Buchungszeilen für diesen Monat gefunden."
            : formatApiError(result.detail, `Buchungsvorschau fehlgeschlagen: ${response.status}`),
        );
      }
      setBookingPreview({
        month: exportMonth,
        rows: result.rows || [],
        invalidDocuments: result.invalid_documents || [],
        exportIssues: result.export_issues || [],
        isBlocked: Boolean(result.is_blocked),
      });
      setNotice(
        result.is_blocked
          ? `Buchungsvorschau geladen: ${result.rows?.length || 0} Zeilen, CSV noch blockiert`
          : `Buchungsvorschau geladen: ${result.rows?.length || 0} Zeilen`,
      );
    } catch (previewError) {
      setBookingPreview(null);
      setError(previewError.message);
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
          <aside className="review-sidebar">
          <section
            className={`dropzone${isDragging ? " active" : ""}${isUploading ? " uploading" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              if (isUploading) return;
              setIsDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragging(false);
              if (isUploading) return;
              handleFiles(event.dataTransfer.files);
            }}
          >
            <strong>{isUploading ? "Stapel wird hochgeladen" : "Belege hier ablegen"}</strong>
            <span>Mehrere PDFs, Bilder oder exportierte Rechnungen für den ausgewählten Mandanten.</span>
            {uploadBatch ? (
              <div className="upload-progress" aria-live="polite">
                <span>
                  {uploadBatch.done} / {uploadBatch.total} verarbeitet
                </span>
                {uploadBatch.current ? <strong>{uploadBatch.current}</strong> : null}
                <small>
                  {uploadBatch.saved} gespeichert, {uploadBatch.duplicates} Dubletten, {uploadBatch.failed} fehlgeschlagen
                </small>
              </div>
            ) : null}
            <input
              type="file"
              multiple
              disabled={!canUpload || isUploading}
              onChange={(event) => {
                handleFiles(event.target.files);
                event.target.value = "";
              }}
            />
          </section>
          <BulkJobHistory jobs={bulkJobs} />
          </aside>

          <section className="uploads">
        <div className="section-header queue-header">
          <div className="queue-heading">
            <div>
              <h2>Review-Queue</h2>
              <span>{filteredDocuments.length} von {documents.length} Belegen</span>
            </div>
            <div className="filter-tabs" aria-label="Review-Filter">
              <button type="button" className={reviewFilter === "all" ? "active" : ""} onClick={() => setReviewFilter("all")}>
                Alle
              </button>
              <button type="button" className={reviewFilter === "review_pending" ? "active" : ""} onClick={() => setReviewFilter("review_pending")}>
                Offen {queueStats.pending}
              </button>
              <button type="button" className={reviewFilter === "extracted" ? "active" : ""} onClick={() => setReviewFilter("extracted")}>
                Extrahiert {queueStats.extracted}
              </button>
              <button type="button" className={reviewFilter === "review_ready" ? "active" : ""} onClick={() => setReviewFilter("review_ready")}>
                Vorschlag {queueStats.ready}
              </button>
              <button type="button" className={reviewFilter === "review_approved" ? "active" : ""} onClick={() => setReviewFilter("review_approved")}>
                Freigegeben {queueStats.approved}
              </button>
            </div>
          </div>
          <div className="queue-tools">
            <div className="queue-primary-actions">
              <button
                type="button"
                onClick={startBulkExtraction}
                disabled={!extractableDocuments.length || isBulkExtracting}
              >
                {isBulkExtracting ? "Extrahiert..." : `Offene extrahieren (${extractableDocuments.length})`}
              </button>
              <button
                type="button"
                onClick={startBulkReviewPreparation}
                disabled={!reviewableDocuments.length || isBulkPreparingReview}
              >
                {isBulkPreparingReview ? "Erstellt..." : `Vorschläge erstellen (${reviewableDocuments.length})`}
              </button>
            </div>
            <details className="export-menu">
              <summary>Export</summary>
              <div className="export-panel">
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
                  onClick={loadBookingPreview}
                  disabled={exporting === "booking-preview"}
                >
                  {exporting === "booking-preview" ? "Lädt..." : "Buchungsvorschau"}
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={exportBookingRows}
                  disabled={exporting === "bookings" || isBookingExportBlockedByPreview}
                >
                  {exporting === "bookings" ? "Erstellt..." : isBookingExportBlockedByPreview ? "CSV blockiert" : "Buchungsentwurf CSV"}
                </button>
              </div>
            </details>
          </div>
        </div>
        {extractionBatch ? (
          <div className="batch-progress" aria-live="polite">
            <strong>{extractionBatch.done} / {extractionBatch.total} extrahiert</strong>
            {extractionBatch.current ? <span>{extractionBatch.current}</span> : null}
            <small>{extractionBatch.failed} fehlgeschlagen</small>
          </div>
        ) : null}
        {reviewBatch ? (
          <div className="batch-progress" aria-live="polite">
            <strong>{reviewBatch.done} / {reviewBatch.total} Vorschläge</strong>
            {reviewBatch.current ? <span>{reviewBatch.current}</span> : null}
            <small>{reviewBatch.failed} fehlgeschlagen</small>
          </div>
        ) : null}
        {bookingPreview ? (
          <BookingExportPreview
            month={bookingPreview.month}
            rows={bookingPreview.rows}
            invalidDocuments={bookingPreview.invalidDocuments}
            exportIssues={bookingPreview.exportIssues}
            isBlocked={bookingPreview.isBlocked}
            onClose={() => setBookingPreview(null)}
          />
        ) : null}
        {documents.length === 0 ? (
          <p className="empty">Noch keine Belege für diesen Mandanten.</p>
        ) : filteredDocuments.length === 0 ? (
          <p className="empty">Keine Belege in diesem Filter.</p>
        ) : (
          <div className="queue">
            {filteredDocuments.map((document) => {
              const isExpanded = expandedDocumentIds.includes(document.id);
              return (
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
                      <div className="document-summary-line">
                        <span>{document.extraction?.supplier_name || "Extraktion ausstehend"}</span>
                        <span>{formatDate(document.extraction?.invoice_date)}</span>
                        <span>{formatMoney(document.extraction?.gross_amount)}</span>
                        {document.extraction?.warnings?.length ? <span>{document.extraction.warnings.length} Hinweise</span> : null}
                      </div>
                    </div>
                  </div>
                  <div className="document-actions">
                    <span className={`status ${statusTone(document.status)}`}>{formatStatus(document.status)}</span>
                    {!document.extraction && document.status === "review_pending" ? (
                      <button
                        type="button"
                        onClick={() => startExtraction(document.id)}
                        disabled={extractingIds.includes(document.id)}
                      >
                        {extractingIds.includes(document.id) ? "Läuft..." : "Extrahieren"}
                      </button>
                    ) : null}
                    {document.extraction && (!document.booking_suggestions?.length || (document.status !== "review_ready" && document.status !== "review_approved")) ? (
                      <button
                        type="button"
                        onClick={() => prepareReview(document)}
                        disabled={approvingIds.includes(document.id)}
                      >
                        {approvingIds.includes(document.id) ? "Erstellt..." : document.booking_suggestions?.length ? "Vorschlag neu" : "Vorschlag"}
                      </button>
                    ) : null}
                    {document.booking_suggestions?.length && document.status === "review_ready" ? (
                      <button
                        type="button"
                        onClick={() => openApprovalDialog(document)}
                        disabled={approvingIds.includes(document.id) || validatingIds.includes(document.id)}
                      >
                        {validatingIds.includes(document.id) ? "Prüft..." : approvingIds.includes(document.id) ? "Gibt frei..." : "Final freigeben"}
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
                      className="secondary-button"
                      type="button"
                      onClick={() => openDocument(document)}
                    >
                      Ansehen
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => toggleDocumentDetails(document.id)}
                    >
                      {isExpanded ? "Details ausblenden" : "Details"}
                    </button>
                    <details className="row-menu">
                      <summary>Datei</summary>
                      <div className="row-menu-panel">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => downloadDocument(document)}
                          disabled={exporting === document.id}
                        >
                          {exporting === document.id ? "Lädt..." : "Download"}
                        </button>
                        {document.extraction ? (
                          <button
                            className="secondary-button"
                            type="button"
                            onClick={() => reextractDocument(document)}
                            disabled={extractingIds.includes(document.id)}
                          >
                            {extractingIds.includes(document.id) ? "Läuft..." : "Neu extrahieren"}
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
                    </details>
                  </div>
                </div>

                {isExpanded && focusedReviewDocumentId !== document.id ? (
                  <>
                    {document.extraction ? (
                      <div className="extraction-panel">
                        <div className="review-check-header">
                          <div>
                            <p className="eyebrow">Prüfung</p>
                            <h3>Beleg prüfen</h3>
                          </div>
                          <button
                            className="secondary-button"
                            type="button"
                            onClick={() => setFocusedReviewDocumentId(document.id)}
                          >
                            Groß prüfen
                          </button>
                        </div>

                        <div className="review-workspace">
                          <DocumentPreview document={document} />
                          <div className="review-data">
                            <ExtractionEditForm
                              document={document}
                              tenantProfile={tenantProfile}
                              isSaving={savingExtractionIds.includes(document.id)}
                              onSave={saveExtraction}
                            />

                            {document.extraction?.warnings?.length ? (
                              <ul className="warnings">
                                {document.extraction.warnings.map((warning, index) => (
                                  <li key={`${warning}-${index}`}>{warning}</li>
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        </div>

                        <div className="review-fullwidth">
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
                      </div>
                    ) : (
                      <div className="pending-extraction">
                    <span>
                      {document.status === "review_pending"
                        ? "Extraktion ausstehend"
                        : "Extraktion für diesen Status gesperrt"}
                    </span>
                    <button
                      type="button"
                      onClick={() => startExtraction(document.id)}
                      disabled={document.status !== "review_pending" || extractingIds.includes(document.id)}
                    >
                      {document.status !== "review_pending"
                        ? "Gesperrt"
                        : extractingIds.includes(document.id)
                          ? "Läuft..."
                          : "Extraktion starten"}
                    </button>
                      </div>
                    )}

                    <div className="meta-grid file-meta">
                      <span>Hash <code>{document.sha256.slice(0, 16)}</code></span>
                      <span>Größe {formatSize(document.size_bytes)}</span>
                    </div>
                  </>
                ) : null}
              </article>
              );
            })}
          </div>
        )}
          </section>
        </section>
      ) : null}

      <ApprovalDialog
        document={approvalDocument}
        tenantProfile={tenantProfile}
        isApproving={approvalDocument ? approvingIds.includes(approvalDocument.id) : false}
        isValidating={approvalDocument ? validatingIds.includes(approvalDocument.id) : false}
        error={approvalError}
        issues={approvalIssues}
        canPrepareAccountingRule={user?.role === "admin"}
        onCancel={() => {
          approvalValidationRequestRef.current += 1;
          setApprovalDocumentId(null);
          setApprovalError("");
          setApprovalIssues([]);
        }}
        onConfirm={() => {
          if (approvalDocument) approveDocument(approvalDocument);
        }}
        onPrepareAccountingRule={prepareAccountingRuleFromApproval}
      />

      <ReviewFocusDialog
        document={focusedReviewDocument}
        tenantProfile={tenantProfile}
        isSavingExtraction={focusedReviewDocument ? savingExtractionIds.includes(focusedReviewDocument.id) : false}
        isSavingPayment={focusedReviewDocument ? savingPaymentIds.includes(focusedReviewDocument.id) : false}
        isSavingSuggestion={focusedReviewDocument ? savingSuggestionIds.includes(focusedReviewDocument.id) : false}
        hasPrevious={focusedReviewIndex > 0}
        hasNext={focusedReviewIndex >= 0 && focusedReviewIndex < focusableReviewDocuments.length - 1}
        positionLabel={focusedReviewPositionLabel}
        savingPaymentIds={savingPaymentIds}
        savingSuggestionIds={savingSuggestionIds}
        onClose={() => setFocusedReviewDocumentId(null)}
        onPrevious={() => moveFocusedReview(-1)}
        onNext={() => moveFocusedReview(1)}
        onSaveExtraction={saveExtraction}
        onSelectPayment={selectPaymentDecision}
        onSaveSuggestion={saveBookingSuggestion}
      />

      {activeView === "masterdata" && user?.role === "admin" ? (
        <MasterdataAdmin
          apiFetch={apiFetch}
          tenantId={activeTenantId}
          tenantProfile={tenantProfile}
          accountingRuleDraft={accountingRuleDraft}
          accountingRuleEditTarget={accountingRuleEditTarget}
          onAccountingRuleDraftConsumed={clearAccountingRuleDraft}
          onAccountingRuleEditTargetConsumed={clearAccountingRuleEditTarget}
          onProfileSaved={setTenantProfile}
        />
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

function BulkJobHistory({ jobs }) {
  const activeCount = jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  return (
    <section className="job-history">
      <div className="card-header">
        <div>
          <span>Stapelverarbeitung</span>
          <h2>Auftragsverlauf</h2>
        </div>
        <span className="status">{activeCount ? `${activeCount} läuft` : `${jobs.length} Einträge`}</span>
      </div>
      {jobs.length === 0 ? (
        <p className="empty">Noch keine Aufträge für diesen Mandanten.</p>
      ) : (
        <div className="job-list">
          {jobs.map((job) => (
            <article key={job.id} className="job-row">
              <div className="job-row-head">
                <strong>{formatBulkAction(job.action)}</strong>
                <span className="status">{formatBulkStatus(job.status)}</span>
              </div>
              <div className="job-progress-line">
                <progress value={job.processed_count || 0} max={Math.max(job.requested_total || 0, 1)} />
                <span>
                  {job.processed_count || 0} / {job.requested_total || 0}
                </span>
              </div>
              <div className="job-meta">
                <span>{job.succeeded_count || 0} erfolgreich</span>
                <span>{job.failed_count || 0} fehlgeschlagen</span>
                <span>{formatDateTime(job.started_at || job.created_at)}</span>
              </div>
              {job.error ? <p className="job-error">{job.error}</p> : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ExtractionEditForm({ document, tenantProfile, isSaving, onDirtyChange, onSave }) {
  const [form, setForm] = useState(() => extractionFormFromDocument(document));
  const baselineForm = useMemo(
    () => extractionFormFromDocument(document),
    [document.id, document.extraction?.updated_at],
  );
  const isDirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(baselineForm),
    [baselineForm, form],
  );
  const isApproved = document.status === "review_approved";

  useEffect(() => {
    setForm(baselineForm);
  }, [baselineForm]);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function submit(event) {
    event.preventDefault();
    onSave(document, form);
  }

  return (
    <form className="extraction-edit-form" onSubmit={submit}>
      <div className="detail-section-header">
        <div>
          <h3>Extraktionsdaten</h3>
          <span>bearbeitbar vor Buchungsvorschlag und Freigabe</span>
        </div>
        <StatusPill value={formatConfidence(document.extraction.confidence) || "geprüft"} tone="blue" />
      </div>
      {isDirty && !isApproved ? (
        <p className="inline-note">Ungespeicherte Änderungen. Bitte speichern, bevor du den Beleg wechselst.</p>
      ) : null}
      {document.status === "review_ready" ? (
        <p className="inline-note">Speichern verwirft bestehende Vorschläge. Danach bitte „Vorschlag neu“ erstellen.</p>
      ) : null}
      <div className="form-grid extraction-edit-grid">
        <FormField label="Lieferant">
          <input value={form.supplier_name} onChange={(event) => updateField("supplier_name", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Rechnung">
          <input value={form.invoice_number} onChange={(event) => updateField("invoice_number", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Datum">
          <input type="date" value={form.invoice_date} onChange={(event) => updateField("invoice_date", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Kunden-Nr.">
          <input value={form.customer_number} onChange={(event) => updateField("customer_number", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Belegart">
          <select value={form.document_type} onChange={(event) => updateField("document_type", event.target.value)} disabled={isApproved}>
            <option value="incoming_invoice">Eingangsrechnung</option>
            <option value="credit_note">Gutschrift</option>
          </select>
        </FormField>
        <FormField label="Kostenart">
          <select value={form.cost_category} onChange={(event) => updateField("cost_category", event.target.value)} disabled={isApproved}>
            <option value="">-</option>
            {COST_CATEGORY_OPTIONS.map(([category, label]) => (
              <option key={category} value={category}>{label}</option>
            ))}
          </select>
        </FormField>
        <FormField label={tenantProfile.assignment_code_label}>
          <input placeholder="z.B. Wewe20" value={form.assignment_code} onChange={(event) => updateField("assignment_code", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Zuordnungsart">
          <select value={form.assignment_kind} onChange={(event) => updateField("assignment_kind", event.target.value)} disabled={isApproved}>
            <option value="">-</option>
            <AssignmentKindOptions />
          </select>
        </FormField>
        <FormField label="Netto">
          <input inputMode="decimal" value={form.net_amount} onChange={(event) => updateField("net_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="USt">
          <input inputMode="decimal" value={form.tax_amount} onChange={(event) => updateField("tax_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Brutto">
          <input inputMode="decimal" value={form.gross_amount} onChange={(event) => updateField("gross_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Währung">
          <input value={form.currency} onChange={(event) => updateField("currency", event.target.value.toUpperCase())} maxLength={3} disabled={isApproved} />
        </FormField>
        <FormField label="Zahlbar bis">
          <input type="date" value={form.due_date} onChange={(event) => updateField("due_date", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Skonto bis">
          <input type="date" value={form.discount_due_date} onChange={(event) => updateField("discount_due_date", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Skonto-Basis">
          <input inputMode="decimal" value={form.discount_base} onChange={(event) => updateField("discount_base", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Skonto">
          <input inputMode="decimal" value={form.discount_amount} onChange={(event) => updateField("discount_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Zahlbetrag Skonto">
          <input inputMode="decimal" value={form.discounted_payable_amount} onChange={(event) => updateField("discounted_payable_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Artikel / Leistung">
          <input value={form.item_summary} onChange={(event) => updateField("item_summary", event.target.value)} disabled={isApproved} />
        </FormField>
      </div>
      <div className="form-actions">
        <button type="submit" disabled={isSaving || isApproved}>
          {isApproved ? "Freigegeben" : isSaving ? "Speichert..." : "Speichern"}
        </button>
      </div>
    </form>
  );
}

function AssignmentKindOptions() {
  return (
    <>
      <option value="construction_project">Bauvorhaben</option>
      <option value="location">Standort</option>
      <option value="construction_or_dropoff_site">Bauvorhaben / Stellplatz</option>
      <option value="cost_object">Kostenobjekt</option>
      <option value="vehicle">Fahrzeug</option>
      <option value="subscription">Abo/Vertrag</option>
      <option value="department">Bereich</option>
    </>
  );
}

function DocumentPreview({ document }) {
  const fileUrl = apiUrl(`/documents/${document.id}/file?disposition=inline`);
  const contentType = document.content_type || "";
  const isImage = contentType.startsWith("image/");
  const isPdf = contentType === "application/pdf";
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState(isPdf ? null : 1);
  const [previewError, setPreviewError] = useState("");
  const [previewMode, setPreviewMode] = useState("pan");
  const [pageText, setPageText] = useState(null);
  const [pageTextTruncated, setPageTextTruncated] = useState(false);
  const [textError, setTextError] = useState("");
  const [copyNotice, setCopyNotice] = useState("");
  const previewUrl = isPdf ? apiUrl(`/documents/${document.id}/preview/pages/${pageNumber}`) : fileUrl;
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef(null);

  useEffect(() => {
    setPageNumber(1);
    setPan({ x: 0, y: 0 });
    setScale(1);
    setPreviewMode("pan");
    setPageText(null);
    setPageTextTruncated(false);
    setTextError("");
    setCopyNotice("");
    setIsDragging(false);
    dragRef.current = null;
  }, [document.id, isPdf]);

  useEffect(() => {
    if (!isPdf) {
      setPageCount(1);
      setPreviewError("");
      return undefined;
    }

    const controller = new AbortController();
    setPageCount(null);
    setPreviewError("");
    fetch(apiUrl(`/documents/${document.id}/preview`), {
      credentials: "include",
      signal: controller.signal,
    })
      .then(async (response) => {
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(formatApiError(result.detail, `Vorschau konnte nicht geladen werden: ${response.status}`));
        }
        setPageCount(Math.max(Number(result.page_count) || 1, 1));
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setPreviewError(error.message || "Vorschau konnte nicht geladen werden.");
          setPageCount(1);
        }
      });

    return () => controller.abort();
  }, [document.id, isPdf]);

  useEffect(() => {
    if (!isPdf || previewMode !== "text") return undefined;

    const controller = new AbortController();
    setPageText(null);
    setPageTextTruncated(false);
    setTextError("");
    setCopyNotice("");
    fetch(apiUrl(`/documents/${document.id}/preview/pages/${pageNumber}/text`), {
      credentials: "include",
      signal: controller.signal,
    })
      .then(async (response) => {
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(formatApiError(result.detail, `PDF-Text konnte nicht geladen werden: ${response.status}`));
        }
        setPageText(result.text ?? "");
        setPageTextTruncated(Boolean(result.truncated));
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setTextError(error.message || "PDF-Text konnte nicht geladen werden.");
        }
      });

    return () => controller.abort();
  }, [document.id, isPdf, pageNumber, previewMode]);

  function startDrag(event) {
    if ((!isImage && !isPdf) || previewMode !== "pan") return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      panX: pan.x,
      panY: pan.y,
    };
    setIsDragging(true);
  }

  function moveDrag(event) {
    if (!dragRef.current) return;
    event.preventDefault();
    setPan({
      x: dragRef.current.panX + event.clientX - dragRef.current.startX,
      y: dragRef.current.panY + event.clientY - dragRef.current.startY,
    });
  }

  function endDrag(event) {
    if (!dragRef.current) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragRef.current = null;
    setIsDragging(false);
  }

  function changeScale(delta) {
    setScale((current) => Math.min(2.4, Math.max(0.85, Number((current + delta).toFixed(2)))));
  }

  function resetView() {
    setPan({ x: 0, y: 0 });
    setScale(1);
  }

  function changePage(delta) {
    setPageNumber((current) => {
      const maxPage = pageCount || current;
      const nextPage = Math.min(maxPage, Math.max(1, current + delta));
      return nextPage;
    });
    resetView();
  }

  function moveWithKeyboard(event) {
    if ((!isImage && !isPdf) || previewMode !== "pan") return;

    const step = event.shiftKey ? 48 : 18;
    const keyMap = {
      ArrowLeft: { x: -step, y: 0 },
      ArrowRight: { x: step, y: 0 },
      ArrowUp: { x: 0, y: -step },
      ArrowDown: { x: 0, y: step },
    };

    if (keyMap[event.key]) {
      event.preventDefault();
      setPan((current) => ({
        x: current.x + keyMap[event.key].x,
        y: current.y + keyMap[event.key].y,
      }));
      return;
    }

    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      changeScale(0.15);
      return;
    }

    if (event.key === "-") {
      event.preventDefault();
      changeScale(-0.15);
      return;
    }

    if (event.key === "0" || event.key === "Home") {
      event.preventDefault();
      resetView();
    }
  }

  async function copyPageText() {
    if (!pageText) return;
    try {
      await navigator.clipboard.writeText(pageText);
      setCopyNotice("Text kopiert.");
    } catch {
      setCopyNotice("Text kann markiert und mit Strg+C kopiert werden.");
    }
  }

  return (
    <aside className="document-preview" aria-label="Belegvorschau">
      <div className="document-preview-header">
        <div>
          <span>Belegvorschau</span>
          <strong>{document.original_filename}</strong>
        </div>
        <button
          className="secondary-button"
          type="button"
          onClick={() => window.open(fileUrl, "_blank", "noopener")}
        >
          Öffnen
        </button>
      </div>
      {(isImage || isPdf) ? (
        <div className="document-preview-tools" aria-label="Vorschau steuern">
          {isPdf ? (
            <div className="document-preview-mode" aria-label="Vorschaumodus">
              <button className={previewMode === "pan" ? "" : "secondary-button"} type="button" onClick={() => setPreviewMode("pan")}>Hand</button>
              <button className={previewMode === "text" ? "" : "secondary-button"} type="button" onClick={() => setPreviewMode("text")}>Text</button>
            </div>
          ) : null}
          <button className="secondary-button" type="button" onClick={() => changeScale(-0.15)} aria-label="Vorschau verkleinern">-</button>
          <span>{Math.round(scale * 100)}%</span>
          <button className="secondary-button" type="button" onClick={() => changeScale(0.15)} aria-label="Vorschau vergrößern">+</button>
          <button className="secondary-button" type="button" onClick={resetView}>Reset</button>
          {isPdf ? (
            <>
              <button className="secondary-button" type="button" onClick={() => changePage(-1)} disabled={pageNumber <= 1} aria-label="Vorherige Seite">‹</button>
              <span>{pageNumber} / {pageCount || "..."}</span>
              <button className="secondary-button" type="button" onClick={copyPageText} disabled={previewMode !== "text" || !pageText}>Text kopieren</button>
              <button className="secondary-button" type="button" onClick={() => changePage(1)} disabled={pageCount ? pageNumber >= pageCount : true} aria-label="Nächste Seite">›</button>
            </>
          ) : null}
        </div>
      ) : null}
      <div
        className={`document-preview-frame ${(isImage || isPdf) && previewMode === "pan" ? "is-draggable" : ""} ${previewMode === "text" ? "is-text-mode" : ""} ${isDragging ? "is-dragging" : ""}`}
        role={isImage || isPdf ? "region" : undefined}
        aria-label={isImage || isPdf ? "Belegvorschau. Im Hand-Modus verschieben Pfeiltasten die Ansicht, Plus und Minus zoomen, 0 setzt zurück. Im Text-Modus kann Text markiert und kopiert werden." : undefined}
        tabIndex={isImage || isPdf ? 0 : undefined}
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={moveWithKeyboard}
      >
        {isImage ? (
          <div
            className="document-preview-pan"
            style={{ "--preview-x": `${pan.x}px`, "--preview-y": `${pan.y}px`, "--preview-scale": scale }}
          >
            <img src={previewUrl} alt={`Vorschau ${document.original_filename}`} draggable="false" />
          </div>
        ) : isPdf ? (
          previewError ? (
            <div className="document-preview-empty">
              <strong>Vorschau nicht verfügbar</strong>
              <span>{previewError}</span>
            </div>
          ) : previewMode === "text" ? (
            <div className="document-preview-text">
              {textError ? (
                <div className="document-preview-empty">
                  <strong>Text nicht verfügbar</strong>
                  <span>{textError}</span>
                </div>
              ) : pageText ? (
                <>
                  <pre>{pageText}</pre>
                  {pageTextTruncated ? <span className="document-preview-copy-note">Text gekürzt. Komplette PDF über „Öffnen“ ansehen.</span> : null}
                  {copyNotice ? <span className="document-preview-copy-note">{copyNotice}</span> : null}
                </>
              ) : pageText === "" ? (
                <div className="document-preview-empty">
                  <strong>Kein Text gefunden</strong>
                  <span>Diese Seite ist vermutlich gescannt oder enthält nur Bildinhalt.</span>
                </div>
              ) : (
                <div className="document-preview-empty">
                  <strong>Text wird geladen</strong>
                  <span>Die PDF-Seite wird als markierbarer Text vorbereitet.</span>
                </div>
              )}
            </div>
          ) : (
            <div
              className="document-preview-pan"
              style={{ "--preview-x": `${pan.x}px`, "--preview-y": `${pan.y}px`, "--preview-scale": scale }}
            >
              <img src={previewUrl} alt={`PDF-Seite ${pageNumber} von ${pageCount || "?"}`} draggable="false" />
            </div>
          )
        ) : (
          <div className="document-preview-empty">
            <strong>Keine direkte Vorschau</strong>
            <span>Dieses Dateiformat wird nicht eingebettet angezeigt.</span>
          </div>
        )}
      </div>
    </aside>
  );
}

function ReviewFocusDialog({
  document,
  tenantProfile,
  isSavingExtraction,
  isSavingPayment,
  isSavingSuggestion,
  hasPrevious,
  hasNext,
  positionLabel,
  savingPaymentIds,
  savingSuggestionIds,
  onClose,
  onPrevious,
  onNext,
  onSaveExtraction,
  onSelectPayment,
  onSaveSuggestion,
}) {
  const dialogRef = useRef(null);
  const [hasUnsavedExtractionChanges, setHasUnsavedExtractionChanges] = useState(false);
  const [navigationWarning, setNavigationWarning] = useState("");
  const isBusy = isSavingExtraction || isSavingPayment || isSavingSuggestion;

  useEffect(() => {
    setHasUnsavedExtractionChanges(false);
    setNavigationWarning("");
  }, [document?.id]);

  function canLeaveCurrentDocument() {
    if (!hasUnsavedExtractionChanges) return true;
    setNavigationWarning("Bitte erst speichern oder die Änderung zurücksetzen, bevor du den Beleg wechselst.");
    return false;
  }

  function requestClose() {
    if (hasUnsavedExtractionChanges) {
      const confirmed = window.confirm("Ungespeicherte Änderungen verwerfen und Prüfung schließen?");
      if (!confirmed) return;
    }
    onClose();
  }

  function requestPrevious() {
    if (!canLeaveCurrentDocument()) return;
    onPrevious();
  }

  function requestNext() {
    if (!canLeaveCurrentDocument()) return;
    onNext();
  }

  useEffect(() => {
    if (!document) return undefined;

    const previousActiveElement = window.document.activeElement;
    dialogRef.current?.focus();

    return () => {
      previousActiveElement?.focus?.();
    };
  }, [document?.id]);

  useEffect(() => {
    if (!document) return undefined;

    function handleDialogKeydown(event) {
      if (event.key === "Escape" && !isBusy) {
        event.preventDefault();
        requestClose();
        return;
      }

      if (event.altKey && event.key === "ArrowLeft" && !isBusy && hasPrevious) {
        event.preventDefault();
        requestPrevious();
        return;
      }

      if (event.altKey && event.key === "ArrowRight" && !isBusy && hasNext) {
        event.preventDefault();
        requestNext();
        return;
      }

      if (event.key !== "Tab") return;

      const focusableSelector = [
        "button:not([disabled])",
        "[href]",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])",
      ].join(",");
      const focusableElements = Array.from(dialogRef.current?.querySelectorAll(focusableSelector) || []);
      if (!focusableElements.length) return;

      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && window.document.activeElement === firstFocusable) {
        event.preventDefault();
        lastFocusable.focus();
      } else if (!event.shiftKey && window.document.activeElement === lastFocusable) {
        event.preventDefault();
        firstFocusable.focus();
      }
    }

    const dialog = dialogRef.current;
    dialog?.addEventListener("keydown", handleDialogKeydown);
    return () => dialog?.removeEventListener("keydown", handleDialogKeydown);
  }, [document?.id, hasNext, hasPrevious, isBusy, requestNext, requestPrevious]);

  if (!document?.extraction) return null;

  return (
    <div className="modal-backdrop review-focus-backdrop" role="presentation">
      <section className="review-focus-dialog" role="dialog" aria-modal="true" aria-labelledby="review-focus-title" ref={dialogRef} tabIndex={-1}>
        <header className="review-focus-header">
          <div>
            <p className="eyebrow">Prüfung</p>
            <h2 id="review-focus-title">Beleg groß prüfen</h2>
            <span>{document.original_filename}</span>
          </div>
          <div className="review-focus-actions">
            <button className="secondary-button" type="button" onClick={requestPrevious} disabled={isBusy || !hasPrevious}>
              Zurück
            </button>
            {positionLabel ? <span>{positionLabel}</span> : null}
            <button className="secondary-button" type="button" onClick={requestNext} disabled={isBusy || !hasNext}>
              Nächster
            </button>
            <button className="secondary-button review-focus-close" type="button" onClick={requestClose} disabled={isBusy}>
              Schließen
            </button>
          </div>
        </header>
        {navigationWarning ? <p className="inline-note review-focus-warning">{navigationWarning}</p> : null}

        <div className="review-focus-body">
          <DocumentPreview document={document} />
          <div className="review-focus-data">
            <ExtractionEditForm
              document={document}
              tenantProfile={tenantProfile}
              isSaving={isSavingExtraction}
              onDirtyChange={(isDirty) => {
                setHasUnsavedExtractionChanges(isDirty);
                if (!isDirty) setNavigationWarning("");
              }}
              onSave={onSaveExtraction}
            />
            {document.extraction?.warnings?.length ? (
              <ul className="warnings">
                {document.extraction.warnings.map((warning, index) => (
                  <li key={`${warning}-${index}`}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>

        <div className="review-focus-below">
          <AllocationLines lines={document.extraction.raw_result?.allocation_lines} tenantProfile={tenantProfile} />
          <PaymentTerms
            document={document}
            rawResult={document.extraction.raw_result}
            onSelect={onSelectPayment}
            isSaving={savingPaymentIds.includes(document.id)}
          />
          <BookingSuggestions
            document={document}
            suggestions={document.booking_suggestions}
            tenantProfile={tenantProfile}
            onSave={onSaveSuggestion}
            savingIds={savingSuggestionIds}
          />
        </div>
      </section>
    </div>
  );
}

function ApprovalDialog({
  document,
  tenantProfile,
  isApproving,
  isValidating,
  error,
  issues,
  canPrepareAccountingRule,
  onCancel,
  onConfirm,
  onPrepareAccountingRule,
}) {
  const dialogRef = useRef(null);

  useEffect(() => {
    if (!document) return undefined;

    const dialog = dialogRef.current;
    const focusableSelector = [
      "button:not([disabled])",
      "[href]",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const focusableElements = Array.from(dialog?.querySelectorAll(focusableSelector) || []);
    const firstElement = focusableElements[0];
    const previousActiveElement = window.document.activeElement;
    firstElement?.focus();

    function trapFocus(event) {
      if (event.key !== "Tab" || focusableElements.length === 0) return;

      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && window.document.activeElement === firstFocusable) {
        event.preventDefault();
        lastFocusable.focus();
      } else if (!event.shiftKey && window.document.activeElement === lastFocusable) {
        event.preventDefault();
        firstFocusable.focus();
      }
    }

    dialog?.addEventListener("keydown", trapFocus);
    return () => {
      dialog?.removeEventListener("keydown", trapFocus);
      previousActiveElement?.focus?.();
    };
  }, [document]);

  if (!document) return null;

  const extraction = document.extraction || {};
  const rawResult = extraction.raw_result || {};
  const suggestions = document.booking_suggestions || [];
  const payment = approvalPaymentSummary(document);
  const paymentTerms = paymentTermLinesForDocument(document);
  const requiresPaymentDecision = paymentTerms.length > 1 && !document.payment_decision;
  const accountingRuleIssues = (issues || []).filter((issue) =>
    ["missing_accounting_rule", "incomplete_accounting_rule", "missing_discount_account"].includes(issue.code),
  );
  const exportValidationIssues = (issues || []).filter((issue) => issue.code === "export_validation");
  const missingAccountingRuleIssues = accountingRuleIssues.filter((issue) => issue.code === "missing_accounting_rule");
  const editableAccountingRuleIssues = accountingRuleIssues.filter((issue) => issue.code !== "missing_accounting_rule");
  const showGenericApprovalError = Boolean(error) && !accountingRuleIssues.length && !exportValidationIssues.length;
  const totalNet = suggestions.reduce((sum, suggestion) => sum + numberOrZero(suggestion.net_amount), 0);
  const totalTax = suggestions.reduce((sum, suggestion) => sum + numberOrZero(suggestion.tax_amount), 0);
  const totalGross = suggestions.reduce((sum, suggestion) => sum + numberOrZero(suggestion.gross_amount), 0);

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title" ref={dialogRef}>
        <div className="approval-header">
          <div>
            <p className="eyebrow">Finale Freigabe</p>
            <h2 id="approval-title">Beleg wirklich freigeben?</h2>
          </div>
          <button className="secondary-button" type="button" onClick={onCancel} disabled={isApproving}>
            Schließen
          </button>
        </div>

        <p className="approval-note">
          Nach der Freigabe werden die gespeicherten Buchungszeilen gesperrt. Ungespeicherte Änderungen in der Tabelle sind nicht enthalten.
        </p>

        {requiresPaymentDecision ? (
          <p className="approval-blocker">
            Zahlungsentscheidung fehlt: Bitte zuerst Skonto, ohne Abzug oder Gutschrift-Verrechnung wählen.
          </p>
        ) : null}
        {isValidating ? <p className="approval-note">Freigabeprüfung läuft. Bitte kurz warten.</p> : null}
        {showGenericApprovalError ? <p className="approval-blocker">{error}</p> : null}

        {accountingRuleIssues.length ? (
          <div className="approval-fix-panel">
            <div>
              <strong>{accountingRuleFixTitle(accountingRuleIssues)}</strong>
              <span>
                {canPrepareAccountingRule
                  ? missingAccountingRuleIssues.length
                    ? "Die App kann die passende Regel vorbereiten. Konten müssen danach fachlich ergänzt werden."
                    : "Die bestehende Regel muss unter Stammdaten bearbeitet werden."
                  : "Bitte einen Admin bitten, die passende Regel unter Stammdaten anzulegen."}
              </span>
            </div>
            {canPrepareAccountingRule ? (
              <div className="approval-fix-actions">
                {dedupeAccountingRuleIssues(missingAccountingRuleIssues).map((issue) => (
                  <button
                    className="secondary-button"
                    type="button"
                    key={`${issue.supplier_name || "-"}-${issue.cost_category || ""}-${issue.code}`}
                    onClick={() => onPrepareAccountingRule(issue)}
                    disabled={issue.field === "cost_category" && !issue.cost_category}
                  >
                    {issue.cost_category_label || formatCostCategory(issue.cost_category)} / {issue.supplier_name || "ohne Lieferant"}
                  </button>
                ))}
                {dedupeAccountingRuleIssues(editableAccountingRuleIssues).map((issue) => (
                  <button
                    className="secondary-button"
                    type="button"
                    key={`${issue.accounting_rule_id || issue.accounting_rule_name || "-"}-${issue.code}`}
                    onClick={() => onPrepareAccountingRule(issue)}
                  >
                    {issue.accounting_rule_name || issue.suggested_name || "Regel bearbeiten"}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {exportValidationIssues.length ? (
          <div className="approval-export-panel">
            <div>
              <strong>Exportprüfung blockiert die Freigabe</strong>
              <span>Diese Fehler würden sonst im Buchungsentwurf landen. Bitte erst korrigieren, dann erneut freigeben.</span>
            </div>
            <ul>
              {exportValidationIssues.map((issue, index) => (
                <li key={`${issue.row_index || index}-${issue.row_type || "export"}`}>
                  <span>
                    {[issue.line_no ? `Zeile ${issue.line_no}` : null, issue.row_type_label || formatExportRowType(issue.row_type)]
                      .filter(Boolean)
                      .join(" · ") || "Exportzeile"}
                  </span>
                  <small>{(issue.export_errors || []).join(", ") || issue.message}</small>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="approval-facts">
          <Field label="Datei" value={document.original_filename} />
          <Field label="Lieferant" value={extraction.supplier_name} />
          <Field label="Rechnung" value={extraction.invoice_number} />
          <Field label="Datum" value={formatDate(extraction.invoice_date)} />
          <Field label="Belegart" value={formatDocumentType(rawResult.document_type)} />
          <Field label="Kunden-Nr." value={rawResult.customer_number} />
          <Field label="Brutto" value={formatMoney(extraction.gross_amount)} />
          <Field label="Zuordnung" value={formatAssignment(rawResult, tenantProfile)} />
          <Field label={tenantProfile.assignment_code_label} value={<ProjectSummary rawResult={rawResult} tenantProfile={tenantProfile} />} />
          <Field label="Zahlung" value={payment.label} />
          <Field label="Fällig" value={formatDate(payment.due_date)} />
          <Field label="Zahlbetrag" value={formatMoney(payment.amount)} />
        </div>

        {extraction.warnings?.length ? (
          <ul className="warnings approval-warnings">
            {extraction.warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        ) : null}

        <div className="approval-lines">
          <div className="approval-lines-head">
            <h3>Buchungszeilen</h3>
            <StatusPill value={`${suggestions.length} Zeilen`} />
          </div>
          <div className="approval-line-table">
            <div className="approval-line-row approval-line-head">
              <span>Nr.</span>
              <span>Beschreibung</span>
              <span>{tenantProfile.assignment_code_label}</span>
              <span>Kostenart</span>
              <span>Netto</span>
              <span>USt</span>
              <span>Brutto</span>
            </div>
            {suggestions.map((suggestion) => (
              <div className="approval-line-row" key={suggestion.id}>
                <strong>{suggestion.line_no}</strong>
                <span>{suggestion.description || "-"}</span>
                <span>{[suggestion.assignment_code, formatAssignmentKind(suggestion.assignment_kind, tenantProfile)].filter(Boolean).join(" / ") || "-"}</span>
                <span>{formatCostCategory(suggestion.cost_category)}</span>
                <span>{formatMoney(suggestion.net_amount)}</span>
                <span>{formatMoney(suggestion.tax_amount)}</span>
                <span>{formatMoney(suggestion.gross_amount)}</span>
              </div>
            ))}
            <div className="approval-line-row approval-line-total">
              <span>Summe</span>
              <span></span>
              <span></span>
              <span></span>
              <strong>{formatMoney(totalNet)}</strong>
              <strong>{formatMoney(totalTax)}</strong>
              <strong>{formatMoney(totalGross)}</strong>
            </div>
          </div>
        </div>

        <div className="approval-actions">
          <button className="secondary-button" type="button" onClick={onCancel} disabled={isApproving}>
            Abbrechen
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isApproving || isValidating || document.status !== "review_ready" || requiresPaymentDecision || Boolean(error) || (issues || []).length > 0}
          >
            {isApproving ? "Gibt frei..." : isValidating ? "Prüft..." : "Final freigeben"}
          </button>
        </div>
      </section>
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
              aria-label={`Mandanten für ${account.email}`}
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

function MasterdataAdmin({
  apiFetch,
  tenantId,
  tenantProfile,
  accountingRuleDraft,
  accountingRuleEditTarget,
  onAccountingRuleDraftConsumed,
  onAccountingRuleEditTargetConsumed,
  onProfileSaved,
}) {
  const [assignmentUnits, setAssignmentUnits] = useState([]);
  const [supplierRules, setSupplierRules] = useState([]);
  const [accountingRules, setAccountingRules] = useState([]);
  const [assignmentEditId, setAssignmentEditId] = useState(null);
  const [assignmentEditForm, setAssignmentEditForm] = useState(null);
  const [supplierEditId, setSupplierEditId] = useState(null);
  const [supplierEditForm, setSupplierEditForm] = useState(null);
  const [accountingEditId, setAccountingEditId] = useState(null);
  const [accountingEditForm, setAccountingEditForm] = useState(null);
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
    default_cost_category: ["material"],
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
  const accountingSectionRef = useRef(null);
  const savedAccountingFramework = accountingFramework(tenantProfile.accounting_framework);
  const profileAccountingFramework = accountingFramework(profileForm.accounting_framework);
  const hasUnsavedAccountingFramework = profileAccountingFramework !== savedAccountingFramework;
  const activeAccountingFramework = savedAccountingFramework;
  const debitSuggestions = accountSuggestions(activeAccountingFramework, "debit", accountingForm.cost_category);
  const creditSuggestions = accountSuggestions(activeAccountingFramework, "credit", accountingForm.cost_category);
  const discountSuggestions = accountSuggestions(activeAccountingFramework, "discount", accountingForm.cost_category);
  const editDebitSuggestions = accountSuggestions(activeAccountingFramework, "debit", accountingEditForm?.cost_category);
  const editCreditSuggestions = accountSuggestions(activeAccountingFramework, "credit", accountingEditForm?.cost_category);
  const editDiscountSuggestions = accountSuggestions(activeAccountingFramework, "discount", accountingEditForm?.cost_category);

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

  useEffect(() => {
    if (!accountingRuleDraft?.form) return;
    setAccountingForm((current) => ({
      ...current,
      ...accountingRuleDraft.form,
    }));
    setMessage("Kontierungsregel vorbereitet. Bitte Aufwandskonto und Gegenkonto ergänzen und speichern.");
    window.setTimeout(() => {
      accountingSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      accountingSectionRef.current?.querySelector("input")?.focus();
    }, 0);
    onAccountingRuleDraftConsumed?.();
  }, [accountingRuleDraft, onAccountingRuleDraftConsumed]);

  useEffect(() => {
    if (!accountingRuleEditTarget || !accountingRules.length) return;
    const rule = findAccountingRuleForTarget(accountingRules, accountingRuleEditTarget);
    if (!rule) {
      setMessage("Kontierungsregel konnte nicht automatisch gefunden werden. Bitte manuell in den Stammdaten prüfen.");
      onAccountingRuleEditTargetConsumed?.();
      return;
    }

    startAccountingEdit(rule);
    setMessage("Kontierungsregel geöffnet. Bitte fehlende Konten ergänzen und speichern.");
    window.setTimeout(() => {
      accountingSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      const focusSelector = accountingRuleEditTarget.focus_field === "discount_account"
        ? 'input[aria-label="Skontokonto"]'
        : 'input[aria-label="Aufwandskonto"]';
      const row = accountingSectionRef.current?.querySelector(`[data-accounting-rule-id="${rule.id}"]`);
      row?.querySelector(focusSelector)?.focus();
    }, 0);
    onAccountingRuleEditTargetConsumed?.();
  }, [accountingRuleEditTarget, accountingRules, onAccountingRuleEditTargetConsumed]);

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
        code: assignment.code,
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
    setMessage("Zuordnung aktualisiert.");
  }

  function startAssignmentEdit(assignment) {
    setAssignmentEditId(assignment.id);
    setAssignmentEditForm({
      code: assignment.code || "",
      label: assignment.label || "",
      kind: assignment.kind || tenantProfile.default_assignment_kind || "cost_object",
      project_number: assignment.project_number || "",
      revenue_relevant: assignment.revenue_relevant,
      aliases: (assignment.aliases || []).join(", "),
      is_active: assignment.is_active,
    });
  }

  function cancelAssignmentEdit() {
    setAssignmentEditId(null);
    setAssignmentEditForm(null);
  }

  async function saveAssignmentEdit(assignment) {
    if (!assignmentEditForm) return;
    if (!assignmentEditForm.code.trim() || !assignmentEditForm.label.trim()) {
      setMessage(`${tenantProfile.assignment_label_singular} braucht Code und Name.`);
      return;
    }
    const response = await apiFetch(`/masterdata/assignment-units/${assignment.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull({
        ...assignmentEditForm,
        aliases: splitAliases(assignmentEditForm.aliases),
      })),
    });
    if (!response.ok) {
      setMessage(`Zuordnung konnte nicht gespeichert werden: ${response.status}`);
      return;
    }
    cancelAssignmentEdit();
    await loadMasterdata();
    setMessage("Zuordnung gespeichert.");
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
    setSupplierForm({ match_text: "", supplier_name: "", customer_number: "", default_cost_category: ["material"], default_assignment_code: "" });
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
        default_cost_category: supplierCostCategories(rule),
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
    setMessage("Lieferantenregel aktualisiert.");
  }

  function startSupplierEdit(rule) {
    setSupplierEditId(rule.id);
    setSupplierEditForm({
      match_text: rule.match_text || "",
      supplier_name: rule.supplier_name || "",
      customer_number: rule.customer_number || "",
      default_cost_category: supplierCostCategories(rule),
      default_assignment_code: rule.default_assignment_code || "",
      is_active: rule.is_active,
    });
  }

  function cancelSupplierEdit() {
    setSupplierEditId(null);
    setSupplierEditForm(null);
  }

  async function saveSupplierEdit(rule) {
    if (!supplierEditForm) return;
    if (!supplierEditForm.match_text.trim() || !supplierEditForm.supplier_name.trim()) {
      setMessage("Lieferantenregel braucht Erkennungstext und Lieferant.");
      return;
    }
    const response = await apiFetch(`/masterdata/supplier-rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(supplierEditForm)),
    });
    if (!response.ok) {
      setMessage(`Lieferantenregel konnte nicht gespeichert werden: ${response.status}`);
      return;
    }
    cancelSupplierEdit();
    await loadMasterdata();
    setMessage("Lieferantenregel gespeichert.");
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
    setMessage("Kontierungsregel aktualisiert.");
  }

  function startAccountingEdit(rule) {
    setAccountingEditId(rule.id);
    setAccountingEditForm({
      name: rule.name || "",
      supplier_match_text: rule.supplier_match_text || "",
      cost_category: rule.cost_category || "",
      debit_account: rule.debit_account || "",
      credit_account: rule.credit_account || "",
      tax_key: rule.tax_key || "",
      tax_rate: rule.tax_rate || "",
      discount_account: rule.discount_account || "",
      is_active: rule.is_active,
    });
  }

  function cancelAccountingEdit() {
    setAccountingEditId(null);
    setAccountingEditForm(null);
  }

  async function saveAccountingEdit(rule) {
    if (!accountingEditForm) return;
    if (!accountingEditForm.name.trim() || !accountingEditForm.debit_account.trim() || !accountingEditForm.credit_account.trim()) {
      setMessage("Kontierungsregel braucht Name, Aufwandskonto und Gegenkonto.");
      return;
    }
    const response = await apiFetch(`/masterdata/accounting-rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(accountingEditForm)),
    });
    if (!response.ok) {
      setMessage(`Kontierungsregel konnte nicht gespeichert werden: ${response.status}`);
      return;
    }
    cancelAccountingEdit();
    await loadMasterdata();
    setMessage("Kontierungsregel gespeichert.");
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
                  setProfileForm({
                    ...profileForm,
                    ...nextTemplate,
                    display_name: profileForm.display_name || tenantId,
                    accounting_framework: profileForm.accounting_framework || nextTemplate.accounting_framework,
                  });
                }}
              >
                <option value="construction">Baubranche</option>
                <option value="fitness_studio">Sportstudio</option>
                <option value="container_transport">Container/Transport</option>
                <option value="general">Allgemein</option>
              </select>
            </FormField>
            <FormField label="Kontenrahmen">
              <select
                value={profileAccountingFramework}
                onChange={(event) => setProfileForm({ ...profileForm, accounting_framework: event.target.value })}
              >
                <option value="SKR03">SKR03</option>
                <option value="SKR04">SKR04</option>
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
              <span>Aliase</span>
              <span>Status</span>
              <span>Aktiv</span>
              <span>Aktion</span>
            </div>
            {assignmentUnits.map((assignment) => {
              const isEditing = assignmentEditId === assignment.id && assignmentEditForm;
              return (
                <div className={isEditing ? "data-row editing-row" : "data-row"} key={assignment.id}>
                  {isEditing ? (
                    <>
                      <input
                        aria-label="Code"
                        value={assignmentEditForm.code}
                        onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, code: event.target.value })}
                        required
                      />
                      <input
                        aria-label="Projektnummer"
                        placeholder={usesProjectNumber(assignmentEditForm.kind) ? "z.B. 25-00008" : "optional"}
                        value={assignmentEditForm.project_number}
                        onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, project_number: event.target.value })}
                      />
                      <input
                        aria-label="Name"
                        value={assignmentEditForm.label}
                        onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, label: event.target.value })}
                        required
                      />
                      <select
                        aria-label="Art"
                        value={assignmentEditForm.kind}
                        onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, kind: event.target.value })}
                      >
                        <option value="construction_project">Bauvorhaben</option>
                        <option value="location">Standort</option>
                        <option value="construction_or_dropoff_site">Bauvorhaben / Stellplatz</option>
                        <option value="cost_object">Kostenobjekt</option>
                        <option value="vehicle">Fahrzeug</option>
                        <option value="subscription">Abo/Vertrag</option>
                        <option value="department">Bereich</option>
                      </select>
                      <input
                        aria-label="Aliase"
                        placeholder="kommagetrennt"
                        value={assignmentEditForm.aliases}
                        onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, aliases: event.target.value })}
                      />
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={assignmentEditForm.revenue_relevant}
                          onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, revenue_relevant: event.target.checked })}
                        />
                        <span>{assignmentEditForm.revenue_relevant ? "umsatzrelevant" : "intern"}</span>
                      </label>
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={assignmentEditForm.is_active}
                          onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, is_active: event.target.checked })}
                        />
                        <span>{assignmentEditForm.is_active ? "aktiv" : "inaktiv"}</span>
                      </label>
                      <div className="row-actions">
                        <button type="button" onClick={() => saveAssignmentEdit(assignment)}>Speichern</button>
                        <button className="secondary-button" type="button" onClick={cancelAssignmentEdit}>Abbrechen</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <strong>{formatAssignmentCode(assignment.code, assignment.kind, tenantProfile)}</strong>
                      <span>{usesProjectNumber(assignment.kind) ? assignment.project_number || "-" : "-"}</span>
                      <span>{assignment.label}</span>
                      <span>{formatAssignmentKind(assignment.kind, tenantProfile)}</span>
                      <span>{assignment.aliases?.length ? assignment.aliases.join(", ") : "-"}</span>
                      <StatusPill value={assignment.revenue_relevant ? "umsatzrelevant" : "intern"} tone={assignment.revenue_relevant ? "green" : "gray"} />
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={assignment.is_active}
                          onChange={(event) => updateAssignment(assignment, { is_active: event.target.checked })}
                        />
                        <span>{assignment.is_active ? "aktiv" : "inaktiv"}</span>
                      </label>
                      <button className="secondary-button" type="button" onClick={() => startAssignmentEdit(assignment)}>
                        Bearbeiten
                      </button>
                    </>
                  )}
                </div>
              );
            })}
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
              <CategoryChecklist
                value={supplierForm.default_cost_category}
                onChange={(categories) => setSupplierForm({ ...supplierForm, default_cost_category: categories })}
              />
            </FormField>
            <FormField label={tenantProfile.assignment_code_label}>
              <input list="assignment-code-options" placeholder="optional" value={supplierForm.default_assignment_code} onChange={(event) => setSupplierForm({ ...supplierForm, default_assignment_code: event.target.value })} />
            </FormField>
            <button type="submit">Regel anlegen</button>
          </form>
          <datalist id="assignment-code-options">
            {assignmentUnits.map((assignment) => (
              <option key={assignment.id} value={assignment.code}>
                {assignment.label}
              </option>
            ))}
          </datalist>
          <div className="data-table supplier-table">
            <div className="data-row data-head">
              <span>Lieferant</span>
              <span>Erkennung</span>
              <span>Kunden-Nr.</span>
              <span>Kostenart</span>
              <span>{tenantProfile.assignment_code_label}</span>
              <span>Aktiv</span>
              <span>Aktion</span>
            </div>
            {supplierRules.map((rule) => {
              const isEditing = supplierEditId === rule.id && supplierEditForm;
              return (
                <div className={isEditing ? "data-row editing-row" : "data-row"} key={rule.id}>
                  {isEditing ? (
                    <>
                      <input
                        aria-label="Lieferant"
                        value={supplierEditForm.supplier_name}
                        onChange={(event) => setSupplierEditForm({ ...supplierEditForm, supplier_name: event.target.value })}
                        required
                      />
                      <input
                        aria-label="Erkennungstext"
                        value={supplierEditForm.match_text}
                        onChange={(event) => setSupplierEditForm({ ...supplierEditForm, match_text: event.target.value })}
                        required
                      />
                      <input
                        aria-label="Unsere Kunden-Nr."
                        value={supplierEditForm.customer_number}
                        onChange={(event) => setSupplierEditForm({ ...supplierEditForm, customer_number: event.target.value })}
                      />
                      <CategoryChecklist
                        value={supplierEditForm.default_cost_category}
                        onChange={(categories) => setSupplierEditForm({ ...supplierEditForm, default_cost_category: categories })}
                      />
                      <input
                        aria-label={tenantProfile.assignment_code_label}
                        list="assignment-code-options"
                        placeholder="leer = keine feste Zuordnung"
                        value={supplierEditForm.default_assignment_code}
                        onChange={(event) => setSupplierEditForm({ ...supplierEditForm, default_assignment_code: event.target.value })}
                      />
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={supplierEditForm.is_active}
                          onChange={(event) => setSupplierEditForm({ ...supplierEditForm, is_active: event.target.checked })}
                        />
                        <span>{supplierEditForm.is_active ? "aktiv" : "inaktiv"}</span>
                      </label>
                      <div className="row-actions">
                        <button type="button" onClick={() => saveSupplierEdit(rule)}>Speichern</button>
                        <button className="secondary-button" type="button" onClick={cancelSupplierEdit}>Abbrechen</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <strong>{rule.supplier_name}</strong>
                      <span>{rule.match_text}</span>
                      <span>{rule.customer_number || "-"}</span>
                      <span>{formatCostCategory(supplierCostCategories(rule))}</span>
                      <span>{rule.default_assignment_code || "-"}</span>
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={rule.is_active}
                          onChange={(event) => updateSupplierRule(rule, { is_active: event.target.checked })}
                        />
                        <span>{rule.is_active ? "aktiv" : "inaktiv"}</span>
                      </label>
                      <button className="secondary-button" type="button" onClick={() => startSupplierEdit(rule)}>
                        Bearbeiten
                      </button>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section className="admin-card admin-card-wide" ref={accountingSectionRef}>
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
              <input list="accounting-debit-options" placeholder="z.B. 3400" value={accountingForm.debit_account} onChange={(event) => setAccountingForm({ ...accountingForm, debit_account: event.target.value })} required />
            </FormField>
            <FormField label="Gegenkonto">
              <input list="accounting-credit-options" placeholder="z.B. Kreditor/Sammelkonto" value={accountingForm.credit_account} onChange={(event) => setAccountingForm({ ...accountingForm, credit_account: event.target.value })} required />
            </FormField>
            <FormField label="Steuerschlüssel">
              <input placeholder="optional" value={accountingForm.tax_key} onChange={(event) => setAccountingForm({ ...accountingForm, tax_key: event.target.value })} />
            </FormField>
            <FormField label="Steuersatz">
              <input placeholder="19.00" value={accountingForm.tax_rate} onChange={(event) => setAccountingForm({ ...accountingForm, tax_rate: event.target.value })} />
            </FormField>
            <FormField label="Skontokonto">
              <input list="accounting-discount-options" placeholder="optional" value={accountingForm.discount_account} onChange={(event) => setAccountingForm({ ...accountingForm, discount_account: event.target.value })} />
            </FormField>
            <button className="secondary-button" type="button" onClick={() => setAccountingForm((current) => applyAccountingSuggestions(current, activeAccountingFramework))}>
              Leere Konten vorschlagen
            </button>
            <button type="submit">Kontierungsregel anlegen</button>
          </form>
          <AccountSuggestionDatalist id="accounting-debit-options" suggestions={debitSuggestions} />
          <AccountSuggestionDatalist id="accounting-credit-options" suggestions={creditSuggestions} />
          <AccountSuggestionDatalist id="accounting-discount-options" suggestions={discountSuggestions} />
          <p className="form-hint">
            Kontenvorschläge aus {activeAccountingFramework}. Bitte fachlich prüfen; gespeicherte Regeln bleiben frei bearbeitbar.
            {hasUnsavedAccountingFramework ? " Geänderten Kontenrahmen bitte erst im Mandantenprofil speichern." : ""}
          </p>
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
              <span>Aktion</span>
            </div>
            {accountingRules.map((rule) => {
              const isEditing = accountingEditId === rule.id && accountingEditForm;
              return (
                <div className={isEditing ? "data-row editing-row" : "data-row"} data-accounting-rule-id={rule.id} key={rule.id}>
                  {isEditing ? (
                    <>
                      <input
                        aria-label="Name"
                        value={accountingEditForm.name}
                        onChange={(event) => setAccountingEditForm({ ...accountingEditForm, name: event.target.value })}
                        required
                      />
                      <input
                        aria-label="Lieferant enthält"
                        placeholder="optional"
                        value={accountingEditForm.supplier_match_text}
                        onChange={(event) => setAccountingEditForm({ ...accountingEditForm, supplier_match_text: event.target.value })}
                      />
                      <CostCategorySelect
                        value={accountingEditForm.cost_category}
                        onChange={(value) => setAccountingEditForm({ ...accountingEditForm, cost_category: value })}
                        includeAll
                      />
                      <input
                        aria-label="Aufwandskonto"
                        list="accounting-edit-debit-options"
                        value={accountingEditForm.debit_account}
                        onChange={(event) => setAccountingEditForm({ ...accountingEditForm, debit_account: event.target.value })}
                        required
                      />
                      <input
                        aria-label="Gegenkonto"
                        list="accounting-edit-credit-options"
                        value={accountingEditForm.credit_account}
                        onChange={(event) => setAccountingEditForm({ ...accountingEditForm, credit_account: event.target.value })}
                        required
                      />
                      <div className="inline-fields">
                        <input
                          aria-label="Steuerschlüssel"
                          placeholder="Schl."
                          value={accountingEditForm.tax_key}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, tax_key: event.target.value })}
                        />
                        <input
                          aria-label="Steuersatz"
                          placeholder="19.00"
                          value={accountingEditForm.tax_rate}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, tax_rate: event.target.value })}
                        />
                      </div>
                      <input
                        aria-label="Skontokonto"
                        list="accounting-edit-discount-options"
                        placeholder="optional"
                        value={accountingEditForm.discount_account}
                        onChange={(event) => setAccountingEditForm({ ...accountingEditForm, discount_account: event.target.value })}
                      />
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={accountingEditForm.is_active}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, is_active: event.target.checked })}
                        />
                        <span>{accountingEditForm.is_active ? "aktiv" : "inaktiv"}</span>
                      </label>
                      <div className="row-actions">
                        <button className="secondary-button" type="button" onClick={() => setAccountingEditForm((current) => applyAccountingSuggestions(current, activeAccountingFramework))}>
                          Vorschlagen
                        </button>
                        <button type="button" onClick={() => saveAccountingEdit(rule)}>Speichern</button>
                        <button className="secondary-button" type="button" onClick={cancelAccountingEdit}>Abbrechen</button>
                      </div>
                    </>
                  ) : (
                    <>
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
                      <button className="secondary-button" type="button" onClick={() => startAccountingEdit(rule)}>
                        Bearbeiten
                      </button>
                    </>
                  )}
                </div>
              );
            })}
          </div>
          <AccountSuggestionDatalist id="accounting-edit-debit-options" suggestions={editDebitSuggestions} />
          <AccountSuggestionDatalist id="accounting-edit-credit-options" suggestions={editCreditSuggestions} />
          <AccountSuggestionDatalist id="accounting-edit-discount-options" suggestions={editDiscountSuggestions} />
        </section>
      </div>
    </section>
  );
}

function FormField({ label, children }) {
  return (
    <div className="form-field">
      <span>{label}</span>
      {children}
    </div>
  );
}

function CategoryChecklist({ value, onChange }) {
  const selected = costCategoryList(value);
  return (
    <div className="check-list" role="group" aria-label="Kostenarten">
      {COST_CATEGORY_OPTIONS.map(([category, label]) => (
        <label className="check-pill" key={category}>
          <input
            type="checkbox"
            checked={selected.includes(category)}
            onChange={(event) => {
              const next = event.target.checked
                ? [...selected, category]
                : selected.filter((entry) => entry !== category);
              onChange(next);
            }}
          />
          <span>{label}</span>
        </label>
      ))}
    </div>
  );
}

function CostCategorySelect({ value, onChange, includeAll = false }) {
  return (
    <select aria-label="Kostenart" value={value || ""} onChange={(event) => onChange(event.target.value)}>
      {includeAll ? <option value="">Alle Kostenarten</option> : null}
      {COST_CATEGORY_OPTIONS.map(([category, label]) => (
        <option key={category} value={category}>{label}</option>
      ))}
    </select>
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
                  : `${tenantProfile.assignment_label_singular} ungeklärt`},{" "}
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
          <span>{tenantProfile.assignment_code_label}</span>
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
                  aria-label={`${tenantProfile.assignment_code_label} Zeile ${suggestion.line_no}`}
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

function BookingExportPreview({ month, rows, invalidDocuments = [], exportIssues = [], isBlocked = false, onClose }) {
  const documents = useMemo(() => groupBookingPreviewRows(rows), [rows]);
  const totals = useMemo(
    () => rows.reduce(
      (sum, row) => ({
        net: sum.net + numberOrZero(row.net_amount),
        tax: sum.tax + numberOrZero(row.tax_amount),
        gross: sum.gross + numberOrZero(row.gross_amount),
        delta: sum.delta + numberOrZero(row.payable_delta),
      }),
      { net: 0, tax: 0, gross: 0, delta: 0 },
    ),
    [rows],
  );
  const warningCount = rows.reduce((sum, row) => sum + exportWarningList(row).length, 0);

  return (
    <section className="booking-preview">
      <div className="booking-preview-head">
        <div>
          <p className="eyebrow">Exportvorschau</p>
          <h3>Buchungsentwurf {month}</h3>
          <span>{documents.length} Belege, {rows.length} Zeilen vor CSV-Erstellung</span>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>Schließen</button>
      </div>

      <div className="booking-preview-totals" aria-label="Summen der Exportvorschau">
        <PreviewTotal label="Netto" value={totals.net} />
        <PreviewTotal label="USt" value={totals.tax} />
        <PreviewTotal label="Brutto" value={totals.gross} />
        <PreviewTotal label="Zahlungsdifferenz" value={totals.delta} />
        <PreviewTotal label="Hinweise" value={warningCount} unit="" />
      </div>

      {warningCount ? (
        <div className="booking-preview-warning">
          {warningCount} Hinweise vor dem CSV-Export. Bitte Konten, Zuordnung und Zahlungsentscheidung prüfen.
        </div>
      ) : null}

      {isBlocked && invalidDocuments.length ? (
        <div className="booking-preview-blockers">
          <strong>CSV-Download ist noch blockiert</strong>
          <ul>
            {invalidDocuments.map((document) => (
              <li key={document.document_id || document.filename}>
                <span>{document.filename || document.document_id}</span>
                <small>{(document.errors || []).join(" ")}</small>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {exportIssues.length ? (
        <div className="booking-preview-blockers">
          <strong>Exportprüfung</strong>
          <ul>
            {exportIssues.map((issue, index) => (
              <li key={`${issue.document_id || issue.filename || "issue"}-${issue.row_index || index}`}>
                <span>
                  {[issue.invoice_number, issue.line_no ? `Zeile ${issue.line_no}` : null, formatExportRowType(issue.row_type)]
                    .filter(Boolean)
                    .join(" · ") || issue.filename || "Exportzeile"}
                </span>
                <small>{(issue.errors || []).join(", ")}</small>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="booking-preview-list">
        {documents.map((document) => (
          <BookingPreviewDocument key={document.key} document={document} />
        ))}
      </div>
    </section>
  );
}

function BookingPreviewDocument({ document }) {
  const totals = document.rows.reduce(
    (sum, row) => ({
      gross: sum.gross + numberOrZero(row.gross_amount),
      delta: sum.delta + numberOrZero(row.payable_delta),
    }),
    { gross: 0, delta: 0 },
  );
  const warnings = uniqueList(document.rows.flatMap(exportWarningList));

  return (
    <article className="booking-preview-document">
      <div className="booking-preview-document-head">
        <div>
          <h4>{document.invoiceNumber || "Beleg ohne Nummer"}</h4>
          <p>{document.supplierName || "-"}</p>
          <span>{safeVisibleFilename(document.normalizedFilename || document.originalFilename)}</span>
        </div>
        <div className="booking-preview-document-meta">
          <strong>{formatMoney(totals.gross)}</strong>
          <span>{formatDate(document.invoiceDate)}</span>
          {totals.delta ? <small>Differenz {formatMoney(totals.delta)}</small> : null}
        </div>
      </div>

      {warnings.length ? (
        <div className="booking-preview-document-warnings">
          {warnings.map((warning) => <span key={warning}>{warning}</span>)}
        </div>
      ) : null}

      <div className="booking-preview-lines">
        {document.rows.map((row, index) => (
          <BookingPreviewLine key={`${row.row_type}-${row.line_no || "delta"}-${index}`} row={row} />
        ))}
      </div>
    </article>
  );
}

function BookingPreviewLine({ row }) {
  const warnings = exportWarningList(row);

  return (
    <div className={warnings.length ? "booking-preview-line has-warning" : "booking-preview-line"}>
      <div className="booking-preview-line-main">
        <span className={`status ${row.row_type === "payment_adjustment" ? "blue" : "gray"}`}>{formatExportRowType(row.row_type)}</span>
        <div>
          <strong>{row.description || row.payment_label || "-"}</strong>
          <span>{row.line_no ? `Zeile ${row.line_no}` : "Zahlungszeile"}</span>
        </div>
      </div>
      <div className="booking-preview-line-fields">
        <PreviewField label="Zuordnung" value={[formatAssignmentKind(row.assignment_kind), row.assignment_code].filter(Boolean).join(" ") || "-"} />
        <PreviewField label="Kostenart" value={formatCostCategory(row.cost_category)} />
        <PreviewField label="Konten" value={formatAccountPair(row)} />
        <PreviewField label="Steuer" value={[row.tax_key, row.tax_rate ? `${row.tax_rate} %` : null].filter(Boolean).join(" / ") || "-"} />
        <PreviewField label="Zahlung" value={`${paymentTypeLabel(row.payment_type)} (${row.payment_decision_source || "-"})`} />
        <PreviewField label="Netto" value={formatMoney(row.net_amount)} numeric />
        <PreviewField label="USt" value={formatMoney(row.tax_amount)} numeric />
        <PreviewField label="Brutto" value={formatMoney(row.gross_amount)} numeric />
      </div>
      <details className="booking-preview-details">
        <summary>CSV-Details</summary>
        <div className="booking-preview-detail-grid">
          <PreviewField label="Kontierungsregel" value={row.accounting_rule || "-"} />
          <PreviewField label="Aufwandskonto" value={row.debit_account || "-"} />
          <PreviewField label="Gegenkonto" value={row.credit_account || "-"} />
          <PreviewField label="Skontokonto" value={row.discount_account || "-"} />
          <PreviewField label="Zahlbetrag" value={formatMoney(row.payment_amount)} numeric />
          <PreviewField label="Skonto-Basis" value={formatMoney(row.discount_base)} numeric />
          <PreviewField label="Skonto %" value={row.discount_percent || "-"} numeric />
          <PreviewField label="Skonto" value={formatMoney(row.discount_amount)} numeric />
          <PreviewField label="Differenz" value={formatMoney(row.payable_delta)} numeric />
        </div>
      </details>
    </div>
  );
}

function PreviewField({ label, value, numeric = false }) {
  return (
    <div className={numeric ? "preview-field numeric" : "preview-field"}>
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

function PreviewTotal({ label, value, unit = "EUR" }) {
  const displayValue = unit === "EUR" ? formatMoney(value.toFixed(2)) : value;
  return (
    <div>
      <span>{label}</span>
      <strong>{displayValue}</strong>
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

function extractionFormFromDocument(document) {
  const extraction = document.extraction || {};
  const raw = extraction.raw_result || {};
  return {
    supplier_name: extraction.supplier_name || "",
    invoice_number: extraction.invoice_number || "",
    invoice_date: inputDateValue(extraction.invoice_date),
    service_period: extraction.service_period || "",
    customer_number: raw.customer_number || "",
    document_type: raw.document_type || "incoming_invoice",
    cost_category: raw.cost_category || "",
    assignment_code: raw.assignment_code || raw.project_code || "",
    assignment_kind: raw.assignment_kind || "",
    net_amount: moneyDraftValue(extraction.net_amount),
    tax_amount: moneyDraftValue(extraction.tax_amount),
    gross_amount: moneyDraftValue(extraction.gross_amount),
    currency: extraction.currency || "EUR",
    due_date: inputDateValue(raw.due_date),
    discount_due_date: inputDateValue(raw.discount_due_date),
    discount_base: moneyDraftValue(raw.discount_base),
    discount_amount: moneyDraftValue(raw.discount_amount),
    discounted_payable_amount: moneyDraftValue(raw.discounted_payable_amount),
    item_summary: raw.item_summary || "",
  };
}

function normalizeExtractionUpdate(values) {
  return {
    supplier_name: values.supplier_name?.trim() || null,
    invoice_number: values.invoice_number?.trim() || null,
    invoice_date: values.invoice_date || null,
    service_period: values.service_period?.trim() || null,
    customer_number: values.customer_number?.trim() || null,
    document_type: values.document_type || null,
    cost_category: values.cost_category || null,
    assignment_code: values.assignment_code?.trim() || null,
    assignment_kind: values.assignment_kind || null,
    net_amount: decimalOrNull(values.net_amount),
    tax_amount: decimalOrNull(values.tax_amount),
    gross_amount: decimalOrNull(values.gross_amount),
    currency: values.currency?.trim().toUpperCase() || "EUR",
    due_date: values.due_date || null,
    discount_due_date: values.discount_due_date || null,
    discount_base: decimalOrNull(values.discount_base),
    discount_amount: decimalOrNull(values.discount_amount),
    discounted_payable_amount: decimalOrNull(values.discounted_payable_amount),
    item_summary: values.item_summary?.trim() || null,
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

function inputDateValue(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
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

async function waitForBulkJob(apiFetch, jobId, setBatch) {
  let job = null;
  for (let attempt = 0; attempt < 900; attempt += 1) {
    await delay(750);
    const response = await apiFetch(`/documents/bulk-jobs/${jobId}`);
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(formatApiError(result.detail, `Bulk-Job konnte nicht geladen werden: ${response.status}`));
    }
    const result = await response.json();
    job = result.job;
    setBatch(batchStateFromJob(job));
    if (!["queued", "running"].includes(job.status)) return job;
  }
  throw new Error("Bulk-Job läuft zu lange. Bitte später erneut prüfen.");
}

function batchStateFromJob(job) {
  const currentItem = job.items?.find((item) => item.status === "running")
    || job.items?.find((item) => item.status === "queued");
  const active = ["queued", "running"].includes(job.status);
  return {
    state: active ? "running" : "done",
    jobId: job.id,
    total: job.requested_total,
    done: job.processed_count,
    current: currentItem?.document?.original_filename || "",
    failed: job.failed_count,
    succeeded: job.succeeded_count,
  };
}

function formatBulkJobFailures(job, prefix) {
  const failedItems = (job.items || []).filter((item) => ["failed", "skipped"].includes(item.status));
  if (!failedItems.length) return "";
  const details = failedItems
    .slice(0, 3)
    .map((item) => `${item.document?.original_filename || item.document_id} (${item.error || "unbekannter Fehler"})`)
    .join("; ");
  return `${prefix}: ${details}${failedItems.length > 3 ? " ..." : ""}`;
}

function formatApiError(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (detail?.documents?.length) {
    const details = detail.documents
      .slice(0, 3)
      .map((entry) => {
        const message = entry.reason || entry.errors?.join(", ") || entry.filename || "unbekannter Fehler";
        return `${entry.filename || entry.document_id}: ${message}`;
      })
      .join("; ");
    return `${detail.message || fallback}: ${details}${detail.documents.length > 3 ? " ..." : ""}`;
  }
  if (detail?.message) return detail.message;
  return fallback;
}

function delay(milliseconds) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
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

function statusTone(status) {
  const tones = {
    review_pending: "gray",
    extracted: "blue",
    review_ready: "orange",
    review_approved: "green",
  };
  return tones[status] ?? "gray";
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

function formatExportRowType(value) {
  const labels = {
    cost: "Kosten",
    payment_adjustment: "Skonto",
  };
  return labels[value] ?? value;
}

function groupBookingPreviewRows(rows) {
  const grouped = new Map();
  rows.forEach((row, index) => {
    const key = row.document_id || `row-${index}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        key,
        invoiceNumber: row.invoice_number,
        invoiceDate: row.invoice_date,
        supplierName: row.supplier_name,
        originalFilename: row.original_filename,
        normalizedFilename: row.normalized_filename,
        rows: [],
      });
    }
    grouped.get(key).rows.push(row);
  });
  return Array.from(grouped.values());
}

function exportWarningList(row) {
  if (!row?.export_warnings) return [];
  return String(row.export_warnings)
    .split(";")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function uniqueList(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function formatAccountPair(row) {
  if (row.row_type === "payment_adjustment") return row.discount_account || "-";
  return [row.debit_account, row.credit_account].filter(Boolean).join(" / ") || "-";
}

function formatAssignment(rawResult, tenantProfile = assignmentProfileFromRaw(rawResult)) {
  if (rawResult?.assignment_code) return formatAssignmentCode(rawResult.assignment_code, rawResult.assignment_kind, tenantProfile);
  if (rawResult?.project_code) return `BV ${rawResult.project_code}`;
  const labels = {
    general_cost: "Allgemeine Kosten",
    assignment_unresolved: `${tenantProfile.assignment_label_singular} ungeklärt`,
    assignment_split: `${tenantProfile.assignment_label_plural} aufgeteilt`,
    project_split: "BV aufgeteilt",
    project_unresolved: "BV ungeklärt",
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
            : `${tenantProfile.assignment_label_singular} ungeklärt`;
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
  const categories = costCategoryList(value);
  if (!categories.length) return "-";
  return categories.map((category) => costCategoryLabel(category)).join(", ");
}

function costCategoryLabel(value) {
  return COST_CATEGORY_OPTIONS.find(([category]) => category === value)?.[1] ?? value;
}

function costCategoryList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter(Boolean);
  return String(value)
    .split(/[;,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function supplierCostCategories(rule) {
  return costCategoryList(rule.default_cost_categories?.length ? rule.default_cost_categories : rule.default_cost_category);
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
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return "-";
  return `${number.toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} EUR`;
}

function formatConfidence(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return "-";
  return `${Math.round(number * 100)} %`;
}

function formatDate(value) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBulkAction(action) {
  const labels = {
    extract: "Extraktion",
    prepare_review: "Buchungsvorschläge",
  };
  return labels[action] ?? action;
}

function formatBulkStatus(status) {
  const labels = {
    queued: "Wartet",
    running: "Läuft",
    completed: "Abgeschlossen",
    failed: "Fehlgeschlagen",
  };
  return labels[status] ?? status;
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

function approvalPaymentSummary(document) {
  const decision = document?.payment_decision;
  if (decision) {
    return {
      label: decision.label || paymentTypeLabel(decision.payment_type),
      due_date: decision.due_date,
      amount: decision.amount,
    };
  }

  const terms = paymentTermLinesForDocument(document);
  if (terms.length === 1) {
    return {
      label: `${terms[0].label} (Standard)`,
      due_date: terms[0].due_date,
      amount: terms[0].amount,
    };
  }

  return {
    label: "Keine Zahlungsentscheidung gewählt",
    due_date: null,
    amount: null,
  };
}

function paymentTermLinesForDocument(document) {
  const extraction = document?.extraction || {};
  const rawResult = extraction.raw_result || {};
  return paymentTermLines({
    ...rawResult,
    gross_amount: rawResult.gross_amount ?? extraction.gross_amount,
  });
}

function paymentTypeLabel(type) {
  const labels = {
    full_amount: "Ohne Abzug zahlen",
    cash_discount: "Skontozahlung",
    credit_note_settlement: "Gutschrift verrechnen",
  };
  return labels[type] ?? type ?? "-";
}

function numberOrZero(value) {
  const number = Number(String(value ?? "").replace(",", "."));
  return Number.isNaN(number) ? 0 : number;
}

function legacyDiscountedAmount(rawResult) {
  if (rawResult?.discounted_payable_amount) return rawResult.discounted_payable_amount;
  if (!rawResult?.gross_amount || !rawResult?.discount_amount) return null;
  return Number(rawResult.gross_amount) - Math.abs(Number(rawResult.discount_amount));
}

function formatApprovalError(detail, status) {
  if (detail?.errors?.length) {
    return `${detail.message || "Freigabe blockiert"}:\n${detail.errors.map((entry) => `- ${entry}`).join("\n")}`;
  }
  if (typeof detail === "string") return detail;
  return `Finale Freigabe fehlgeschlagen: ${status}`;
}

function extractApprovalIssues(detail) {
  return Array.isArray(detail?.details) ? detail.details : [];
}

function dedupeAccountingRuleIssues(issues) {
  const seen = new Set();
  return issues.filter((issue) => {
    const key = `${issue.code || ""}|${issue.supplier_name || ""}|${issue.cost_category || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function accountingRuleFixTitle(issues) {
  if (issues.some((issue) => issue.code === "missing_discount_account")) return "Skontokonto fehlt";
  if (issues.some((issue) => issue.code === "incomplete_accounting_rule")) return "Kontierungsregel unvollständig";
  return "Kontierungsregel fehlt";
}

function findAccountingRuleForTarget(rules, target) {
  if (!target) return null;
  if (target.rule_id) {
    const exactRule = rules.find((rule) => rule.id === target.rule_id);
    if (exactRule) return exactRule;
  }
  const supplierText = normalizeSearchText(target.supplier_name);
  return rules.find((rule) => {
    if (target.accounting_rule_name && rule.name !== target.accounting_rule_name) return false;
    if (target.cost_category && rule.cost_category !== target.cost_category) return false;
    if (supplierText && rule.supplier_match_text && !supplierText.includes(normalizeSearchText(rule.supplier_match_text))) return false;
    return true;
  }) ?? null;
}

function defaultAccountingRuleName(supplierName, costCategory) {
  return [formatCostCategory(costCategory), supplierName].filter(Boolean).join(" ").trim() || "Neue Kontierungsregel";
}

const ACCOUNTING_ACCOUNT_PRESETS = {
  SKR03: {
    debit: {
      material: [{ account: "3400", label: "Wareneingang 19 %" }],
      subcontractor: [{ account: "3100", label: "Fremdleistungen 19 %" }],
      fuel_vehicle: [{ account: "4530", label: "Kfz-Betriebskosten" }],
      software_subscription: [{ account: "4806", label: "Wartung/Software" }],
      security_subscription: [{ account: "4900", label: "Sonstige betriebliche Aufwendungen" }],
      general_overhead: [{ account: "4900", label: "Sonstige betriebliche Aufwendungen" }],
    },
    credit: [{ account: "70000", label: "Kreditoren-Sammelkonto" }],
    discount: [{ account: "3736", label: "Erhaltene Skonti 19 %" }],
  },
  SKR04: {
    debit: {
      material: [{ account: "5400", label: "Wareneingang 19 %" }],
      subcontractor: [{ account: "5900", label: "Fremdleistungen/Aufwand" }],
      fuel_vehicle: [{ account: "6530", label: "Fahrzeugkosten" }],
      software_subscription: [{ account: "6835", label: "Wartung/Software" }],
      security_subscription: [{ account: "6850", label: "Sonstige betriebliche Aufwendungen" }],
      general_overhead: [{ account: "6850", label: "Sonstige betriebliche Aufwendungen" }],
    },
    credit: [{ account: "70000", label: "Kreditoren-Sammelkonto" }],
    discount: [{ account: "5736", label: "Erhaltene Skonti 19 %" }],
  },
};

function accountingFramework(value) {
  return ["SKR03", "SKR04"].includes(value) ? value : "SKR03";
}

function accountSuggestions(framework, role, costCategory) {
  const presets = ACCOUNTING_ACCOUNT_PRESETS[accountingFramework(framework)] ?? ACCOUNTING_ACCOUNT_PRESETS.SKR03;
  if (role === "debit") {
    return presets.debit[costCategory] ?? [];
  }
  return presets[role] ?? [];
}

function firstAccountSuggestion(framework, role, costCategory) {
  return accountSuggestions(framework, role, costCategory)[0]?.account ?? "";
}

function applyAccountingSuggestions(form, framework) {
  return {
    ...form,
    debit_account: form.debit_account || firstAccountSuggestion(framework, "debit", form.cost_category),
    credit_account: form.credit_account || firstAccountSuggestion(framework, "credit", form.cost_category),
    discount_account: form.discount_account || firstAccountSuggestion(framework, "discount", form.cost_category),
    tax_rate: form.tax_rate || "19.00",
  };
}

function AccountSuggestionDatalist({ id, suggestions }) {
  return (
    <datalist id={id}>
      {suggestions.map((suggestion) => (
        <option key={`${id}-${suggestion.account}`} value={suggestion.account}>
          {suggestion.label}
        </option>
      ))}
    </datalist>
  );
}

function normalizeSearchText(value) {
  return String(value ?? "").trim().toLocaleLowerCase("de-DE");
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
      accounting_framework: "SKR03",
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
      accounting_framework: "SKR03",
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
      accounting_framework: "SKR03",
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
      accounting_framework: "SKR03",
    },
  };
  return templates[industry] ?? templates.general;
}

createRoot(document.getElementById("root")).render(<App />);
