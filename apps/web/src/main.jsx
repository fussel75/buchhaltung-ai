import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const apiBaseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL ?? "/api");
const AuthContext = createContext(null);
const AI_CHECK_TIMEOUT_MS = 60_000;
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
  const [aiCheckingIds, setAiCheckingIds] = useState([]);
  const [activeView, setActiveView] = useState("review");
  const [deletingIds, setDeletingIds] = useState([]);
  const [approvingIds, setApprovingIds] = useState([]);
  const [validatingIds, setValidatingIds] = useState([]);
  const [savingSuggestionIds, setSavingSuggestionIds] = useState([]);
  const [savingPaymentIds, setSavingPaymentIds] = useState([]);
  const [savingExtractionIds, setSavingExtractionIds] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [exporting, setExporting] = useState("");
  const [emailImporting, setEmailImporting] = useState(false);
  const [bookingPreview, setBookingPreview] = useState(null);
  const [exportMonth, setExportMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [uploadBatch, setUploadBatch] = useState(null);
  const [extractionBatch, setExtractionBatch] = useState(null);
  const [reviewBatch, setReviewBatch] = useState(null);
  const [bulkJobs, setBulkJobs] = useState([]);
  const [reviewFilter, setReviewFilter] = useState("all");
  const [problemReasonFilter, setProblemReasonFilter] = useState("");
  const [reviewSearch, setReviewSearch] = useState("");
  const [reviewSort, setReviewSort] = useState("created_desc");
  const [expandedDocumentIds, setExpandedDocumentIds] = useState([]);
  const [approvalDocumentId, setApprovalDocumentId] = useState(null);
  const [focusedReviewDocumentId, setFocusedReviewDocumentId] = useState(null);
  const [approvalError, setApprovalError] = useState("");
  const [approvalIssues, setApprovalIssues] = useState([]);
  const [highlightedBookingTarget, setHighlightedBookingTarget] = useState(null);
  const [reviewFocusTarget, setReviewFocusTarget] = useState(null);
  const [problemActionMessage, setProblemActionMessage] = useState("");
  const [accountingRuleDraft, setAccountingRuleDraft] = useState(null);
  const [accountingRuleEditTarget, setAccountingRuleEditTarget] = useState(null);
  const [assignmentUnitDraft, setAssignmentUnitDraft] = useState(null);
  const [tenantProfile, setTenantProfile] = useState(defaultTenantProfile("construction"));
  const [assignmentUnits, setAssignmentUnits] = useState([]);
  const approvalValidationRequestRef = useRef(0);
  const reviewQueueRef = useRef(null);
  const aiCheckControllersRef = useRef(new Map());
  const aiCheckTimeoutsRef = useRef(new Map());

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
  const problemDocuments = useMemo(
    () => documents.filter(isProblemExtraction),
    [documents],
  );
  const problemSummary = useMemo(
    () => summarizeProblemExtractionReasons(problemDocuments),
    [problemDocuments],
  );
  const problemWorkItems = useMemo(
    () => buildProblemWorkItems(problemDocuments),
    [problemDocuments],
  );
  const filteredDocuments = useMemo(
    () => {
      const searchText = normalizeSearchText(reviewSearch);
      return documents
        .filter((document) => {
          if (reviewFilter === "all") return true;
          if (reviewFilter === "problems") return documentMatchesProblemSummary(document, problemReasonFilter);
          return document.status === reviewFilter;
        })
        .filter((document) => !searchText || documentSearchText(document).includes(searchText))
        .sort((left, right) => compareReviewDocuments(left, right, reviewSort));
    },
    [documents, problemReasonFilter, reviewFilter, reviewSearch, reviewSort],
  );
  const extractableDocuments = useMemo(
    () => filteredDocuments.filter((document) => !document.extraction && document.status === "review_pending"),
    [filteredDocuments],
  );
  const extractableAllDocuments = useMemo(
    () => documents.filter((document) => !document.extraction && document.status === "review_pending"),
    [documents],
  );
  const reviewableDocuments = useMemo(
    () => filteredDocuments.filter((document) => document.status === "extracted" && document.extraction && !document.booking_suggestions?.length),
    [filteredDocuments],
  );
  const reextractableDocuments = useMemo(
    () => documents.filter((document) => ["extracted", "review_ready"].includes(document.status) && document.extraction),
    [documents],
  );
  const problemExtractionDocuments = useMemo(
    () => reextractableDocuments.filter((document) => documentMatchesProblemSummary(document, problemReasonFilter)),
    [problemReasonFilter, reextractableDocuments],
  );
  const problemAiDocuments = useMemo(
    () => problemExtractionDocuments.filter((document) => isPdfDocument(document)),
    [problemExtractionDocuments],
  );
  const problemReextractionLabel = problemReasonFilter ? `Problembelege neu: ${problemReasonFilter}` : "Problembelege neu";
  const problemAiLabel = problemReasonFilter ? `Problembelege mit KI: ${problemReasonFilter}` : "Problembelege mit KI";
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
  const clearAssignmentUnitDraft = useCallback(() => setAssignmentUnitDraft(null), []);

  const loadDocuments = useCallback(async () => {
    if (!activeTenantId) {
      setDocuments([]);
      return [];
    }

    const response = await apiFetch(`/documents?tenant_id=${encodeURIComponent(activeTenantId)}&limit=1000`);

    if (!response.ok) {
      throw new Error(`Review-Queue konnte nicht geladen werden: ${response.status}`);
    }

    const result = await response.json();
    const loadedDocuments = result.documents ?? [];
    setDocuments(loadedDocuments);
    return loadedDocuments;
  }, [activeTenantId, apiFetch]);

  useEffect(() => () => {
    aiCheckControllersRef.current.forEach((controller) => controller.abort());
    aiCheckTimeoutsRef.current.forEach((timeoutId) => window.clearTimeout(timeoutId));
    aiCheckControllersRef.current.clear();
    aiCheckTimeoutsRef.current.clear();
  }, []);

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

  const cancelBulkJob = useCallback(async (job) => {
    if (!job?.id || !["queued", "running"].includes(job.status)) return;
    const confirmed = window.confirm(`${formatBulkAction(job.action)} wirklich abbrechen? Bereits bearbeitete Belege bleiben erhalten.`);
    if (!confirmed) return;

    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`/documents/bulk-jobs/${job.id}/cancel`, { method: "POST" });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Auftrag konnte nicht abgebrochen werden: ${response.status}`));
      }
      const result = await response.json();
      rememberBulkJob(result.job);
      setExtractionBatch(null);
      setReviewBatch(null);
      await loadBulkJobs();
      await loadDocuments();
      setNotice("Auftrag abgebrochen. Gesperrte Belege wurden wieder freigegeben.");
    } catch (cancelError) {
      setError(cancelError.message);
    }
  }, [apiFetch, loadBulkJobs, loadDocuments, rememberBulkJob]);

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

  const loadAssignmentUnits = useCallback(async () => {
    if (!activeTenantId) {
      setAssignmentUnits([]);
      return;
    }
    const response = await apiFetch(`/masterdata/assignment-units?tenant_id=${encodeURIComponent(activeTenantId)}`);
    if (!response.ok) return;
    const result = await response.json();
    setAssignmentUnits(result.assignment_units ?? []);
  }, [activeTenantId, apiFetch]);

  useEffect(() => {
    loadTenantProfile();
  }, [loadTenantProfile]);

  useEffect(() => {
    loadAssignmentUnits();
  }, [loadAssignmentUnits]);

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

  const scrollReviewQueueIntoView = useCallback(() => {
    window.requestAnimationFrame(() => {
      reviewQueueRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const openProblemDocument = useCallback((document, reason) => {
    if (!document?.id) return;
    const targetReason = reason || problemExtractionSummaryKey(problemExtractionReasons(document)[0] || "");
    const focusTarget = problemCorrectionFocusTarget(targetReason, document, tenantProfile);
    setActiveView("review");
    setReviewFilter("problems");
    setProblemReasonFilter(targetReason);
    setReviewSearch("");
    setReviewSort("problem_desc");
    setFocusedReviewDocumentId(document.id);
    setReviewFocusTarget(focusTarget);
    setExpandedDocumentIds((current) => (
      current.includes(document.id) ? current : [...current, document.id]
    ));
    setProblemActionMessage(`${targetReason}: ${focusTarget.message}`);
    scrollReviewQueueIntoView();
    window.setTimeout(() => focusReviewDocumentCard(document.id, { focusAction: false }), 80);
  }, [scrollReviewQueueIntoView, tenantProfile]);

  const openProblemWorkItem = useCallback((item) => {
    openProblemDocument(item?.documents?.[0], item?.reason);
  }, [openProblemDocument]);

  const moveToNextProblemDocument = useCallback((currentDocumentId) => {
    const currentReason = reviewFilter === "problems" ? problemReasonFilter : "";
    const candidates = documents
      .filter((document) => document.extraction)
      .filter((document) => documentMatchesProblemSummary(document, currentReason))
      .sort((left, right) => compareReviewDocuments(left, right, "problem_desc"));
    if (!candidates.length) return;
    const currentIndex = candidates.findIndex((document) => document.id === currentDocumentId);
    const nextDocument = currentIndex >= 0
      ? candidates[(currentIndex + 1) % candidates.length]
      : candidates[0];
    openProblemDocument(nextDocument, currentReason || problemExtractionSummaryKey(problemExtractionReasons(nextDocument)[0] || ""));
  }, [documents, openProblemDocument, problemReasonFilter, reviewFilter]);

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

  const cancelAiCheckDocument = useCallback((documentId, message = "KI-Prüfung abgebrochen.") => {
    const controller = aiCheckControllersRef.current.get(documentId);
    if (controller) {
      controller.abort();
    }
    const timeoutId = aiCheckTimeoutsRef.current.get(documentId);
    if (timeoutId) {
      window.clearTimeout(timeoutId);
    }
    aiCheckControllersRef.current.delete(documentId);
    aiCheckTimeoutsRef.current.delete(documentId);
    setAiCheckingIds((current) => current.filter((id) => id !== documentId));
    setError(message);
  }, []);

  const aiCheckDocument = useCallback(
    async (document) => {
      if (aiCheckControllersRef.current.has(document.id)) {
        return;
      }
      const confirmed = window.confirm(
        `Beleg "${document.original_filename}" mit KI prüfen? Bestehende Buchungsvorschläge werden verworfen, wenn die Extraktion gespeichert wird.`,
      );
      if (!confirmed) return;

      setError("");
      setNotice("");
      setAiCheckingIds((current) => (current.includes(document.id) ? current : [...current, document.id]));

      const controller = new AbortController();
      let timedOut = false;
      aiCheckControllersRef.current.set(document.id, controller);
      const timeoutId = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, AI_CHECK_TIMEOUT_MS);
      aiCheckTimeoutsRef.current.set(document.id, timeoutId);

      try {
        const response = await apiFetch(`/documents/${document.id}/ai-extract`, {
          method: "POST",
          signal: controller.signal,
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(formatApiError(result.detail, `KI-Prüfung fehlgeschlagen: ${response.status}`));
        }

        const result = await response.json();
        await loadDocuments();
        const ai = result.document?.extraction?.raw_result?.ai_extraction || {};
        const acceptedFields = Array.isArray(ai.accepted_fields) ? ai.accepted_fields.filter(Boolean) : [];
        if (ai.status === "failed") {
          setError(`KI-Prüfung ohne Ergebnis: ${ai.error || "Anbieter hat keine auswertbare Antwort geliefert."}`);
        } else if (ai.status === "applied") {
          setNotice(`KI-Prüfung übernommen: ${acceptedFields.length ? acceptedFields.map(formatAiFieldLabel).join(", ") : result.document.original_filename}`);
        } else {
          setNotice(`KI-Prüfung abgeschlossen: keine neuen Werte übernommen (${result.document.original_filename}).`);
        }
      } catch (aiError) {
        if (aiError.name === "AbortError") {
          setError(timedOut
            ? "KI-Prüfung nach 60 Sekunden abgebrochen. Bitte später erneut versuchen oder den Beleg manuell prüfen."
            : "KI-Prüfung abgebrochen.");
        } else {
          setError(aiError.message);
        }
      } finally {
        const activeTimeoutId = aiCheckTimeoutsRef.current.get(document.id);
        if (activeTimeoutId) {
          window.clearTimeout(activeTimeoutId);
        }
        aiCheckControllersRef.current.delete(document.id);
        aiCheckTimeoutsRef.current.delete(document.id);
        setAiCheckingIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [apiFetch, loadDocuments],
  );

  const startBulkExtraction = useCallback(async () => {
    const targets = extractableAllDocuments;
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
      const response = await apiFetch("/documents/bulk/extract-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          limit: 1000,
        }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Bulk-Extraktion fehlgeschlagen: ${response.status}`));
      }
      const result = await response.json();
      if (!result.job) {
        setExtractionBatch(null);
        setNotice("Keine offenen Belege für Extraktion gefunden.");
        return;
      }
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
  }, [activeTenantId, apiFetch, extractableAllDocuments, isBulkExtracting, loadBulkJobs, loadDocuments, rememberBulkJob]);

  const startBulkReextraction = useCallback(async () => {
    const targets = reextractableDocuments;
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
      const response = await apiFetch("/documents/bulk/reextract-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          limit: 1000,
          confirm: true,
        }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Neu-Extraktion fehlgeschlagen: ${response.status}`));
      }
      const result = await response.json();
      if (!result.job) {
        setExtractionBatch(null);
        setNotice("Keine Belege für Neu-Extraktion gefunden.");
        return;
      }
      rememberBulkJob(result.job);
      setExtractionBatch(batchStateFromJob(result.job));
      const job = await waitForBulkJob(apiFetch, result.job.id, setExtractionBatch);
      rememberBulkJob(job);
      await loadBulkJobs();
      await loadDocuments();
      setNotice(`Neu-Extraktion abgeschlossen: ${job.succeeded_count} neu extrahiert, ${job.failed_count} fehlgeschlagen.${formatReextractionSummaryNotice(job.summary)}`);
      if (job.failed_count) {
        setError(formatBulkJobFailures(job, "Nicht neu extrahiert"));
      }
    } catch (extractError) {
      setError(extractError.message);
    } finally {
      setExtractingIds((current) => current.filter((id) => !targets.some((document) => document.id === id)));
    }
  }, [activeTenantId, apiFetch, isBulkExtracting, loadBulkJobs, loadDocuments, reextractableDocuments, rememberBulkJob]);

  const startProblemReextraction = useCallback(async () => {
    const targets = problemExtractionDocuments;
    if (!targets.length || isBulkExtracting) return;

    const scopeLabel = problemReasonFilter ? ` mit "${problemReasonFilter}"` : "";
    const confirmed = window.confirm(
      `${targets.length} Problembelege${scopeLabel} neu extrahieren? Vorhandene Buchungsvorschläge, Freigaben und Zahlungsentscheidungen dieser Belege werden verworfen.`,
    );
    if (!confirmed) return;

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
      const response = await apiFetch("/documents/bulk/reextract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          document_ids: targets.map((document) => document.id),
          confirm: true,
        }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Problem-Neu-Extraktion fehlgeschlagen: ${response.status}`));
      }
      const result = await response.json();
      if (!result.job) {
        setExtractionBatch(null);
        setNotice("Keine Problembelege für Neu-Extraktion gefunden.");
        return;
      }
      rememberBulkJob(result.job);
      setExtractionBatch(batchStateFromJob(result.job));
      const job = await waitForBulkJob(apiFetch, result.job.id, setExtractionBatch);
      rememberBulkJob(job);
      await loadBulkJobs();
      await loadDocuments();
      setNotice(`Problem-Neu-Extraktion${scopeLabel} abgeschlossen: ${job.succeeded_count} neu extrahiert, ${job.failed_count} fehlgeschlagen.${formatReextractionSummaryNotice(job.summary)}`);
      if (job.failed_count) {
        setError(formatBulkJobFailures(job, "Nicht neu extrahiert"));
      }
    } catch (extractError) {
      setError(extractError.message);
    } finally {
      setExtractingIds((current) => current.filter((id) => !targets.some((document) => document.id === id)));
    }
  }, [activeTenantId, apiFetch, isBulkExtracting, loadBulkJobs, loadDocuments, problemExtractionDocuments, problemReasonFilter, rememberBulkJob]);

  const startProblemAiExtraction = useCallback(async () => {
    const targets = problemAiDocuments;
    if (!targets.length || isBulkExtracting) return;

    const scopeLabel = problemReasonFilter ? ` mit "${problemReasonFilter}"` : "";
    const confirmed = window.confirm(
      `${targets.length} Problembelege${scopeLabel} mit KI prüfen? Das kann je nach Anbieter Kosten verursachen. Bestehende Buchungsvorschläge, Freigaben und Zahlungsentscheidungen dieser Belege können verworfen werden, wenn die KI Felder übernimmt.`,
    );
    if (!confirmed) return;

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
      const response = await apiFetch("/documents/bulk/ai-extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          document_ids: targets.map((document) => document.id),
          confirm: true,
        }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(formatApiError(result.detail, `Bulk-KI-Prüfung fehlgeschlagen: ${response.status}`));
      }
      const result = await response.json();
      if (!result.job) {
        setExtractionBatch(null);
        setNotice("Keine Problembelege für KI-Prüfung gefunden.");
        return;
      }
      rememberBulkJob(result.job);
      setExtractionBatch(batchStateFromJob(result.job));
      const job = await waitForBulkJob(apiFetch, result.job.id, setExtractionBatch);
      rememberBulkJob(job);
      await loadBulkJobs();
      await loadDocuments();
      setNotice(`Bulk-KI-Prüfung${scopeLabel} abgeschlossen: ${job.succeeded_count} geprüft, ${job.failed_count} fehlgeschlagen.${formatAiExtractionSummaryNotice(job.summary)}`);
      if (job.failed_count) {
        setError(formatBulkJobFailures(job, "KI-Prüfung fehlgeschlagen"));
      }
    } catch (extractError) {
      setError(extractError.message);
    } finally {
      setExtractingIds((current) => current.filter((id) => !targets.some((document) => document.id === id)));
    }
  }, [activeTenantId, apiFetch, isBulkExtracting, loadBulkJobs, loadDocuments, problemAiDocuments, problemReasonFilter, rememberBulkJob]);

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

  const runEmailImport = useCallback(async () => {
    if (!activeTenantId || emailImporting) return;

    setError("");
    setNotice("");
    setEmailImporting(true);
    try {
      const response = await apiFetch(`/email-import/run?tenant_id=${encodeURIComponent(activeTenantId)}`, {
        method: "POST",
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(formatApiError(result.detail, `E-Mail-Import fehlgeschlagen: ${response.status}`));
      }
      await loadDocuments();
      const parts = [
        `${result.scanned_messages ?? 0} Mails geprüft`,
        `${result.imported?.length ?? 0} importiert`,
        `${result.duplicates?.length ?? 0} Dubletten`,
        `${result.failed?.length ?? 0} fehlgeschlagen`,
      ];
      setNotice(`E-Mail-Import abgeschlossen: ${parts.join(", ")}.`);
      if (!result.scanned_messages) {
        setError("Keine ungelesenen Mails gefunden. Zum Testen eine neue ungelesene Mail senden oder EMAIL_IMPORT_SEARCH auf ALL setzen.");
      } else if (result.skipped_attachments) {
        setError(`${result.skipped_attachments} Anhänge wurden übersprungen, weil Dateityp oder Inhalt nicht zum Belegimport passt.`);
      }
    } catch (importError) {
      setError(importError.message);
    } finally {
      setEmailImporting(false);
    }
  }, [activeTenantId, apiFetch, emailImporting, loadDocuments]);

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
        return result.document;
      } catch (prepareError) {
        setError(prepareError.message);
        return null;
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

  const returnToApprovalAfterAccountingRule = useCallback(
    async (documentId, successMessage = "Kontierungsregel gespeichert. Freigabeprüfung läuft erneut.") => {
      if (!documentId) return;

      setActiveView("review");
      setReviewFilter("all");
      setFocusedReviewDocumentId(null);
      setExpandedDocumentIds((current) => (
        current.includes(documentId) ? current : [...current, documentId]
      ));
      setHighlightedBookingTarget({ documentId, lineNo: "", rowType: "" });
      setApprovalDocumentId(documentId);
      setApprovalError("");
      setApprovalIssues([]);
      setError("");
      setNotice(successMessage);

      const requestId = approvalValidationRequestRef.current + 1;
      approvalValidationRequestRef.current = requestId;
      setValidatingIds((current) => [...current, documentId]);

      try {
        await loadDocuments();
        const response = await apiFetch(`/documents/${documentId}/review-validation`);
        if (!response.ok) {
          throw new Error(`Freigabeprüfung fehlgeschlagen: ${response.status}`);
        }
        const result = await response.json();
        if (approvalValidationRequestRef.current !== requestId) return;
        const details = Array.isArray(result.details) ? result.details : [];
        const errors = Array.isArray(result.errors) ? result.errors : [];
        setApprovalIssues(details);
        setApprovalError(errors.length ? formatApprovalError({ message: "Freigabe blockiert", errors }, 409) : "");
        setNotice(errors.length ? "Freigabeprüfung erneut blockiert. Bitte die Hinweise im Dialog prüfen." : "Freigabeprüfung erfolgreich. Der Beleg kann final freigegeben werden.");
        window.setTimeout(() => focusReviewDocumentCard(documentId, { focusAction: false }), 120);
      } catch (validationError) {
        if (approvalValidationRequestRef.current !== requestId) return;
        setApprovalError(validationError.message);
        setError(validationError.message);
      } finally {
        setValidatingIds((current) => current.filter((id) => id !== documentId));
      }
    },
    [apiFetch, loadDocuments],
  );

  const returnToApprovalAfterAssignmentUnit = useCallback(
    async (payload) => {
      const documentId = typeof payload === "string" ? payload : payload?.documentId;
      if (!documentId) return;

      const assignmentUnit = payload?.assignmentUnit || null;
      const lineNo = payload?.lineNo ? String(payload.lineNo) : "";
      const suggestionId = payload?.suggestionId || "";
      const document = documents.find((item) => item.id === documentId);
      const suggestion = (document?.booking_suggestions || []).find((item) => (
        (suggestionId && item.id === suggestionId) || (lineNo && String(item.line_no) === lineNo)
      ));

      if (assignmentUnit?.code && suggestion) {
        setError("");
        setNotice("Zuordnung angelegt. Buchungszeile wird aktualisiert.");
        setSavingSuggestionIds((current) => [...current, suggestion.id]);
        try {
          const response = await apiFetch(`/documents/${documentId}/booking-suggestions/${suggestion.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(normalizeBookingSuggestion({
              ...suggestion,
              assignment_code: assignmentUnit.code,
              assignment_kind: assignmentUnit.kind || suggestion.assignment_kind,
            })),
          });

          if (!response.ok) {
            throw new Error(`Buchungszeile konnte nicht auf die neue Zuordnung gesetzt werden: ${response.status}`);
          }
        } catch (saveError) {
          setError(saveError.message);
          setActiveView("review");
          setExpandedDocumentIds((current) => (
            current.includes(documentId) ? current : [...current, documentId]
          ));
          setFocusedReviewDocumentId(documentId);
          setHighlightedBookingTarget({ documentId, lineNo, rowType: "" });
          return;
        } finally {
          setSavingSuggestionIds((current) => current.filter((id) => id !== suggestion.id));
        }
      }

      await returnToApprovalAfterAccountingRule(documentId, "Zuordnung gespeichert. Freigabeprüfung läuft erneut.");
    },
    [apiFetch, documents, returnToApprovalAfterAccountingRule],
  );

  function prepareAccountingRuleFromApproval(issue) {
    if (user?.role !== "admin") {
      setNotice("Kontierungsregel braucht Pflege. Bitte einen Admin bitten, die Regel unter Stammdaten zu prüfen.");
      return;
    }
    if (issue?.code !== "missing_accounting_rule") {
      const isAmbiguousRule = issue?.code === "ambiguous_accounting_rule";
      const focusField = issue?.code === "missing_discount_account"
        ? "discount_account"
        : isAmbiguousRule
          ? "supplier_match_text"
          : "debit_account";
      setAccountingRuleEditTarget({
        id: `${Date.now()}-${issue?.accounting_rule_id || issue?.accounting_rule_name || issue?.cost_category || ""}`,
        rule_id: issue?.accounting_rule_id || "",
        accounting_rule_name: issue?.accounting_rule_name || issue?.suggested_name || "",
        supplier_name: issue?.supplier_name || "",
        cost_category: issue?.cost_category || "",
        focus_field: focusField,
        return_document_id: approvalDocument?.id || "",
      });
      approvalValidationRequestRef.current += 1;
      setApprovalDocumentId(null);
      setApprovalError("");
      setApprovalIssues([]);
      setActiveView("masterdata");
      setNotice(isAmbiguousRule
        ? "Kontierungsregel wird geöffnet. Bitte Erkennung oder Kostenart eindeutiger machen und speichern."
        : "Kontierungsregel wird geöffnet. Bitte fehlende Konten ergänzen und speichern.");
      return;
    }
    setAccountingRuleDraft({
      id: `${Date.now()}-${issue?.cost_category || ""}-${issue?.supplier_name || ""}`,
      return_document_id: approvalDocument?.id || "",
      form: accountingRuleFormFromApprovalIssue(issue, approvalDocument),
      focus_field: issue?.suggested_debit_account ? "credit_account" : "debit_account",
    });
    approvalValidationRequestRef.current += 1;
    setApprovalDocumentId(null);
    setApprovalError("");
    setApprovalIssues([]);
    setActiveView("masterdata");
    setNotice("Kontierungsregel in Stammdaten vorbereitet. Bitte Konten fachlich ergänzen und speichern.");
  }

  async function createAccountingRuleFromApproval(form, returnDocumentId) {
    if (user?.role !== "admin") {
      throw new Error("Kontierungsregeln dürfen nur durch Admins angelegt werden.");
    }
    const response = await apiFetch(`/masterdata/accounting-rules?tenant_id=${encodeURIComponent(activeTenantId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(form)),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Kontierungsregel konnte nicht angelegt werden");
      const saveError = new Error(apiError.message);
      saveError.fields = apiError.fields;
      throw saveError;
    }
    setNotice("Kontierungsregel angelegt. Freigabeprüfung läuft erneut.");
    await returnToApprovalAfterAccountingRule(returnDocumentId);
  }

  function openAccountingRulesFromApproval() {
    if (user?.role !== "admin") {
      setNotice("Kontierungsregel braucht Pflege. Bitte einen Admin bitten, die Regel unter Stammdaten zu prüfen.");
      return;
    }
    approvalValidationRequestRef.current += 1;
    setApprovalDocumentId(null);
    setApprovalError("");
    setApprovalIssues([]);
    setActiveView("masterdata");
    setNotice("Bitte die Kontierungsregeln prüfen und eindeutiger machen.");
  }

  function prepareAssignmentUnitFromApproval(issue) {
    if (user?.role !== "admin") {
      setNotice("Zuordnung braucht Stammdatenpflege. Bitte einen Admin bitten, die Zuordnung unter Stammdaten zu prüfen.");
      return;
    }
    const lineNo = issue?.line_no ? String(issue.line_no) : "";
    const suggestion = (approvalDocument?.booking_suggestions || []).find((item) => (
      lineNo && String(item.line_no) === lineNo
    ));
    setAssignmentUnitDraft({
      id: `${Date.now()}-${issue?.assignment_code || issue?.line_no || ""}`,
      return_document_id: approvalDocument?.id || "",
      return_line_no: lineNo,
      return_suggestion_id: suggestion?.id || "",
      form: assignmentUnitFormFromApprovalIssue(issue, approvalDocument, tenantProfile),
      focus_field: issue?.assignment_code ? "label" : "code",
    });
    approvalValidationRequestRef.current += 1;
    setApprovalDocumentId(null);
    setApprovalError("");
    setApprovalIssues([]);
    setActiveView("masterdata");
    setNotice(`${tenantProfile.assignment_label_singular} in Stammdaten vorbereitet. Bitte Angaben ergänzen und speichern.`);
  }

  function focusBookingSuggestionFromApproval(issue) {
    if (!approvalDocument) return;
    const lineNo = issue?.line_no ? String(issue.line_no) : "";
    const target = issue?.target === "booking_export"
      ? "booking_lines"
      : issue?.target || (lineNo ? "booking_lines" : "review");
    approvalValidationRequestRef.current += 1;
    setApprovalDocumentId(null);
    setApprovalError("");
    setApprovalIssues([]);
    setActiveView("review");
    setReviewFilter("all");
    setFocusedReviewDocumentId(approvalDocument.id);
    setExpandedDocumentIds((current) => (
      current.includes(approvalDocument.id) ? current : [...current, approvalDocument.id]
    ));
    setHighlightedBookingTarget({
      documentId: approvalDocument.id,
      lineNo,
      rowType: issue?.row_type || "",
    });
    setReviewFocusTarget({
      documentId: approvalDocument.id,
      target,
      field: issue?.field || "",
      lineNo,
      action: issue?.action || "",
    });
    setNotice(reviewCorrectionNotice(issue));
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
      const { remember_supplier_rule: rememberSupplierRule, ...extractionValues } = values;
      setError("");
      setNotice("");
      setSavingExtractionIds((current) => [...current, document.id]);
      try {
        const response = await apiFetch(`/documents/${document.id}/extraction`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(normalizeExtractionUpdate(extractionValues)),
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(formatApiError(result.detail, `Extraktionsdaten konnten nicht gespeichert werden: ${response.status}`));
        }

        const result = await response.json();
        let ruleNotice = "";
        if (rememberSupplierRule) {
          const supplierRulePayload = supplierRulePayloadFromExtractionForm(extractionValues);
          if (supplierRulePayload) {
            try {
              const ruleResponse = await apiFetch(`/masterdata/supplier-rules?tenant_id=${encodeURIComponent(activeTenantId)}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(supplierRulePayload),
              });
              if (!ruleResponse.ok) {
                const ruleResult = await ruleResponse.json().catch(() => ({}));
                throw new Error(formatApiError(ruleResult.detail, `Lieferantenregel konnte nicht angelegt werden: ${ruleResponse.status}`));
              }
              ruleNotice = " Lieferantenregel angelegt.";
            } catch (ruleError) {
              ruleNotice = ` Lieferantenregel nicht angelegt: ${ruleError.message}`;
            }
          }
        }
        await loadDocuments();
        setNotice(`Extraktionsdaten gespeichert: ${result.document.original_filename}. Bitte Buchungsvorschlag neu erstellen.${ruleNotice}`);
        return result.document;
      } catch (saveError) {
        setError(saveError.message);
        return null;
      } finally {
        setSavingExtractionIds((current) => current.filter((id) => id !== document.id));
      }
    },
    [activeTenantId, apiFetch, loadDocuments],
  );

  const saveExtractionAndPrepareReview = useCallback(
    async (document, values) => {
      const savedDocument = await saveExtraction(document, values);
      if (!savedDocument) return null;
      const preparedDocument = await prepareReview(document);
      return preparedDocument;
    },
    [prepareReview, saveExtraction],
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
            <button type="button" className={activeView === "projects" ? "active" : ""} onClick={() => setActiveView("projects")}>
              Projekte
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
          <BulkJobHistory jobs={bulkJobs} onCancel={cancelBulkJob} />
          </aside>

          <section className="uploads" ref={reviewQueueRef}>
        <div className="section-header queue-header">
          <div className="queue-heading">
            <div>
              <h2>Review-Queue</h2>
              <span>{filteredDocuments.length} von {documents.length} Belegen</span>
            </div>
            <div className="filter-tabs" aria-label="Review-Filter">
              <button type="button" className={reviewFilter === "all" ? "active" : ""} onClick={() => { setReviewFilter("all"); setProblemReasonFilter(""); }}>
                Alle
              </button>
              <button type="button" className={reviewFilter === "review_pending" ? "active" : ""} onClick={() => { setReviewFilter("review_pending"); setProblemReasonFilter(""); }}>
                Offen {queueStats.pending}
              </button>
              <button type="button" className={reviewFilter === "extracted" ? "active" : ""} onClick={() => { setReviewFilter("extracted"); setProblemReasonFilter(""); }}>
                Extrahiert {queueStats.extracted}
              </button>
              <button type="button" className={reviewFilter === "review_ready" ? "active" : ""} onClick={() => { setReviewFilter("review_ready"); setProblemReasonFilter(""); }}>
                Vorschlag {queueStats.ready}
              </button>
              <button type="button" className={reviewFilter === "review_approved" ? "active" : ""} onClick={() => { setReviewFilter("review_approved"); setProblemReasonFilter(""); }}>
                Freigegeben {queueStats.approved}
              </button>
              <button type="button" className={reviewFilter === "problems" && !problemReasonFilter ? "active" : ""} onClick={() => { setReviewFilter("problems"); setProblemReasonFilter(""); setReviewSort("problem_desc"); }}>
                Probleme {problemDocuments.length}
              </button>
            </div>
            <div className="queue-search-tools">
              <label>
                <span>Suchen</span>
                <input
                  type="search"
                  placeholder="Datei, Lieferant, Rechnung, Projekt"
                  value={reviewSearch}
                  onChange={(event) => setReviewSearch(event.target.value)}
                />
              </label>
              <label>
                <span>Sortieren</span>
                <select value={reviewSort} onChange={(event) => setReviewSort(event.target.value)}>
                  <option value="created_desc">Neueste zuerst</option>
                  <option value="created_asc">Älteste zuerst</option>
                  <option value="problem_desc">Problempriorität</option>
                  <option value="date_desc">Belegdatum absteigend</option>
                  <option value="date_asc">Belegdatum aufsteigend</option>
                  <option value="amount_desc">Betrag absteigend</option>
                  <option value="amount_asc">Betrag aufsteigend</option>
                  <option value="supplier_asc">Lieferant A-Z</option>
                  <option value="filename_asc">Dateiname A-Z</option>
                </select>
              </label>
            </div>
            {problemSummary.length ? (
              <div className="problem-summary" aria-label="Häufige Extraktionsprobleme">
                {problemSummary.map((item) => (
                  <button
                    type="button"
                    className={reviewFilter === "problems" && problemReasonFilter === item.reason ? "active" : ""}
                    key={item.reason}
                    onClick={() => {
                      setReviewFilter("problems");
                      setProblemReasonFilter(item.reason);
                      setReviewSearch("");
                      setReviewSort("problem_desc");
                      setProblemActionMessage(`Problemfilter aktiv: ${item.reason}`);
                      scrollReviewQueueIntoView();
                    }}
                  >
                    <span>{item.reason}</span>
                    <strong>{item.count}</strong>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="queue-tools">
            <div className="queue-primary-actions">
              {user?.role === "admin" ? (
                <button
                  type="button"
                  className="secondary-button"
                  onClick={runEmailImport}
                  disabled={!activeTenantId || emailImporting}
                >
                  {emailImporting ? "Emails werden abgerufen..." : "Emails abrufen"}
                </button>
              ) : null}
              <button
                type="button"
                onClick={startBulkExtraction}
                disabled={!extractableAllDocuments.length || isBulkExtracting}
              >
                {isBulkExtracting ? "Extrahiert..." : `Alle offenen extrahieren (${extractableAllDocuments.length})`}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={startBulkReextraction}
                disabled={!reextractableDocuments.length || isBulkExtracting}
              >
                {isBulkExtracting ? "Läuft..." : `Alle neu extrahieren (${reextractableDocuments.length})`}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={startProblemReextraction}
                disabled={!problemExtractionDocuments.length || isBulkExtracting}
              >
                {isBulkExtracting ? "Läuft..." : `${problemReextractionLabel} (${problemExtractionDocuments.length})`}
              </button>
              {user?.role === "admin" ? (
                <button
                  type="button"
                  className="secondary-button"
                  onClick={startProblemAiExtraction}
                  disabled={!problemAiDocuments.length || isBulkExtracting}
                >
                  {isBulkExtracting ? "Läuft..." : `${problemAiLabel} (${problemAiDocuments.length})`}
                </button>
              ) : null}
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
        <ProblemWorkboard
          items={problemWorkItems}
          activeReason={reviewFilter === "problems" ? problemReasonFilter : ""}
          actionMessage={problemActionMessage}
          onSelect={(reason) => {
            setReviewFilter("problems");
            setProblemReasonFilter(reason);
            setReviewSearch("");
            setReviewSort("problem_desc");
            setProblemActionMessage(`Problemfilter aktiv: ${reason}`);
            scrollReviewQueueIntoView();
          }}
          onOpenFirst={openProblemWorkItem}
          onShowAll={() => {
            setReviewFilter("problems");
            setProblemReasonFilter("");
            setReviewSearch("");
            setReviewSort("problem_desc");
            setProblemActionMessage("Alle Problembelege werden angezeigt.");
            scrollReviewQueueIntoView();
          }}
        />
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
          <>
          {reviewFilter === "problems" && problemReasonFilter ? (
            <div className="active-problem-filter">
              <span>Problemfilter: {problemReasonFilter}</span>
              <button type="button" className="secondary-button" onClick={() => setProblemReasonFilter("")}>
                Alle Problembelege
              </button>
            </div>
          ) : null}
          <div className="queue">
            {filteredDocuments.map((document) => {
              const isExpanded = expandedDocumentIds.includes(document.id);
              const problemReasons = problemExtractionReasons(document);
              return (
              <article key={document.id} className="document-card" data-document-id={document.id}>
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
                      {problemReasons.length ? (
                        <div className="problem-reasons" aria-label="Extraktionsprobleme">
                          {problemReasons.map((reason) => <span key={reason}>{reason}</span>)}
                        </div>
                      ) : null}
                      <AiSummaryPill rawResult={document.extraction?.raw_result} />
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
                    {document.extraction && document.status !== "review_approved" ? (
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => (
                          aiCheckingIds.includes(document.id)
                            ? cancelAiCheckDocument(document.id)
                            : aiCheckDocument(document)
                        )}
                        disabled={!aiCheckingIds.includes(document.id) && extractingIds.includes(document.id)}
                      >
                        {aiCheckingIds.includes(document.id) ? "KI abbrechen" : "KI prüfen"}
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
                              assignmentUnits={assignmentUnits}
                              isSaving={savingExtractionIds.includes(document.id)}
                              onSave={saveExtraction}
                            />
                            <AssignmentMatchNote rawResult={document.extraction.raw_result} tenantProfile={tenantProfile} />
                            <AiExtractionNote rawResult={document.extraction.raw_result} />

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
                            assignmentUnits={assignmentUnits}
                            highlightedLineNo={highlightedBookingTarget?.documentId === document.id ? highlightedBookingTarget.lineNo : ""}
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
          </>
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
        onOpenAccountingRules={openAccountingRulesFromApproval}
        onPrepareAccountingRule={prepareAccountingRuleFromApproval}
        onCreateAccountingRule={createAccountingRuleFromApproval}
        onPrepareAssignmentUnit={prepareAssignmentUnitFromApproval}
        onFixReviewIssue={focusBookingSuggestionFromApproval}
      />

      <ReviewFocusDialog
        document={focusedReviewDocument}
        tenantProfile={tenantProfile}
        isSavingExtraction={focusedReviewDocument ? savingExtractionIds.includes(focusedReviewDocument.id) : false}
        isSavingPayment={focusedReviewDocument ? savingPaymentIds.includes(focusedReviewDocument.id) : false}
        isSavingSuggestion={focusedReviewDocument ? savingSuggestionIds.includes(focusedReviewDocument.id) : false}
        isPreparingReview={focusedReviewDocument ? approvingIds.includes(focusedReviewDocument.id) : false}
        isAiChecking={focusedReviewDocument ? aiCheckingIds.includes(focusedReviewDocument.id) : false}
        hasPrevious={focusedReviewIndex > 0}
        hasNext={focusedReviewIndex >= 0 && focusedReviewIndex < focusableReviewDocuments.length - 1}
        positionLabel={focusedReviewPositionLabel}
        assignmentUnits={assignmentUnits}
        savingPaymentIds={savingPaymentIds}
        savingSuggestionIds={savingSuggestionIds}
        focusTarget={reviewFocusTarget?.documentId === focusedReviewDocumentId ? reviewFocusTarget : null}
        onClose={() => {
          setFocusedReviewDocumentId(null);
          setReviewFocusTarget(null);
        }}
        onPrevious={() => moveFocusedReview(-1)}
        onNext={() => moveFocusedReview(1)}
        onSaveExtraction={saveExtraction}
        onSaveExtractionAndPrepare={saveExtractionAndPrepareReview}
        onAiCheck={aiCheckDocument}
        onCancelAiCheck={cancelAiCheckDocument}
        onPrepareReview={prepareReview}
        onNextProblem={() => moveToNextProblemDocument(focusedReviewDocument?.id)}
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
          assignmentUnitDraft={assignmentUnitDraft}
          onAccountingRuleDraftConsumed={clearAccountingRuleDraft}
          onAccountingRuleEditTargetConsumed={clearAccountingRuleEditTarget}
          onAccountingRuleSaved={returnToApprovalAfterAccountingRule}
          onAssignmentUnitDraftConsumed={clearAssignmentUnitDraft}
          onAssignmentUnitSaved={returnToApprovalAfterAssignmentUnit}
          onProfileSaved={(profile) => {
            setTenantProfile(profile);
            loadAssignmentUnits();
          }}
        />
      ) : null}

      {activeView === "projects" && user?.role === "admin" ? (
        <ProjectsAdmin
          apiFetch={apiFetch}
          tenantId={activeTenantId}
          tenantProfile={tenantProfile}
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

function ProjectsAdmin({ apiFetch, tenantId, tenantProfile }) {
  const [assignmentUnits, setAssignmentUnits] = useState([]);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState("notice");
  const [isLoading, setIsLoading] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortConfig, setSortConfig] = useState({ key: "project_number", direction: "asc" });

  const loadProjects = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await apiFetch(`/masterdata/assignment-units?tenant_id=${encodeURIComponent(tenantId)}`);
      if (!response.ok) {
        const apiError = await readApiError(response, "Projekte konnten nicht geladen werden");
        throw new Error(apiError.message);
      }
      const result = await response.json();
      setAssignmentUnits(result.assignment_units ?? []);
    } catch (error) {
      setMessageTone("error");
      setMessage(error.message || "Projekte konnten nicht geladen werden.");
    } finally {
      setIsLoading(false);
    }
  }, [apiFetch, tenantId]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  async function syncPartnerProjects() {
    if (!window.confirm("Alle Projektstammdaten aus der Partner-App abrufen und lokale Projektdaten aktualisieren?")) {
      return;
    }
    setIsSyncing(true);
    setMessage("");
    try {
      const response = await apiFetch(`/masterdata/assignment-units/import-partner?tenant_id=${encodeURIComponent(tenantId)}`, {
        method: "POST",
      });
      if (!response.ok) {
        const apiError = await readApiError(response, "Projektstammdaten konnten nicht synchronisiert werden");
        throw new Error(apiError.message);
      }
      const result = await response.json();
      await loadProjects();
      setMessageTone("notice");
      setMessage(
        `Partner-App gelesen: ${result.source_count ?? result.synced_count ?? 0} Projekte, ` +
        `${result.synced_count ?? 0} lokal synchronisiert.`,
      );
    } catch (error) {
      setMessageTone("error");
      setMessage(error.message || "Projektstammdaten konnten nicht synchronisiert werden.");
    } finally {
      setIsSyncing(false);
    }
  }

  const projectKinds = useMemo(
    () => Array.from(new Set(assignmentUnits.map((project) => project.kind || "cost_object"))).sort(),
    [assignmentUnits],
  );
  const filteredProjects = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return assignmentUnits.filter((project) => {
      if (kindFilter !== "all" && project.kind !== kindFilter) return false;
      if (statusFilter === "active" && !project.is_active) return false;
      if (statusFilter === "inactive" && project.is_active) return false;
      if (!needle) return true;
      const haystack = [
        project.code,
        project.project_number,
        project.order_number,
        project.customer_number,
        project.label,
        project.description,
        project.client_name,
        project.source_status,
        project.address_line,
        project.postal_code,
        project.city,
        project.external_id,
        ...(project.aliases || []),
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(needle);
    });
  }, [assignmentUnits, kindFilter, search, statusFilter]);
  const sortedProjects = useMemo(() => {
    const direction = sortConfig.direction === "desc" ? -1 : 1;
    return [...filteredProjects].sort((left, right) => {
      const leftValue = projectSortValue(left, sortConfig.key, tenantProfile);
      const rightValue = projectSortValue(right, sortConfig.key, tenantProfile);
      return compareProjectValues(leftValue, rightValue) * direction;
    });
  }, [filteredProjects, sortConfig, tenantProfile]);
  const activeCount = assignmentUnits.filter((project) => project.is_active).length;
  const inactiveCount = assignmentUnits.length - activeCount;
  const withProjectNumber = assignmentUnits.filter((project) => project.project_number).length;
  function changeProjectSort(key) {
    setSortConfig((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  return (
    <section className="admin-panel project-page">
      <div className="section-header">
        <div>
          <p className="eyebrow">Partner-App und Zuordnungen</p>
          <h2>Projekte</h2>
        </div>
        <span className="tenant-chip">{tenantId}</span>
      </div>
      {message ? <p className={messageTone}>{message}</p> : null}

      <section className="project-overview">
        <Metric label="Gesamt" value={assignmentUnits.length} />
        <Metric label="Aktiv" value={activeCount} />
        <Metric label="Inaktiv" value={inactiveCount} />
        <Metric label="Mit Projektnummer" value={withProjectNumber} />
        <Metric label="Sichtbar" value={filteredProjects.length} />
      </section>

      <section className="admin-card project-list-card">
        <div className="card-header">
          <div>
            <p className="eyebrow">Projektliste</p>
            <h3>{tenantProfile.assignment_label_plural}</h3>
          </div>
          <div className="header-actions">
            <button type="button" onClick={syncPartnerProjects} disabled={isSyncing}>
              {isSyncing ? "Synchronisiere..." : "Partner-App synchronisieren"}
            </button>
            <button className="secondary-button" type="button" onClick={loadProjects} disabled={isLoading}>
              {isLoading ? "Lade..." : "Aktualisieren"}
            </button>
          </div>
        </div>

        <div className="project-toolbar">
          <label>
            Suche
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Projekt, Nummer, Adresse, Alias"
            />
          </label>
          <label>
            Art
            <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}>
              <option value="all">Alle Arten</option>
              {projectKinds.map((kind) => (
                <option key={kind} value={kind}>{formatAssignmentKind(kind, tenantProfile)}</option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">Alle Status</option>
              <option value="active">Aktiv</option>
              <option value="inactive">Inaktiv / abgeschlossen</option>
            </select>
          </label>
        </div>

        {sortedProjects.length ? (
          <div className="project-table">
            <div className="project-row project-head">
              <ProjectSortHeader label="Projekt-Nr." sortKey="project_number" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Auftragsnr." sortKey="order_number" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Kundennr." sortKey="customer_number" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Projektname" sortKey="label" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Adresse" sortKey="address" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Beschreibung" sortKey="description" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Bauherr" sortKey="client_name" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Art" sortKey="kind" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Aliase" sortKey="aliases" sortConfig={sortConfig} onSort={changeProjectSort} />
              <ProjectSortHeader label="Status" sortKey="status" sortConfig={sortConfig} onSort={changeProjectSort} />
            </div>
            {sortedProjects.map((project) => (
              <div className="project-row" key={project.id}>
                <strong>{project.project_number || "-"}</strong>
                <span>{project.order_number || "-"}</span>
                <span>{project.customer_number || "-"}</span>
                <span>{project.label}</span>
                <span>{formatAssignmentAddress(project)}</span>
                <span>{project.description || "-"}</span>
                <span>{project.client_name || "-"}</span>
                <span>{formatAssignmentKind(project.kind, tenantProfile)}</span>
                <span>{project.aliases?.length ? project.aliases.join(", ") : "-"}</span>
                <StatusPill value={formatProjectStatus(project)} tone={project.is_active ? "green" : "gray"} />
              </div>
            ))}
          </div>
        ) : (
          <p className="empty">
            {isLoading ? "Projekte werden geladen ..." : "Keine Projekte für diese Auswahl gefunden."}
          </p>
        )}
      </section>
    </section>
  );
}

function ProjectSortHeader({ label, sortKey, sortConfig, onSort }) {
  const isActive = sortConfig.key === sortKey;
  return (
    <button
      className={`project-sort-button${isActive ? " active" : ""}`}
      type="button"
      onClick={() => onSort(sortKey)}
      aria-sort={isActive ? (sortConfig.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <span>{label}</span>
      <span aria-hidden="true">{isActive ? (sortConfig.direction === "asc" ? "↑" : "↓") : "↕"}</span>
    </button>
  );
}

function projectSortValue(project, key, tenantProfile) {
  if (key === "address") return formatAssignmentAddress(project);
  if (key === "aliases") return project.aliases?.join(", ") || "";
  if (key === "kind") return formatAssignmentKind(project.kind, tenantProfile);
  if (key === "status") return formatProjectStatus(project);
  return project[key] ?? "";
}

function compareProjectValues(left, right) {
  const leftText = String(left || "").trim();
  const rightText = String(right || "").trim();
  if (!leftText && rightText) return 1;
  if (leftText && !rightText) return -1;
  return leftText.localeCompare(rightText, "de-DE", { numeric: true, sensitivity: "base" });
}

function formatAssignmentPickerLabel(assignment) {
  return [
    assignment.project_number,
    assignment.review_code,
    assignment.address_line,
    assignment.is_active === false ? "abgeschlossen" : null,
  ].filter(Boolean).join(" · ");
}

function formatAssignmentPickerDetails(assignment) {
  return [
    assignment.review_code,
    assignment.project_number,
    assignment.address_line,
    assignment.client_name,
    assignment.is_active === false ? "abgeschlossen" : null,
  ].filter(Boolean).join(", ");
}

function assignmentMatchesSearch(assignment, needle) {
  return [
    assignment.project_number,
    assignment.review_code,
    assignment.label,
    assignment.address_line,
    assignment.postal_code,
    assignment.city,
    assignment.client_name,
    assignment.customer_number,
    assignment.order_number,
    assignment.description,
    assignment.is_active === false ? "abgeschlossen inaktiv" : "aktiv",
    ...(assignment.aliases || []),
  ].filter(Boolean).join(" ").toLowerCase().includes(needle);
}

function BulkJobHistory({ jobs, onCancel }) {
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
              <BulkJobSummary summary={job.summary} />
              {job.error ? <p className="job-error">{job.error}</p> : null}
              {["queued", "running"].includes(job.status) ? (
                <button type="button" className="secondary compact" onClick={() => onCancel?.(job)}>
                  Abbrechen
                </button>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function BulkJobSummary({ summary }) {
  if (!summary?.analyzed_count) return null;
  const before = summary.before || {};
  const after = summary.after || {};
  const improved = summary.improved_count || 0;
  const regressed = summary.regressed_count || 0;
  const remaining = summary.remaining_problem_count || 0;
  return (
    <div className="job-summary">
      <div>
        <span>Allgemeine Kosten</span>
        <strong>{before.general_cost || 0}{" -> "}{after.general_cost || 0}</strong>
      </div>
      <div>
        <span>Zuordnung ungeklärt</span>
        <strong>{before.assignment_unresolved || 0}{" -> "}{after.assignment_unresolved || 0}</strong>
      </div>
      <div>
        <span>Zuordnung prüfen</span>
        <strong>{before.assignment_review || 0}{" -> "}{after.assignment_review || 0}</strong>
      </div>
      <div>
        <span>Verbessert</span>
        <strong>{improved}</strong>
      </div>
      <div>
        <span>Restproblem</span>
        <strong>{remaining}</strong>
      </div>
      {summary.ai_applied_count !== undefined ? (
        <div>
          <span>KI übernommen</span>
          <strong>{summary.ai_applied_count || 0}</strong>
        </div>
      ) : null}
      {summary.ai_no_changes_count !== undefined ? (
        <div>
          <span>KI ohne Änderung</span>
          <strong>{summary.ai_no_changes_count || 0}</strong>
        </div>
      ) : null}
      {summary.ai_failed_count ? (
        <div className="job-summary-warning">
          <span>KI fehlgeschlagen</span>
          <strong>{summary.ai_failed_count}</strong>
        </div>
      ) : null}
      {regressed ? (
        <div className="job-summary-warning">
          <span>Verschlechtert</span>
          <strong>{regressed}</strong>
        </div>
      ) : null}
      {summary.remaining_by_supplier?.length ? (
        <div className="job-summary-wide">
          <span>Rest nach Lieferant</span>
          <strong>{formatSummaryBuckets(summary.remaining_by_supplier)}</strong>
        </div>
      ) : null}
      {summary.remaining_by_document_type?.length ? (
        <div className="job-summary-wide">
          <span>Rest nach Dokumenttyp</span>
          <strong>{formatSummaryBuckets(summary.remaining_by_document_type)}</strong>
        </div>
      ) : null}
    </div>
  );
}

function ProblemWorkboard({ items, activeReason, actionMessage, onSelect, onOpenFirst, onShowAll }) {
  if (!items.length) return null;
  const totalDocuments = new Set(items.flatMap((item) => item.documents.map((document) => document.id))).size;
  return (
    <section className="problem-workboard" aria-label="Problembelege abarbeiten">
      <div className="problem-workboard-head">
        <div>
          <span>Problem-Abarbeitung</span>
          <h3>Wichtigste Gruppen zuerst</h3>
        </div>
        <button type="button" className="secondary-button" onClick={onShowAll}>
          Alle Problembelege {totalDocuments}
        </button>
      </div>
      {actionMessage ? (
        <p className="problem-action-message">{actionMessage}</p>
      ) : null}
      <div className="problem-work-list">
        {items.map((item) => (
          <article key={item.reason} className={activeReason === item.reason ? "problem-work-item active" : "problem-work-item"}>
            <div className="problem-work-main">
              <span className={`problem-severity ${item.severity}`}>{item.severityLabel}</span>
              <h4>{item.reason}</h4>
              <p>{item.help}</p>
              {item.examples.length ? (
                <small>Beispiele: {item.examples.join(", ")}</small>
              ) : null}
            </div>
            <div className="problem-work-action">
              <strong>{item.count}</strong>
              <span>{item.action}</span>
              <button type="button" className="secondary-button" onClick={() => onSelect(item.reason)}>
                Anzeigen
              </button>
              <button type="button" onClick={() => onOpenFirst(item)}>
                Ersten bearbeiten
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ExtractionEditForm({
  document,
  tenantProfile,
  assignmentUnits = [],
  isSaving,
  isPreparingReview = false,
  canPrepareReview = false,
  onDirtyChange,
  onSave,
  onSaveAndPrepare,
}) {
  const [form, setForm] = useState(() => extractionFormFromDocument(document));
  const [assignmentSearch, setAssignmentSearch] = useState("");
  const [rememberSupplierRule, setRememberSupplierRule] = useState(false);
  const assignmentOptionRefs = useRef({});
  const baselineForm = useMemo(
    () => extractionFormFromDocument(document),
    [document.id, document.extraction?.updated_at],
  );
  const isDirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(baselineForm),
    [baselineForm, form],
  );
  const isApproved = document.status === "review_approved";
  const assignmentOptions = useMemo(
    () => assignmentUnits
      .map((assignment) => ({
        ...assignment,
        review_code: reviewAssignmentCode(assignment),
      }))
      .filter((assignment) => assignment.review_code || assignment.project_number)
      .sort((left, right) => {
        const inactiveCompare = Number(left.is_active === false) - Number(right.is_active === false);
        if (inactiveCompare !== 0) return inactiveCompare;
        return compareProjectValues(left.project_number || left.review_code, right.project_number || right.review_code);
      }),
    [assignmentUnits],
  );
  const selectedAssignment = useMemo(
    () => findAssignmentOption(assignmentOptions, "project_number", form.project_number)
      || findAssignmentOption(assignmentOptions, "assignment_code", form.assignment_code),
    [assignmentOptions, form.assignment_code, form.project_number],
  );
  const selectedAssignmentId = selectedAssignment?.id || "";
  const rawResult = document.extraction?.raw_result || {};
  const pdfTextDiagnostic = formatPdfTextDiagnostic(rawResult);
  const filteredAssignmentOptions = useMemo(() => {
    const needle = assignmentSearch.trim().toLowerCase();
    const matches = needle
      ? assignmentOptions.filter((assignment) => assignmentMatchesSearch(assignment, needle))
      : assignmentOptions;
    if (selectedAssignment && !matches.some((assignment) => assignment.id === selectedAssignment.id)) {
      return [selectedAssignment, ...matches];
    }
    return matches;
  }, [assignmentOptions, assignmentSearch, selectedAssignment]);

  useEffect(() => {
    setForm(baselineForm);
    setAssignmentSearch("");
    setRememberSupplierRule(false);
  }, [baselineForm]);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  useEffect(() => {
    const visibleIds = new Set(filteredAssignmentOptions.map((assignment) => assignment.id));
    Object.keys(assignmentOptionRefs.current).forEach((id) => {
      if (!visibleIds.has(id)) delete assignmentOptionRefs.current[id];
    });
  }, [filteredAssignmentOptions]);

  function updateField(field, value) {
    setForm((current) => {
      const next = { ...current, [field]: value };
      if (field === "assignment_code") {
        const assignment = findAssignmentOption(assignmentOptions, "assignment_code", value);
        if (assignment) {
          next.assignment_code = assignment.review_code || value;
          next.project_number = assignment.project_number || "";
          next.assignment_kind = assignment.kind || current.assignment_kind;
        }
      }
      if (field === "project_number") {
        const assignment = findAssignmentOption(assignmentOptions, "project_number", value);
        if (assignment) {
          next.project_number = assignment.project_number || value;
          next.assignment_code = assignment.review_code || "";
          next.assignment_kind = assignment.kind || current.assignment_kind;
        }
      }
      return next;
    });
  }

  function applyAssignmentSelection(assignmentId) {
    const assignment = assignmentOptions.find((option) => option.id === assignmentId);
    if (!assignment) return;
    setForm((current) => ({
      ...current,
      assignment_code: assignment.review_code || assignment.code || "",
      project_number: assignment.project_number || "",
      assignment_kind: assignment.kind || current.assignment_kind,
    }));
  }

  function focusAssignmentOption(index) {
    const assignment = filteredAssignmentOptions[index];
    if (!assignment) return;
    assignmentOptionRefs.current[assignment.id]?.focus();
  }

  function handleAssignmentKeyDown(event) {
    if (!filteredAssignmentOptions.length) return;
    const selectedIndex = filteredAssignmentOptions.findIndex((assignment) => assignment.id === selectedAssignmentId);
    const focusedIndex = filteredAssignmentOptions.findIndex((assignment) => assignmentOptionRefs.current[assignment.id] === window.document.activeElement);
    const currentIndex = focusedIndex >= 0 ? focusedIndex : (selectedIndex >= 0 ? selectedIndex : 0);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusAssignmentOption(focusedIndex >= 0 || selectedIndex >= 0 ? Math.min(currentIndex + 1, filteredAssignmentOptions.length - 1) : 0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusAssignmentOption(Math.max(currentIndex - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      applyAssignmentSelection(filteredAssignmentOptions[currentIndex].id);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setAssignmentSearch("");
    }
  }

  function submit(event) {
    event.preventDefault();
    onSave(document, { ...form, remember_supplier_rule: rememberSupplierRule });
  }

  function saveAndPrepare() {
    onSaveAndPrepare?.(document, { ...form, remember_supplier_rule: rememberSupplierRule });
  }

  return (
    <form className="extraction-edit-form" onSubmit={submit}>
      <div className="detail-section-header">
        <div>
          <h3>Extraktionsdaten</h3>
          <span>
            bearbeitbar vor Buchungsvorschlag und Freigabe
            {pdfTextDiagnostic ? ` · ${pdfTextDiagnostic}` : ""}
          </span>
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
          <input name="supplier_name" value={form.supplier_name} onChange={(event) => updateField("supplier_name", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Rechnung">
          <input name="invoice_number" value={form.invoice_number} onChange={(event) => updateField("invoice_number", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Datum">
          <input name="invoice_date" type="date" value={form.invoice_date} onChange={(event) => updateField("invoice_date", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Kunden-Nr.">
          <input name="customer_number" value={form.customer_number} onChange={(event) => updateField("customer_number", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Belegart">
          <select name="document_type" value={form.document_type} onChange={(event) => updateField("document_type", event.target.value)} disabled={isApproved}>
            <option value="incoming_invoice">Eingangsrechnung</option>
            <option value="credit_note">Gutschrift</option>
            <option value="fuel_receipt">Tankbeleg</option>
            <option value="project_document">Projektunterlage</option>
            <option value="tax_exemption_certificate">Freistellungsbescheinigung</option>
            <option value="reverse_charge_certificate">§13b-Nachweis</option>
          </select>
        </FormField>
        <FormField label="Kostenart">
          <select name="cost_category" value={form.cost_category} onChange={(event) => updateField("cost_category", event.target.value)} disabled={isApproved}>
            <option value="">-</option>
            {COST_CATEGORY_OPTIONS.map(([category, label]) => (
              <option key={category} value={category}>{label}</option>
            ))}
          </select>
        </FormField>
        <FormField label={`${tenantProfile.assignment_label_singular} aus Stammdaten`} className="assignment-picker-field">
          <input
            className="assignment-search-input"
            value={assignmentSearch}
            onChange={(event) => setAssignmentSearch(event.target.value)}
            onKeyDown={handleAssignmentKeyDown}
            placeholder="Projekt suchen: Nummer, Name, Adresse, Bauherr"
            disabled={isApproved || assignmentOptions.length === 0}
          />
          <div
            className="assignment-combobox"
            role="listbox"
            aria-label={`${tenantProfile.assignment_label_singular} auswählen`}
            onKeyDown={handleAssignmentKeyDown}
          >
            {filteredAssignmentOptions.length ? (
              filteredAssignmentOptions.map((assignment) => {
                const isSelected = selectedAssignmentId === assignment.id;
                return (
                  <button
                    type="button"
                    key={`assignment-picker-${assignment.id}`}
                    className={isSelected ? "selected" : ""}
                    onClick={() => applyAssignmentSelection(assignment.id)}
                    ref={(element) => {
                      if (element) assignmentOptionRefs.current[assignment.id] = element;
                    }}
                    disabled={isApproved}
                    role="option"
                    aria-selected={isSelected}
                  >
                    <strong>{assignment.review_code || assignment.label || assignment.project_number}</strong>
                    <span>{formatAssignmentPickerDetails(assignment)}</span>
                  </button>
                );
              })
            ) : (
              <p>{assignmentOptions.length ? "Keine passenden Projekte gefunden." : "Keine Stammdaten geladen."}</p>
            )}
          </div>
          <small>
            {assignmentOptions.length
              ? `${filteredAssignmentOptions.length} von ${assignmentOptions.length} Projekten sichtbar. Setzt Projektnr., ${tenantProfile.assignment_code_label} und Zuordnungsart gemeinsam.`
              : "Noch keine Projektstammdaten geladen."}
          </small>
        </FormField>
        <FormField label={tenantProfile.assignment_code_label}>
          <input name="assignment_code" list={`assignment-code-options-${document.id}`} placeholder="z.B. Wewe20" value={form.assignment_code} onChange={(event) => updateField("assignment_code", event.target.value)} disabled={isApproved} />
          <datalist id={`assignment-code-options-${document.id}`}>
            {assignmentOptions.map((assignment) => (
              <option key={`code-${assignment.id}`} value={assignment.review_code}>
                {formatAssignmentPickerDetails(assignment)}
              </option>
            ))}
          </datalist>
        </FormField>
        <FormField label="Projektnr.">
          <input name="project_number" list={`project-number-options-${document.id}`} placeholder="z.B. 26-00007" value={form.project_number} onChange={(event) => updateField("project_number", event.target.value)} disabled={isApproved} />
          <datalist id={`project-number-options-${document.id}`}>
            {assignmentOptions.filter((assignment) => assignment.project_number).map((assignment) => (
              <option key={`project-${assignment.id}`} value={assignment.project_number}>
                {formatAssignmentPickerDetails(assignment)}
              </option>
            ))}
          </datalist>
        </FormField>
        <FormField label="Zuordnungsart">
          <select name="assignment_kind" value={form.assignment_kind} onChange={(event) => updateField("assignment_kind", event.target.value)} disabled={isApproved}>
            <option value="">-</option>
            <AssignmentKindOptions />
          </select>
        </FormField>
        <FormField label="Netto">
          <input name="net_amount" inputMode="decimal" value={form.net_amount} onChange={(event) => updateField("net_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="USt">
          <input name="tax_amount" inputMode="decimal" value={form.tax_amount} onChange={(event) => updateField("tax_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Brutto">
          <input name="gross_amount" inputMode="decimal" value={form.gross_amount} onChange={(event) => updateField("gross_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Währung">
          <input name="currency" value={form.currency} onChange={(event) => updateField("currency", event.target.value.toUpperCase())} maxLength={3} disabled={isApproved} />
        </FormField>
        <FormField label="Zahlbar bis">
          <input name="due_date" type="date" value={form.due_date} onChange={(event) => updateField("due_date", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Skonto bis">
          <input name="discount_due_date" type="date" value={form.discount_due_date} onChange={(event) => updateField("discount_due_date", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Skonto-Basis">
          <input name="discount_base" inputMode="decimal" value={form.discount_base} onChange={(event) => updateField("discount_base", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Skonto">
          <input name="discount_amount" inputMode="decimal" value={form.discount_amount} onChange={(event) => updateField("discount_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Zahlbetrag Skonto">
          <input name="discounted_payable_amount" inputMode="decimal" value={form.discounted_payable_amount} onChange={(event) => updateField("discounted_payable_amount", event.target.value)} disabled={isApproved} />
        </FormField>
        <FormField label="Artikel / Leistung">
          <input name="item_summary" value={form.item_summary} onChange={(event) => updateField("item_summary", event.target.value)} disabled={isApproved} />
        </FormField>
      </div>
      {!isApproved ? (
        <label className="remember-rule-option">
          <input
            type="checkbox"
            checked={rememberSupplierRule}
            onChange={(event) => setRememberSupplierRule(event.target.checked)}
            disabled={isSaving || !form.supplier_name?.trim()}
          />
          <span>
            <strong>Für ähnliche Rechnungen merken</strong>
            <small>Speichert Lieferant, Kunden-Nr. und Kostenart als Regel. Kein Bauvorhaben wird an den Lieferanten gebunden.</small>
          </span>
        </label>
      ) : null}
      <div className="form-actions">
        <button type="submit" disabled={isSaving || isApproved}>
          {isApproved ? "Freigegeben" : isSaving ? "Speichert..." : "Speichern"}
        </button>
        {canPrepareReview && onSaveAndPrepare ? (
          <button
            type="button"
            className="secondary-button"
            onClick={saveAndPrepare}
            disabled={isSaving || isPreparingReview || isApproved}
          >
            {isPreparingReview ? "Erstellt..." : "Speichern + Vorschlag neu"}
          </button>
        ) : null}
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

function AiExtractionNote({ rawResult }) {
  const ai = rawResult?.ai_extraction;
  if (!ai) return null;

  const acceptedFields = Array.isArray(ai.accepted_fields) ? ai.accepted_fields.filter(Boolean) : [];
  const evidence = Array.isArray(ai.evidence) ? ai.evidence.filter(Boolean) : [];
  const warnings = Array.isArray(ai.warnings) ? ai.warnings.filter(Boolean) : [];
  const confidence = Number(ai.confidence);
  const statusLabel = {
    applied: "KI angewendet",
    no_changes: "KI geprüft",
    failed: "KI fehlgeschlagen",
  }[ai.status] || "KI geprüft";
  const tone = ai.status === "failed" ? "warning" : ai.status === "applied" ? "blue" : "neutral";

  return (
    <div className={`ai-extraction-note ${tone}`}>
      <div>
        <strong>{statusLabel}</strong>
        {ai.model ? <span>{ai.model}</span> : null}
        {!Number.isNaN(confidence) ? <span>{Math.round(confidence * 100)} %</span> : null}
      </div>
      {acceptedFields.length ? <p>Übernommen: {acceptedFields.map(formatAiFieldLabel).join(", ")}</p> : null}
      {evidence.length ? (
        <ul>
          {evidence.slice(0, 3).map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : null}
      {warnings.length ? <p>{warnings.join(" · ")}</p> : null}
    </div>
  );
}

function AiSummaryPill({ rawResult }) {
  const ai = rawResult?.ai_extraction;
  if (!ai) return null;

  const acceptedFields = Array.isArray(ai.accepted_fields) ? ai.accepted_fields.filter(Boolean) : [];
  const statusText = {
    applied: acceptedFields.length
      ? `KI übernommen: ${acceptedFields.slice(0, 3).map(formatAiFieldLabel).join(", ")}`
      : "KI übernommen",
    no_changes: "KI geprüft: keine Änderung",
    failed: `KI Fehler${ai.error ? `: ${String(ai.error).slice(0, 80)}` : ""}`,
  }[ai.status] || "KI geprüft";
  const visionText = ai.used_vision ? "Bildprüfung" : null;

  return (
    <div className="ai-summary-pills" aria-label="KI-Prüfung Ergebnis">
      <span className={`ai-summary-pill ${ai.status || "checked"}`}>{statusText}</span>
      {visionText ? <span className="ai-summary-pill vision">{visionText}</span> : null}
    </div>
  );
}

function formatAiFieldLabel(field) {
  const labels = {
    supplier_name: "Lieferant",
    invoice_number: "Rechnungsnummer",
    invoice_date: "Datum",
    customer_number: "Kunden-Nr.",
    document_type: "Belegart",
    cost_category: "Kostenart",
    assignment_code: "Zuordnung",
    assignment_kind: "Zuordnungsart",
    project_number: "Projekt-Nr.",
    net_amount: "Netto",
    tax_amount: "USt",
    gross_amount: "Brutto",
    due_date: "Zahlbar bis",
    discount_due_date: "Skonto bis",
    discount_base: "Skonto-Basis",
    discount_amount: "Skonto",
    discounted_payable_amount: "Zahlbetrag Skonto",
    item_summary: "Artikel/Leistung",
  };
  return labels[field] || field;
}

function AssignmentMatchNote({ rawResult, tenantProfile }) {
  const match = rawResult?.assignment_match;
  if (!match) return null;
  const label = [match.project_number, match.label || match.code].filter(Boolean).join(" / ");
  const reasons = Array.isArray(match.reasons) ? match.reasons.filter(Boolean) : [];
  const needsReview = assignmentMatchNeedsReview(match);
  return (
    <div className={needsReview ? "match-note needs-review" : "match-note"}>
      <strong>{tenantProfile.assignment_label_singular} erkannt: {label || "-"}</strong>
      <span>
        {[match.source ? `Quelle: ${match.source}` : null, match.score ? `Score: ${match.score}` : null]
          .filter(Boolean)
          .join(" · ")}
      </span>
      {reasons.length ? <small>Treffer über {reasons.join(", ")}</small> : null}
      {needsReview ? <em>Bitte prüfen: indirekter oder knapper Stammdaten-Treffer.</em> : null}
    </div>
  );
}

function assignmentMatchNeedsReview(match) {
  if (!match) return false;
  const score = Number(match.score);
  return match.source === "Projektstammdaten-Abgleich" || (!Number.isNaN(score) && score < 120);
}

function isPdfDocument(document) {
  const contentType = String(document?.content_type || "").split(";", 1)[0].trim().toLowerCase();
  return contentType === "application/pdf" || String(document?.original_filename || "").toLowerCase().endsWith(".pdf");
}

function DocumentPreview({ document }) {
  const fileUrl = apiUrl(`/documents/${document.id}/file?disposition=inline`);
  const contentType = document.content_type || "";
  const isImage = contentType.startsWith("image/");
  const isPdf = contentType === "application/pdf" || String(document.original_filename || "").toLowerCase().endsWith(".pdf");
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
  assignmentUnits = [],
  isSavingExtraction,
  isSavingPayment,
  isSavingSuggestion,
  isPreparingReview,
  isAiChecking,
  hasPrevious,
  hasNext,
  positionLabel,
  savingPaymentIds,
  savingSuggestionIds,
  focusTarget,
  onClose,
  onPrevious,
  onNext,
  onSaveExtraction,
  onSaveExtractionAndPrepare,
  onAiCheck,
  onCancelAiCheck,
  onPrepareReview,
  onNextProblem,
  onSelectPayment,
  onSaveSuggestion,
}) {
  const dialogRef = useRef(null);
  const [hasUnsavedExtractionChanges, setHasUnsavedExtractionChanges] = useState(false);
  const [navigationWarning, setNavigationWarning] = useState("");
  const canCreateReviewSuggestion = document?.extraction
    && (!document.booking_suggestions?.length || (document.status !== "review_ready" && document.status !== "review_approved"));
  const hasProblemFlow = Boolean(focusTarget?.reason);
  const isBusy = isSavingExtraction || isSavingPayment || isSavingSuggestion || isPreparingReview || isAiChecking;

  useEffect(() => {
    setHasUnsavedExtractionChanges(false);
    setNavigationWarning("");
  }, [document?.id]);

  useEffect(() => {
    if (!document || !focusTarget) return undefined;
    const timer = window.setTimeout(() => {
      const sectionSelector = focusTarget.lineNo
        ? `[data-booking-line="${focusTarget.lineNo}"]`
        : `[data-review-section="${focusTarget.target}"]`;
      const section = dialogRef.current?.querySelector(sectionSelector);
      section?.scrollIntoView({ behavior: "smooth", block: "center" });
      const fieldSelector = focusTarget.field
        ? `[name="${focusTarget.field}"], [data-field="${focusTarget.field}"]`
        : "input:not([disabled]), select:not([disabled]), button:not([disabled])";
      const focusable = section?.querySelector?.(fieldSelector)
        || section?.querySelector?.("input:not([disabled]), select:not([disabled]), button:not([disabled])");
      focusable?.focus?.({ preventScroll: true });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [document?.id, focusTarget]);

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
            {canCreateReviewSuggestion ? (
              <button
                type="button"
                onClick={() => onPrepareReview(document)}
                disabled={isBusy || hasUnsavedExtractionChanges}
                title={hasUnsavedExtractionChanges ? "Bitte erst Extraktionsdaten speichern." : ""}
              >
                {isPreparingReview ? "Erstellt..." : document.booking_suggestions?.length ? "Vorschlag neu" : "Vorschlag"}
              </button>
            ) : null}
            {document?.extraction && document.status !== "review_approved" ? (
              <button
                className="secondary-button"
                type="button"
                onClick={() => (isAiChecking ? onCancelAiCheck(document.id) : onAiCheck(document))}
                disabled={(!isAiChecking && isBusy) || hasUnsavedExtractionChanges}
                title={hasUnsavedExtractionChanges ? "Bitte erst Extraktionsdaten speichern." : ""}
              >
                {isAiChecking ? "KI abbrechen" : "KI prüfen"}
              </button>
            ) : null}
            {hasProblemFlow ? (
              <button className="secondary-button" type="button" onClick={onNextProblem} disabled={isBusy || hasUnsavedExtractionChanges}>
                Nächstes Problem
              </button>
            ) : null}
            <button className="secondary-button" type="button" onClick={requestNext} disabled={isBusy || !hasNext}>
              Nächster
            </button>
            <button className="secondary-button review-focus-close" type="button" onClick={requestClose} disabled={isBusy}>
              Schließen
            </button>
          </div>
        </header>
        {navigationWarning ? <p className="inline-note review-focus-warning">{navigationWarning}</p> : null}

        {focusTarget?.message ? (
          <p className="quick-fix-note">
            <strong>{focusTarget.reason || "Korrektur"}:</strong> {focusTarget.message}
          </p>
        ) : null}

        <div className="review-focus-body">
          <div data-review-section="preview">
            <DocumentPreview document={document} />
          </div>
          <div className="review-focus-data">
            <div data-review-section="extraction">
              <ExtractionEditForm
                document={document}
                tenantProfile={tenantProfile}
                assignmentUnits={assignmentUnits}
                isSaving={isSavingExtraction}
                isPreparingReview={isPreparingReview}
                canPrepareReview={canCreateReviewSuggestion}
                onDirtyChange={(isDirty) => {
                  setHasUnsavedExtractionChanges(isDirty);
                  if (!isDirty) setNavigationWarning("");
                }}
                onSave={onSaveExtraction}
                onSaveAndPrepare={onSaveExtractionAndPrepare}
              />
            </div>
            <AssignmentMatchNote rawResult={document.extraction.raw_result} tenantProfile={tenantProfile} />
            <AiExtractionNote rawResult={document.extraction.raw_result} />
            {document.extraction?.warnings?.length ? (
              <ul className="warnings" data-review-section="warnings">
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
            assignmentUnits={assignmentUnits}
            highlightedLineNo={focusTarget?.lineNo || ""}
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
  onOpenAccountingRules,
  onPrepareAccountingRule,
  onCreateAccountingRule,
  onPrepareAssignmentUnit,
  onFixReviewIssue,
}) {
  const dialogRef = useRef(null);
  const [inlineAccountingIssue, setInlineAccountingIssue] = useState(null);
  const [inlineAccountingForm, setInlineAccountingForm] = useState(null);
  const [inlineAccountingErrors, setInlineAccountingErrors] = useState({});
  const [inlineAccountingMessage, setInlineAccountingMessage] = useState("");
  const [isSavingInlineAccountingRule, setIsSavingInlineAccountingRule] = useState(false);

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

  useEffect(() => {
    setInlineAccountingIssue(null);
    setInlineAccountingForm(null);
    setInlineAccountingErrors({});
    setInlineAccountingMessage("");
    setIsSavingInlineAccountingRule(false);
  }, [document?.id]);

  if (!document) return null;

  const extraction = document.extraction || {};
  const rawResult = extraction.raw_result || {};
  const suggestions = document.booking_suggestions || [];
  const payment = approvalPaymentSummary(document);
  const paymentTerms = paymentTermLinesForDocument(document);
  const requiresPaymentDecision = paymentTerms.length > 1 && !document.payment_decision;
  const accountingRuleIssues = (issues || []).filter((issue) =>
    ["missing_accounting_rule", "ambiguous_accounting_rule", "incomplete_accounting_rule", "missing_discount_account"].includes(issue.code),
  );
  const assignmentIssues = dedupeReviewCorrectionIssues((issues || []).filter((issue) => isAssignmentIssue(issue)));
  const exportValidationIssues = (issues || []).filter((issue) => issue.code === "export_validation");
  const approvalIssueGroups = groupedApprovalIssues(issues || []);
  const correctionIssues = dedupeReviewCorrectionIssues((issues || []).filter((issue) =>
    !accountingRuleIssues.includes(issue) && !assignmentIssues.includes(issue) && issue.code !== "export_validation" && issue.category !== "status",
  ));
  const missingAccountingRuleIssues = accountingRuleIssues.filter((issue) => issue.code === "missing_accounting_rule");
  const ambiguousAccountingRuleIssues = accountingRuleIssues.filter((issue) => issue.code === "ambiguous_accounting_rule");
  const editableAccountingRuleIssues = accountingRuleIssues.filter((issue) =>
    !["missing_accounting_rule", "ambiguous_accounting_rule"].includes(issue.code),
  );
  const hasAccountingRuleActions = Boolean(missingAccountingRuleIssues.length || editableAccountingRuleIssues.length);
  const showGenericApprovalError = Boolean(error)
    && !accountingRuleIssues.length
    && !assignmentIssues.length
    && !exportValidationIssues.length
    && !correctionIssues.length;
  const totalNet = suggestions.reduce((sum, suggestion) => sum + numberOrZero(suggestion.net_amount), 0);
  const totalTax = suggestions.reduce((sum, suggestion) => sum + numberOrZero(suggestion.tax_amount), 0);
  const totalGross = suggestions.reduce((sum, suggestion) => sum + numberOrZero(suggestion.gross_amount), 0);
  const accountingRuleFixHint = ambiguousAccountingRuleIssues.length
    ? "Mehrere Regeln passen gleich gut. Bitte die Regeln unter Stammdaten eindeutiger machen."
    : canPrepareAccountingRule
      ? missingAccountingRuleIssues.length
        ? "Die App kann die passende Regel vorbereiten. Konten müssen danach fachlich ergänzt werden."
        : "Die bestehende Regel muss unter Stammdaten bearbeitet werden."
      : "Bitte einen Admin bitten, die passende Regel unter Stammdaten anzulegen.";
  const activeAccountingFramework = accountingFramework(tenantProfile?.accounting_framework);
  const inlineDebitSuggestions = accountSuggestions(activeAccountingFramework, "debit", inlineAccountingForm?.cost_category);
  const inlineCreditSuggestions = accountSuggestions(activeAccountingFramework, "credit", inlineAccountingForm?.cost_category);
  const inlineDiscountSuggestions = accountSuggestions(activeAccountingFramework, "discount", inlineAccountingForm?.cost_category);

  function startInlineAccountingRule(issue) {
    setInlineAccountingIssue(issue);
    setInlineAccountingForm(accountingRuleFormFromApprovalIssue(issue, document));
    setInlineAccountingErrors({});
    setInlineAccountingMessage("");
  }

  function updateInlineAccountingField(field, value) {
    setInlineAccountingForm((current) => ({ ...(current || {}), [field]: value }));
    setInlineAccountingErrors((current) => ({ ...current, [field]: "" }));
    setInlineAccountingMessage("");
  }

  async function submitInlineAccountingRule(event) {
    event.preventDefault();
    if (!inlineAccountingForm || !inlineAccountingIssue || !onCreateAccountingRule) return;
    const errorsByField = validateAccountingRuleForm(inlineAccountingForm);
    setInlineAccountingErrors(errorsByField);
    setInlineAccountingMessage("");
    if (Object.keys(errorsByField).length) return;

    setIsSavingInlineAccountingRule(true);
    try {
      await onCreateAccountingRule(inlineAccountingForm, document.id);
    } catch (saveError) {
      setInlineAccountingErrors(saveError.fields || {});
      setInlineAccountingMessage(saveError.message || "Kontierungsregel konnte nicht angelegt werden.");
    } finally {
      setIsSavingInlineAccountingRule(false);
    }
  }

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
        {approvalIssueGroups.length ? (
          <div className="approval-issue-summary" aria-label="Freigabe-Ursachen">
            {approvalIssueGroups.map((group) => (
              <div className={`approval-issue-chip ${group.severity}`} key={group.key}>
                <strong>{group.label}</strong>
                <span>{group.count}</span>
                <small>{group.help}</small>
              </div>
            ))}
          </div>
        ) : null}
        {showGenericApprovalError ? <p className="approval-blocker">{error}</p> : null}

        {correctionIssues.length ? (
          <div className="approval-correction-panel">
            <div>
              <strong>Direkt korrigieren</strong>
              <span>Zum passenden Bereich im großen Prüffenster springen.</span>
            </div>
            <div className="approval-correction-actions">
              {correctionIssues.map((issue, index) => (
                <button
                  className="secondary-button compact-button"
                  type="button"
                  key={`${issue.code || "issue"}-${issue.line_no || ""}-${issue.field || ""}-${index}`}
                  onClick={() => onFixReviewIssue(issue)}
                >
                  {reviewCorrectionButtonLabel(issue)}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {assignmentIssues.length ? (
          <div className="approval-assignment-panel">
            <div>
              <strong>Zuordnung prüfen</strong>
              <span>Fehlende Zuordnung wird in der Buchungszeile ergänzt. Unbekannte Codes werden in Stammdaten angelegt.</span>
            </div>
            <div className="approval-assignment-actions">
              {assignmentIssues.map((issue, index) => (
                <div className="approval-rule-action-cluster" key={`${issue.code || "assignment"}-${issue.line_no || ""}-${issue.assignment_code || ""}-${index}`}>
                  <span>{assignmentIssueContext(issue, tenantProfile)}</span>
                  <div>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => onFixReviewIssue({ ...issue, target: "booking_lines", action: "edit_booking_line" })}
                    >
                      Buchungszeile öffnen
                    </button>
                    {issue.code === "unknown_assignment" || issue.assignment_hint || issue.target === "assignment_units" ? (
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => onPrepareAssignmentUnit(issue)}
                      >
                        In Stammdaten anlegen
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {accountingRuleIssues.length ? (
          <div className="approval-fix-panel">
            <div>
              <strong>{accountingRuleFixTitle(accountingRuleIssues)}</strong>
              <span>{accountingRuleFixHint}</span>
            </div>
            {ambiguousAccountingRuleIssues.length ? (
              <div className="approval-fix-list-wrap">
                <ul className="approval-fix-list">
                  {ambiguousAccountingRuleIssues.map((issue, index) => {
                    const matchingRules = Array.isArray(issue.matching_rules) ? issue.matching_rules : [];
                    return (
                      <li key={`${issue.line_no || index}-${issue.cost_category || ""}`}>
                        <strong>Zeile {issue.line_no || "?"}</strong>
                        <span>{accountingRuleIssueContext(issue) || "Mehrere Kontierungsregeln passen gleich gut."}</span>
                        {matchingRules.length ? (
                          <div className="approval-rule-matches">
                            {matchingRules.map((rule, ruleIndex) => (
                              <button
                                className="secondary-button compact-button"
                                type="button"
                                key={`${rule.id || rule.rule_id || rule.name || ruleIndex}-${issue.line_no || index}`}
                                onClick={() => onPrepareAccountingRule({
                                  ...issue,
                                  accounting_rule_id: rule.id || rule.rule_id || issue.accounting_rule_id || "",
                                  accounting_rule_name: rule.name || issue.accounting_rule_name || "",
                                  supplier_name: issue.supplier_name || rule.supplier_name || "",
                                  cost_category: issue.cost_category || rule.cost_category || "",
                                })}
                                disabled={!canPrepareAccountingRule || !(rule.id || rule.rule_id)}
                              >
                                {accountingRuleMatchLabel(rule)}
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
                {canPrepareAccountingRule ? (
                  <button className="secondary-button compact-button" type="button" onClick={onOpenAccountingRules}>
                    Alle Regeln öffnen
                  </button>
                ) : null}
              </div>
            ) : null}
            {canPrepareAccountingRule && hasAccountingRuleActions ? (
              <div className="approval-fix-actions">
                {dedupeAccountingRuleIssues(missingAccountingRuleIssues).map((issue) => {
                  const isBlockedByMissingCostCategory = issue.field === "cost_category" && !issue.cost_category;
                  return (
                    <div className="approval-rule-action-cluster" key={`${issue.supplier_name || "-"}-${issue.cost_category || ""}-${issue.code}`}>
                      <span>{accountingRuleIssueContext(issue) || "Kontierungsregel fehlt."}</span>
                      <div>
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => startInlineAccountingRule(issue)}
                          disabled={isBlockedByMissingCostCategory}
                        >
                          Direkt anlegen
                        </button>
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => onPrepareAccountingRule(issue)}
                          disabled={isBlockedByMissingCostCategory}
                        >
                          In Stammdaten öffnen
                        </button>
                      </div>
                    </div>
                  );
                })}
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
            {canPrepareAccountingRule && inlineAccountingForm ? (
              <form className="approval-rule-form" onSubmit={submitInlineAccountingRule}>
                <div className="approval-rule-form-head">
                  <div>
                    <strong>Kontierungsregel direkt anlegen</strong>
                    <span>{accountingRuleIssueContext(inlineAccountingIssue)}</span>
                  </div>
                  <button
                    className="secondary-button compact-button"
                    type="button"
                    onClick={() => onPrepareAccountingRule(inlineAccountingIssue)}
                  >
                    In Stammdaten öffnen
                  </button>
                </div>
                {inlineAccountingMessage ? <p className="field-error">{inlineAccountingMessage}</p> : null}
                <div className="approval-rule-suggestion-bar">
                  <span>Kontenvorschläge aus {activeAccountingFramework}</span>
                  <button
                    className="secondary-button compact-button"
                    type="button"
                    onClick={() => {
                      setInlineAccountingForm((current) => applyAccountingSuggestions(current || {}, tenantProfile));
                      setInlineAccountingErrors((current) => ({
                        ...current,
                        debit_account: "",
                        credit_account: "",
                        discount_account: "",
                        tax_rate: "",
                      }));
                    }}
                  >
                    Leere Konten vorschlagen
                  </button>
                </div>
                <div className="approval-rule-grid">
                  <FormField label="Regelname" error={inlineAccountingErrors.name}>
                    <input
                      type="text"
                      value={inlineAccountingForm.name || ""}
                      onChange={(event) => updateInlineAccountingField("name", event.target.value)}
                    />
                  </FormField>
                  <FormField label="Erkennung" error={inlineAccountingErrors.supplier_match_text}>
                    <input
                      type="text"
                      value={inlineAccountingForm.supplier_match_text || ""}
                      onChange={(event) => updateInlineAccountingField("supplier_match_text", event.target.value)}
                    />
                  </FormField>
                  <FormField label="Kostenart" error={inlineAccountingErrors.cost_category}>
                    <select
                      value={inlineAccountingForm.cost_category || ""}
                      onChange={(event) => updateInlineAccountingField("cost_category", event.target.value)}
                    >
                      <option value="">Alle Kostenarten</option>
                      {COST_CATEGORY_OPTIONS.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </FormField>
                  <FormField label="Aufwandskonto" error={inlineAccountingErrors.debit_account}>
                    <input
                      list="approval-accounting-debit-options"
                      type="text"
                      value={inlineAccountingForm.debit_account || ""}
                      onChange={(event) => updateInlineAccountingField("debit_account", event.target.value)}
                    />
                  </FormField>
                  <FormField label="Gegenkonto" error={inlineAccountingErrors.credit_account}>
                    <input
                      list="approval-accounting-credit-options"
                      type="text"
                      value={inlineAccountingForm.credit_account || ""}
                      onChange={(event) => updateInlineAccountingField("credit_account", event.target.value)}
                    />
                  </FormField>
                  <FormField label="Steuerschlüssel" error={inlineAccountingErrors.tax_key}>
                    <input
                      type="text"
                      value={inlineAccountingForm.tax_key || ""}
                      onChange={(event) => updateInlineAccountingField("tax_key", event.target.value)}
                    />
                  </FormField>
                  <FormField label="Steuersatz" error={inlineAccountingErrors.tax_rate}>
                    <input
                      type="text"
                      value={inlineAccountingForm.tax_rate || ""}
                      onChange={(event) => updateInlineAccountingField("tax_rate", event.target.value)}
                    />
                  </FormField>
                  <FormField label="Skontokonto" error={inlineAccountingErrors.discount_account}>
                    <input
                      list="approval-accounting-discount-options"
                      type="text"
                      value={inlineAccountingForm.discount_account || ""}
                      onChange={(event) => updateInlineAccountingField("discount_account", event.target.value)}
                    />
                  </FormField>
                </div>
                <div className="approval-rule-form-actions">
                  <button
                    className="secondary-button compact-button"
                    type="button"
                    onClick={() => {
                      setInlineAccountingIssue(null);
                      setInlineAccountingForm(null);
                      setInlineAccountingErrors({});
                      setInlineAccountingMessage("");
                    }}
                    disabled={isSavingInlineAccountingRule}
                  >
                    Abbrechen
                  </button>
                  <button type="submit" disabled={isSavingInlineAccountingRule}>
                    {isSavingInlineAccountingRule ? "Speichert..." : "Regel speichern"}
                  </button>
                </div>
                <AccountSuggestionDatalist id="approval-accounting-debit-options" suggestions={inlineDebitSuggestions} />
                <AccountSuggestionDatalist id="approval-accounting-credit-options" suggestions={inlineCreditSuggestions} />
                <AccountSuggestionDatalist id="approval-accounting-discount-options" suggestions={inlineDiscountSuggestions} />
              </form>
            ) : null}
            {missingAccountingRuleIssues.some((issue) => issue.bwa_account_hints?.length) ? (
              <details className="approval-fix-details">
                <summary>BWA-Hinweise anzeigen</summary>
                <div className="approval-bwa-hints">
                  <span>Aus hochgeladenen BWA-Daten, nur als Vorschlag für die Kontierungsregel.</span>
                  <ul>
                    {dedupeAccountingRuleIssues(missingAccountingRuleIssues)
                      .filter((issue) => issue.bwa_account_hints?.length)
                      .map((issue) => {
                        const hint = bestBwaAccountHint(issue);
                        return (
                          <li key={`bwa-${issue.supplier_name || "-"}-${issue.cost_category || ""}`}>
                            <span>{accountingRuleIssueContext(issue)}</span>
                            <strong>{formatBwaAccountHint(hint)}</strong>
                            <small>
                              {issue.suggested_debit_account
                                ? "wird als Aufwandskonto vorgeschlagen"
                                : "kein automatisch übernehmbares Aufwandskonto"}
                            </small>
                          </li>
                        );
                      })}
                  </ul>
                </div>
              </details>
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
                  <div>
                    <span>
                      {[issue.line_no ? `Zeile ${issue.line_no}` : null, issue.row_type_label || formatExportRowType(issue.row_type)]
                        .filter(Boolean)
                        .join(" · ") || "Exportzeile"}
                    </span>
                    <small>{(issue.export_errors || []).join(", ") || issue.message}</small>
                  </div>
                  <button
                    className="secondary-button compact-button"
                    type="button"
                    onClick={() => onFixReviewIssue(issue)}
                  >
                    Zur Korrektur
                  </button>
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
                <AssignmentLineSummary
                  assignmentCode={suggestion.assignment_code}
                  assignmentKind={suggestion.assignment_kind}
                  projectNumber={suggestion.assignment_project_number}
                  tenantProfile={tenantProfile}
                />
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
  assignmentUnitDraft,
  onAccountingRuleDraftConsumed,
  onAccountingRuleEditTargetConsumed,
  onAccountingRuleSaved,
  onAssignmentUnitDraftConsumed,
  onAssignmentUnitSaved,
  onProfileSaved,
}) {
  const [assignmentUnits, setAssignmentUnits] = useState([]);
  const [supplierRules, setSupplierRules] = useState([]);
  const [extractionCapabilities, setExtractionCapabilities] = useState([]);
  const [accountingRules, setAccountingRules] = useState([]);
  const [bwaImports, setBwaImports] = useState([]);
  const [taxSupportingDocuments, setTaxSupportingDocuments] = useState([]);
  const [assignmentEditId, setAssignmentEditId] = useState(null);
  const [assignmentEditForm, setAssignmentEditForm] = useState(null);
  const [supplierEditId, setSupplierEditId] = useState(null);
  const [supplierEditForm, setSupplierEditForm] = useState(null);
  const [accountingEditId, setAccountingEditId] = useState(null);
  const [accountingEditForm, setAccountingEditForm] = useState(null);
  const [accountingReturnDocumentId, setAccountingReturnDocumentId] = useState("");
  const [assignmentReturnDocumentId, setAssignmentReturnDocumentId] = useState("");
  const [assignmentReturnLineNo, setAssignmentReturnLineNo] = useState("");
  const [assignmentReturnSuggestionId, setAssignmentReturnSuggestionId] = useState("");
  const [capabilitySearch, setCapabilitySearch] = useState("");
  const [capabilityStatusFilter, setCapabilityStatusFilter] = useState("all");
  const [profileForm, setProfileForm] = useState(tenantProfile);
  const [assignmentForm, setAssignmentForm] = useState({
    code: "",
    label: "",
    kind: "cost_object",
    project_number: "",
    address_line: "",
    postal_code: "",
    city: "",
    external_id: "",
    revenue_relevant: false,
    aliases: "",
  });
  const [supplierForm, setSupplierForm] = useState({
    match_text: "",
    supplier_name: "",
    customer_number: "",
    default_cost_category: ["material"],
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
  const [messageTone, setMessageTone] = useState("notice");
  const [isUploadingBwa, setIsUploadingBwa] = useState(false);
  const [isSyncingPartnerProjects, setIsSyncingPartnerProjects] = useState(false);
  const [supplierFormErrors, setSupplierFormErrors] = useState({});
  const [accountingFormErrors, setAccountingFormErrors] = useState({});
  const [assignmentEditErrors, setAssignmentEditErrors] = useState({});
  const [supplierEditErrors, setSupplierEditErrors] = useState({});
  const [accountingEditErrors, setAccountingEditErrors] = useState({});
  const accountingSectionRef = useRef(null);
  const assignmentSectionRef = useRef(null);
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
  const filteredExtractionCapabilities = useMemo(() => {
    const searchText = normalizeSearchText(capabilitySearch);
    return extractionCapabilities
      .filter((capability) => capabilityStatusFilter === "all" || capability.status === capabilityStatusFilter)
      .filter((capability) => {
        if (!searchText) return true;
        return normalizeSearchText([
          capability.supplier_name,
          capability.status,
          capability.recognition,
          capability.coverage,
        ].filter(Boolean).join(" ")).includes(searchText);
      })
      .sort((left, right) => compareReviewValues(left.supplier_name, right.supplier_name));
  }, [capabilitySearch, capabilityStatusFilter, extractionCapabilities]);
  const capabilityStatuses = useMemo(
    () => Array.from(new Set(extractionCapabilities.map((capability) => capability.status).filter(Boolean))).sort((left, right) => compareReviewValues(left, right)),
    [extractionCapabilities],
  );

  useEffect(() => {
    setProfileForm(tenantProfile);
    setAssignmentForm((current) => ({
      ...current,
      kind: tenantProfile.default_assignment_kind || current.kind,
    }));
  }, [tenantProfile]);

  const loadMasterdata = useCallback(async () => {
    const [assignmentsResponse, suppliersResponse, capabilitiesResponse, accountingResponse, bwaResponse, taxDocsResponse] = await Promise.all([
      apiFetch(`/masterdata/assignment-units?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch(`/masterdata/supplier-rules?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch("/masterdata/extraction-capabilities"),
      apiFetch(`/masterdata/accounting-rules?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch(`/masterdata/bwa-imports?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch(`/masterdata/tax-supporting-documents?tenant_id=${encodeURIComponent(tenantId)}`),
    ]);
    if (!assignmentsResponse.ok || !suppliersResponse.ok || !capabilitiesResponse.ok || !accountingResponse.ok || !bwaResponse.ok || !taxDocsResponse.ok) {
      throw new Error("Stammdaten konnten nicht geladen werden.");
    }
    const assignmentsResult = await assignmentsResponse.json();
    const suppliersResult = await suppliersResponse.json();
    const capabilitiesResult = await capabilitiesResponse.json();
    const accountingResult = await accountingResponse.json();
    const bwaResult = await bwaResponse.json();
    const taxDocsResult = await taxDocsResponse.json();
    setAssignmentUnits(assignmentsResult.assignment_units ?? []);
    setSupplierRules(suppliersResult.supplier_rules ?? []);
    setExtractionCapabilities(capabilitiesResult.capabilities ?? []);
    setAccountingRules(accountingResult.accounting_rules ?? []);
    setBwaImports(bwaResult.bwa_imports ?? []);
    setTaxSupportingDocuments(taxDocsResult.tax_supporting_documents ?? []);
  }, [apiFetch, tenantId]);

  useEffect(() => {
    loadMasterdata().catch((error) => {
      setMessageTone("error");
      setMessage(error.message);
    });
  }, [loadMasterdata]);

  async function importPartnerAssignments() {
    if (!window.confirm("Projektstammdaten aus der Partner-App synchronisieren? Bestehende Einträge mit gleichem Code werden aktualisiert.")) {
      return;
    }
    setIsSyncingPartnerProjects(true);
    try {
      const response = await apiFetch(`/masterdata/assignment-units/import-partner?tenant_id=${encodeURIComponent(tenantId)}`, {
        method: "POST",
      });
      if (!response.ok) {
        const apiError = await readApiError(response, "Projektstammdaten konnten nicht synchronisiert werden");
        setMessageTone("error");
        setMessage(apiError.message);
        return;
      }
      const result = await response.json();
      await loadMasterdata();
      setMessageTone("notice");
      setMessage(
        `Partner-App gelesen: ${result.source_count ?? result.synced_count ?? 0} Projekte, ` +
        `${result.synced_count ?? 0} lokal synchronisiert.`,
      );
    } catch (error) {
      setMessageTone("error");
      setMessage(error.message || "Projektstammdaten konnten nicht synchronisiert werden.");
    } finally {
      setIsSyncingPartnerProjects(false);
    }
  }

  useEffect(() => {
    if (!accountingRuleDraft?.form) return;
    setAccountingForm((current) => ({
      ...current,
      ...accountingRuleDraft.form,
    }));
    setAccountingReturnDocumentId(accountingRuleDraft.return_document_id || "");
    setMessageTone("notice");
    setMessage("Kontierungsregel aus der Freigabe vorbereitet. Nach dem Speichern läuft die Freigabeprüfung erneut.");
    window.setTimeout(() => {
      accountingSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      const focusSelector = `[data-accounting-field="${accountingRuleDraft.focus_field || "debit_account"}"]`;
      accountingSectionRef.current?.querySelector(focusSelector)?.focus();
    }, 0);
    onAccountingRuleDraftConsumed?.();
  }, [accountingRuleDraft, onAccountingRuleDraftConsumed]);

  useEffect(() => {
    if (!assignmentUnitDraft?.form) return;
    setAssignmentForm((current) => ({
      ...current,
      ...assignmentUnitDraft.form,
    }));
    setAssignmentReturnDocumentId(assignmentUnitDraft.return_document_id || "");
    setAssignmentReturnLineNo(assignmentUnitDraft.return_line_no || "");
    setAssignmentReturnSuggestionId(assignmentUnitDraft.return_suggestion_id || "");
    setMessageTone("notice");
    setMessage(`${tenantProfile.assignment_label_singular} aus der Freigabe vorbereitet. Nach dem Speichern läuft die Freigabeprüfung erneut.`);
    window.setTimeout(() => {
      assignmentSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      const focusSelector = `[data-assignment-field="${assignmentUnitDraft.focus_field || "code"}"]`;
      assignmentSectionRef.current?.querySelector(focusSelector)?.focus();
    }, 0);
    onAssignmentUnitDraftConsumed?.();
  }, [assignmentUnitDraft, onAssignmentUnitDraftConsumed, tenantProfile.assignment_label_singular]);

  useEffect(() => {
    if (!accountingRuleEditTarget || !accountingRules.length) return;
    const rule = findAccountingRuleForTarget(accountingRules, accountingRuleEditTarget);
    if (!rule) {
      setMessageTone("error");
      setMessage("Kontierungsregel konnte nicht automatisch gefunden werden. Bitte manuell in den Stammdaten prüfen.");
      setAccountingReturnDocumentId("");
      onAccountingRuleEditTargetConsumed?.();
      return;
    }

    setAccountingReturnDocumentId(accountingRuleEditTarget.return_document_id || "");
    startAccountingEdit(rule);
    setMessageTone("notice");
    setMessage(accountingRuleEditTarget.focus_field === "supplier_match_text"
      ? "Kontierungsregel geöffnet. Bitte Erkennung oder Kostenart eindeutiger machen und speichern."
      : "Kontierungsregel geöffnet. Bitte fehlende Konten ergänzen und speichern.");
    window.setTimeout(() => {
      accountingSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      const focusSelector = `[data-accounting-field="${accountingRuleEditTarget.focus_field || "debit_account"}"]`;
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
      const apiError = await readApiError(response, "Zuordnung konnte nicht angelegt werden");
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    const result = await response.json();
    const assignmentUnit = result.assignment_unit;
    setAssignmentForm({
      code: "",
      label: "",
      kind: tenantProfile.default_assignment_kind || "cost_object",
      project_number: "",
      address_line: "",
      postal_code: "",
      city: "",
      external_id: "",
      revenue_relevant: false,
      aliases: "",
    });
    await loadMasterdata();
    if (assignmentReturnDocumentId) {
      const returnDocumentId = assignmentReturnDocumentId;
      const returnLineNo = assignmentReturnLineNo;
      const returnSuggestionId = assignmentReturnSuggestionId;
      setAssignmentReturnDocumentId("");
      setAssignmentReturnLineNo("");
      setAssignmentReturnSuggestionId("");
      setMessageTone("notice");
      setMessage("Zuordnung angelegt. Zurück zur Freigabeprüfung.");
      onAssignmentUnitSaved?.({
        documentId: returnDocumentId,
        lineNo: returnLineNo,
        suggestionId: returnSuggestionId,
        assignmentUnit,
      });
    } else {
      setMessageTone("notice");
      setMessage("Zuordnung angelegt.");
    }
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
        order_number: assignment.order_number,
        customer_number: assignment.customer_number,
        description: assignment.description,
        client_name: assignment.client_name,
        source_status: assignment.source_status,
        address_line: assignment.address_line,
        postal_code: assignment.postal_code,
        city: assignment.city,
        external_id: assignment.external_id,
        revenue_relevant: assignment.revenue_relevant,
        aliases: assignment.aliases ?? [],
        is_active: assignment.is_active,
        ...payload,
      }),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Zuordnung konnte nicht aktualisiert werden");
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    await loadMasterdata();
    setMessageTone("notice");
    setMessage("Zuordnung aktualisiert.");
  }

  function startAssignmentEdit(assignment) {
    setAssignmentEditId(assignment.id);
    setAssignmentEditErrors({});
    setAssignmentEditForm({
      code: assignment.code || "",
      label: assignment.label || "",
      kind: assignment.kind || tenantProfile.default_assignment_kind || "cost_object",
      project_number: assignment.project_number || "",
      order_number: assignment.order_number || "",
      customer_number: assignment.customer_number || "",
      description: assignment.description || "",
      client_name: assignment.client_name || "",
      source_status: assignment.source_status || "",
      address_line: assignment.address_line || "",
      postal_code: assignment.postal_code || "",
      city: assignment.city || "",
      external_id: assignment.external_id || "",
      revenue_relevant: assignment.revenue_relevant,
      aliases: (assignment.aliases || []).join(", "),
      is_active: assignment.is_active,
    });
  }

  function cancelAssignmentEdit() {
    setAssignmentEditId(null);
    setAssignmentEditForm(null);
    setAssignmentEditErrors({});
  }

  async function saveAssignmentEdit(assignment) {
    if (!assignmentEditForm) return;
    if (!assignmentEditForm.code.trim() || !assignmentEditForm.label.trim()) {
      setAssignmentEditErrors({
        code: assignmentEditForm.code.trim() ? "" : "Code ist erforderlich.",
        label: assignmentEditForm.label.trim() ? "" : "Name ist erforderlich.",
      });
      setMessageTone("error");
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
      const apiError = await readApiError(response, "Zuordnung konnte nicht gespeichert werden");
      setAssignmentEditErrors(apiError.fields);
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    cancelAssignmentEdit();
    await loadMasterdata();
    setMessageTone("notice");
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
      const apiError = await readApiError(response, "Mandantenprofil konnte nicht gespeichert werden");
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    const result = await response.json();
    onProfileSaved(result.tenant_profile);
    setMessageTone("notice");
    setMessage("Mandantenprofil gespeichert.");
  }

  async function createSupplierRule(event) {
    event.preventDefault();
    setSupplierFormErrors({});
    const response = await apiFetch(`/masterdata/supplier-rules?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(supplierForm)),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Lieferantenregel konnte nicht angelegt werden");
      setSupplierFormErrors(apiError.fields);
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    setSupplierForm({ match_text: "", supplier_name: "", customer_number: "", default_cost_category: ["material"] });
    await loadMasterdata();
    setMessageTone("notice");
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
        default_assignment_code: null,
        is_active: rule.is_active,
        ...payload,
      }),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Lieferantenregel konnte nicht aktualisiert werden");
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    await loadMasterdata();
    setMessageTone("notice");
    setMessage("Lieferantenregel aktualisiert.");
  }

  function startSupplierEdit(rule) {
    setSupplierEditId(rule.id);
    setSupplierEditErrors({});
    setSupplierEditForm({
      match_text: rule.match_text || "",
      supplier_name: rule.supplier_name || "",
      customer_number: rule.customer_number || "",
      default_cost_category: supplierCostCategories(rule),
      is_active: rule.is_active,
    });
  }

  function cancelSupplierEdit() {
    setSupplierEditId(null);
    setSupplierEditForm(null);
    setSupplierEditErrors({});
  }

  async function saveSupplierEdit(rule) {
    if (!supplierEditForm) return;
    if (!supplierEditForm.match_text.trim() || !supplierEditForm.supplier_name.trim()) {
      setSupplierEditErrors({
        match_text: supplierEditForm.match_text.trim() ? "" : "Erkennungstext ist erforderlich.",
        supplier_name: supplierEditForm.supplier_name.trim() ? "" : "Lieferant ist erforderlich.",
      });
      setMessageTone("error");
      setMessage("Lieferantenregel braucht Erkennungstext und Lieferant.");
      return;
    }
    const response = await apiFetch(`/masterdata/supplier-rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(supplierEditForm)),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Lieferantenregel konnte nicht gespeichert werden");
      setSupplierEditErrors(apiError.fields);
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    cancelSupplierEdit();
    await loadMasterdata();
    setMessageTone("notice");
    setMessage("Lieferantenregel gespeichert.");
  }

  async function createAccountingRule(event) {
    event.preventDefault();
    setAccountingFormErrors({});
    const response = await apiFetch(`/masterdata/accounting-rules?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(accountingForm)),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Kontierungsregel konnte nicht angelegt werden");
      setAccountingFormErrors(apiError.fields);
      setMessageTone("error");
      setMessage(apiError.message);
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
    if (accountingReturnDocumentId) {
      const returnDocumentId = accountingReturnDocumentId;
      setAccountingReturnDocumentId("");
      setMessageTone("notice");
      setMessage("Kontierungsregel angelegt. Zurück zur Freigabeprüfung.");
      onAccountingRuleSaved?.(returnDocumentId);
    } else {
      setMessageTone("notice");
      setMessage("Kontierungsregel angelegt.");
    }
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
      const apiError = await readApiError(response, "Kontierungsregel konnte nicht aktualisiert werden");
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    await loadMasterdata();
    setMessageTone("notice");
    setMessage("Kontierungsregel aktualisiert.");
  }

  function startAccountingEdit(rule) {
    setAccountingEditId(rule.id);
    setAccountingEditErrors({});
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
    setAccountingEditErrors({});
  }

  async function saveAccountingEdit(rule) {
    if (!accountingEditForm) return;
    if (!accountingEditForm.name.trim() || !accountingEditForm.debit_account.trim() || !accountingEditForm.credit_account.trim()) {
      setAccountingEditErrors({
        name: accountingEditForm.name.trim() ? "" : "Name ist erforderlich.",
        debit_account: accountingEditForm.debit_account.trim() ? "" : "Aufwandskonto ist erforderlich.",
        credit_account: accountingEditForm.credit_account.trim() ? "" : "Gegenkonto ist erforderlich.",
      });
      setMessageTone("error");
      setMessage("Kontierungsregel braucht Name, Aufwandskonto und Gegenkonto.");
      return;
    }
    const response = await apiFetch(`/masterdata/accounting-rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(emptyToNull(accountingEditForm)),
    });
    if (!response.ok) {
      const apiError = await readApiError(response, "Kontierungsregel konnte nicht gespeichert werden");
      setAccountingEditErrors(apiError.fields);
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    cancelAccountingEdit();
    await loadMasterdata();
    if (accountingReturnDocumentId) {
      const returnDocumentId = accountingReturnDocumentId;
      setAccountingReturnDocumentId("");
      setMessageTone("notice");
      setMessage("Kontierungsregel gespeichert. Zurück zur Freigabeprüfung.");
      onAccountingRuleSaved?.(returnDocumentId);
    } else {
      setMessageTone("notice");
      setMessage("Kontierungsregel gespeichert.");
    }
  }

  async function uploadBwa(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = form.elements.bwa_file?.files?.[0];
    if (!file) {
      setMessageTone("error");
      setMessage("Bitte zuerst eine BWA-Datei auswählen.");
      return;
    }
    setIsUploadingBwa(true);
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(`/masterdata/bwa-imports?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      body: formData,
    });
    setIsUploadingBwa(false);
    if (!response.ok) {
      const apiError = await readApiError(response, "BWA konnte nicht hochgeladen werden");
      setMessageTone("error");
      setMessage(apiError.message);
      return;
    }
    const result = await response.json();
    form.reset();
    await loadMasterdata();
    setMessageTone("notice");
    setMessage(result.duplicate ? "BWA erneut analysiert." : "BWA gespeichert und analysiert.");
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
      {message ? <p className={messageTone}>{message}</p> : null}

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
            <FormField label="Standard-Gegenkonto">
              <input placeholder="70000" value={profileForm.default_credit_account || ""} onChange={(event) => setProfileForm({ ...profileForm, default_credit_account: event.target.value })} />
            </FormField>
            <FormField label="Standard-Steuerschlüssel">
              <input placeholder="optional" value={profileForm.default_tax_key || ""} onChange={(event) => setProfileForm({ ...profileForm, default_tax_key: event.target.value })} />
            </FormField>
            <FormField label="Standard-Steuersatz">
              <input placeholder="19.00" value={profileForm.default_tax_rate || ""} onChange={(event) => setProfileForm({ ...profileForm, default_tax_rate: event.target.value })} />
            </FormField>
            <FormField label="Standard-Skontokonto">
              <input placeholder="3736" value={profileForm.default_discount_account || ""} onChange={(event) => setProfileForm({ ...profileForm, default_discount_account: event.target.value })} />
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

        <section className="admin-card" ref={assignmentSectionRef}>
          <div className="card-header">
            <div>
              <p className="eyebrow">Kosten- und Umsatzzuordnung</p>
              <h3>{tenantProfile.assignment_label_plural}</h3>
            </div>
            <div className="header-actions">
              <button type="button" className="secondary-button compact-button" onClick={importPartnerAssignments} disabled={isSyncingPartnerProjects}>
                {isSyncingPartnerProjects ? "Synchronisiere..." : "Partner-App synchronisieren"}
              </button>
              <StatusPill value={`${assignmentUnits.length} Einträge`} />
            </div>
          </div>
          {assignmentReturnDocumentId ? (
            <div className="return-to-review-note">
              <strong>Freigabeprüfung wartet</strong>
              <span>Diese Zuordnung wurde aus einer blockierten Freigabe geöffnet. Nach dem Speichern springt die App zurück und prüft den Beleg erneut.</span>
            </div>
          ) : null}
          <form className="form-grid assignment-form" onSubmit={createAssignment}>
            <FormField label="Code">
              <input data-assignment-field="code" placeholder="Wewe20" value={assignmentForm.code} onChange={(event) => setAssignmentForm({ ...assignmentForm, code: event.target.value })} required />
            </FormField>
            <FormField label="Name">
              <input data-assignment-field="label" placeholder="Weseler Weg 20" value={assignmentForm.label} onChange={(event) => setAssignmentForm({ ...assignmentForm, label: event.target.value })} required />
            </FormField>
            <FormField label="Art">
              <select data-assignment-field="kind" value={assignmentForm.kind} onChange={(event) => setAssignmentForm({ ...assignmentForm, kind: event.target.value })}>
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
                <input data-assignment-field="project_number" placeholder="25-00008" value={assignmentForm.project_number || ""} onChange={(event) => setAssignmentForm({ ...assignmentForm, project_number: event.target.value })} />
              </FormField>
            ) : null}
            <FormField label="Adresse">
              <input data-assignment-field="address_line" placeholder="Weseler Weg 20" value={assignmentForm.address_line || ""} onChange={(event) => setAssignmentForm({ ...assignmentForm, address_line: event.target.value })} />
            </FormField>
            <FormField label="PLZ">
              <input data-assignment-field="postal_code" placeholder="22045" value={assignmentForm.postal_code || ""} onChange={(event) => setAssignmentForm({ ...assignmentForm, postal_code: event.target.value })} />
            </FormField>
            <FormField label="Ort">
              <input data-assignment-field="city" placeholder="Hamburg" value={assignmentForm.city || ""} onChange={(event) => setAssignmentForm({ ...assignmentForm, city: event.target.value })} />
            </FormField>
            <FormField label="Externe ID">
              <input data-assignment-field="external_id" placeholder="Partner-ID optional" value={assignmentForm.external_id || ""} onChange={(event) => setAssignmentForm({ ...assignmentForm, external_id: event.target.value })} />
            </FormField>
            <FormField label="Aliase">
              <input data-assignment-field="aliases" placeholder="Aliase, komma-getrennt" value={assignmentForm.aliases} onChange={(event) => setAssignmentForm({ ...assignmentForm, aliases: event.target.value })} />
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
              <span>Projekt-Nr.</span>
              <span>Name</span>
              <span>Adresse</span>
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
                      <InlineEditField error={fieldError(assignmentEditErrors, "code")}>
                        <input
                          aria-label="Code"
                          value={assignmentEditForm.code}
                          onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, code: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(assignmentEditErrors, "project_number")}>
                        <input
                          aria-label="Projektnummer"
                          placeholder={usesProjectNumber(assignmentEditForm.kind) ? "z.B. 25-00008" : "optional"}
                          value={assignmentEditForm.project_number}
                          onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, project_number: event.target.value })}
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(assignmentEditErrors, "label")}>
                        <input
                          aria-label="Name"
                          value={assignmentEditForm.label}
                          onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, label: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(assignmentEditErrors, "address_line")}>
                        <div className="stacked-inputs">
                          <input
                            aria-label="Adresse"
                            placeholder="Straße und Hausnummer"
                            value={assignmentEditForm.address_line}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, address_line: event.target.value })}
                          />
                          <input
                            aria-label="PLZ"
                            placeholder="PLZ"
                            value={assignmentEditForm.postal_code}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, postal_code: event.target.value })}
                          />
                          <input
                            aria-label="Ort"
                            placeholder="Ort"
                            value={assignmentEditForm.city}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, city: event.target.value })}
                          />
                          <input
                            aria-label="Externe ID"
                            placeholder="Externe ID"
                            value={assignmentEditForm.external_id}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, external_id: event.target.value })}
                          />
                          <input
                            aria-label="Auftragsnummer"
                            placeholder="Auftragsnummer"
                            value={assignmentEditForm.order_number}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, order_number: event.target.value })}
                          />
                          <input
                            aria-label="Kundennummer"
                            placeholder="Kundennummer"
                            value={assignmentEditForm.customer_number}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, customer_number: event.target.value })}
                          />
                          <input
                            aria-label="Beschreibung"
                            placeholder="Beschreibung"
                            value={assignmentEditForm.description}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, description: event.target.value })}
                          />
                          <input
                            aria-label="Bauherr"
                            placeholder="Bauherr"
                            value={assignmentEditForm.client_name}
                            onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, client_name: event.target.value })}
                          />
                        </div>
                      </InlineEditField>
                      <InlineEditField error={fieldError(assignmentEditErrors, "kind")}>
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
                      </InlineEditField>
                      <InlineEditField error={fieldError(assignmentEditErrors, "aliases")}>
                        <input
                          aria-label="Aliase"
                          placeholder="kommagetrennt"
                          value={assignmentEditForm.aliases}
                          onChange={(event) => setAssignmentEditForm({ ...assignmentEditForm, aliases: event.target.value })}
                        />
                      </InlineEditField>
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
                      <span>{formatAssignmentAddress(assignment)}</span>
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

        <section className="admin-card admin-card-wide">
          <div className="card-header">
            <div>
              <p className="eyebrow">Steuerliche Nachweise</p>
              <h3>Freistellung und §13b</h3>
            </div>
            <StatusPill value={`${taxSupportingDocuments.length} Nachweise`} tone={taxSupportingDocuments.length ? "green" : "gray"} />
          </div>
          <p className="form-hint">
            Hochgeladene Freistellungsbescheinigungen und §13b-Nachweise werden hier gesammelt. Ablaufdaten dienen als Prüfhilfe und ersetzen keine fachliche Steuerprüfung.
          </p>
          <div className="data-table tax-doc-table">
            <div className="data-row data-head">
              <span>Firma</span>
              <span>Nachweis</span>
              <span>Gültig bis</span>
              <span>Steuernr. / USt-ID</span>
              <span>Status</span>
              <span>Datei</span>
            </div>
            {taxSupportingDocuments.map((taxDocument) => (
              <div className="data-row" key={taxDocument.id}>
                <strong>{taxDocument.certificate_subject || "-"}</strong>
                <span>{taxDocument.certificate_kind || formatDocumentType(taxDocument.document_type)}</span>
                <span>{formatDate(taxDocument.certificate_valid_until)}</span>
                <span>{[taxDocument.certificate_tax_number, taxDocument.certificate_vat_id].filter(Boolean).join(" / ") || "-"}</span>
                <StatusPill value={formatCertificateExpiryStatus(taxDocument)} tone={certificateExpiryTone(taxDocument.expiry_status)} />
                <span>{safeVisibleFilename(taxDocument.normalized_filename || taxDocument.original_filename)}</span>
                {taxDocument.warnings?.length ? (
                  <p className="inline-note">{taxDocument.warnings.join(" ")}</p>
                ) : null}
              </div>
            ))}
            {!taxSupportingDocuments.length ? (
              <div className="data-row empty-row">
                <span>Noch keine Freistellungs- oder §13b-Nachweise erkannt.</span>
              </div>
            ) : null}
          </div>
        </section>

        <section className="admin-card admin-card-wide">
          <div className="card-header">
            <div>
              <p className="eyebrow">Einlesen und Extraktion</p>
              <h3>Abgedeckte Rechnungssteller</h3>
            </div>
            <StatusPill value={`${filteredExtractionCapabilities.length} von ${extractionCapabilities.length} Einträgen`} />
          </div>
          <p className="form-hint">
            Diese Liste zeigt, für welche Rechnungssteller es aktuell feste Erkennungsmerkmale oder belastbare Fallbacks gibt.
          </p>
          <div className="capability-toolbar">
            <label>
              <span>Suchen</span>
              <input
                type="search"
                placeholder="Rechnungssteller, Erkennung, Abdeckung"
                value={capabilitySearch}
                onChange={(event) => setCapabilitySearch(event.target.value)}
              />
            </label>
            <label>
              <span>Status</span>
              <select value={capabilityStatusFilter} onChange={(event) => setCapabilityStatusFilter(event.target.value)}>
                <option value="all">Alle Status</option>
                {capabilityStatuses.map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="data-table capability-table">
            <div className="data-row data-head">
              <span>Rechnungssteller</span>
              <span>Status</span>
              <span>Erkennung</span>
              <span>Abdeckung</span>
            </div>
            {filteredExtractionCapabilities.map((capability) => (
              <div className="data-row" key={capability.supplier_name}>
                <strong>{capability.supplier_name}</strong>
                <StatusPill value={capability.status} tone={capability.status === "gut" ? "green" : "gray"} />
                <span>{capability.recognition}</span>
                <span>{capability.coverage}</span>
              </div>
            ))}
            {!filteredExtractionCapabilities.length ? (
              <div className="data-row empty-row">
                <span>Keine Rechnungssteller für diese Auswahl gefunden.</span>
              </div>
            ) : null}
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
            <FormField label="Erkennungstext" error={fieldError(supplierFormErrors, "match_text")}>
              <input placeholder="Holz Junge" value={supplierForm.match_text} onChange={(event) => setSupplierForm({ ...supplierForm, match_text: event.target.value })} required />
            </FormField>
            <FormField label="Lieferant" error={fieldError(supplierFormErrors, "supplier_name")}>
              <input placeholder="Holz Junge GmbH" value={supplierForm.supplier_name} onChange={(event) => setSupplierForm({ ...supplierForm, supplier_name: event.target.value })} required />
            </FormField>
            <FormField label="Unsere Kunden-Nr." error={fieldError(supplierFormErrors, "customer_number")}>
              <input placeholder="109324" value={supplierForm.customer_number} onChange={(event) => setSupplierForm({ ...supplierForm, customer_number: event.target.value })} />
            </FormField>
            <FormField label="Kostenart" error={fieldError(supplierFormErrors, "default_cost_category")}>
              <CategoryChecklist
                value={supplierForm.default_cost_category}
                onChange={(categories) => setSupplierForm({ ...supplierForm, default_cost_category: categories })}
              />
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
              <span>Aktiv</span>
              <span>Aktion</span>
            </div>
            {supplierRules.map((rule) => {
              const isEditing = supplierEditId === rule.id && supplierEditForm;
              return (
                <div className={isEditing ? "data-row editing-row" : "data-row"} key={rule.id}>
                  {isEditing ? (
                    <>
                      <InlineEditField error={fieldError(supplierEditErrors, "supplier_name")}>
                        <input
                          aria-label="Lieferant"
                          value={supplierEditForm.supplier_name}
                          onChange={(event) => setSupplierEditForm({ ...supplierEditForm, supplier_name: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(supplierEditErrors, "match_text")}>
                        <input
                          aria-label="Erkennungstext"
                          value={supplierEditForm.match_text}
                          onChange={(event) => setSupplierEditForm({ ...supplierEditForm, match_text: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(supplierEditErrors, "customer_number")}>
                        <input
                          aria-label="Unsere Kunden-Nr."
                          value={supplierEditForm.customer_number}
                          onChange={(event) => setSupplierEditForm({ ...supplierEditForm, customer_number: event.target.value })}
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(supplierEditErrors, "default_cost_category")}>
                        <CategoryChecklist
                          value={supplierEditForm.default_cost_category}
                          onChange={(categories) => setSupplierEditForm({ ...supplierEditForm, default_cost_category: categories })}
                        />
                      </InlineEditField>
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
          {accountingReturnDocumentId ? (
            <div className="return-to-review-note">
              <strong>Freigabeprüfung wartet</strong>
              <span>Diese Kontierungsregel wurde aus einer blockierten Freigabe geöffnet. Nach dem Speichern springt die App zurück und prüft den Beleg erneut.</span>
            </div>
          ) : null}
          <form className="form-grid accounting-form" onSubmit={createAccountingRule}>
            <FormField label="Name" error={fieldError(accountingFormErrors, "name")}>
              <input data-accounting-field="name" placeholder="Material 19%" value={accountingForm.name} onChange={(event) => setAccountingForm({ ...accountingForm, name: event.target.value })} required />
            </FormField>
            <FormField label="Lieferant enthält" error={fieldError(accountingFormErrors, "supplier_match_text")}>
              <input data-accounting-field="supplier_match_text" placeholder="optional, z.B. Lüchau" value={accountingForm.supplier_match_text} onChange={(event) => setAccountingForm({ ...accountingForm, supplier_match_text: event.target.value })} />
            </FormField>
            <FormField label="Kostenart" error={fieldError(accountingFormErrors, "cost_category")}>
              <select data-accounting-field="cost_category" value={accountingForm.cost_category} onChange={(event) => setAccountingForm({ ...accountingForm, cost_category: event.target.value })}>
                <option value="">Alle Kostenarten</option>
                <option value="material">Material</option>
                <option value="subcontractor">Fremdleistung</option>
                <option value="fuel_vehicle">Fahrzeug/Tanken</option>
                <option value="software_subscription">Software/Abo</option>
                <option value="security_subscription">Überwachung/Abo</option>
                <option value="general_overhead">Sonstige Gemeinkosten</option>
              </select>
            </FormField>
            <FormField label="Aufwandskonto" error={fieldError(accountingFormErrors, "debit_account")}>
              <input data-accounting-field="debit_account" list="accounting-debit-options" placeholder="z.B. 3400" value={accountingForm.debit_account} onChange={(event) => setAccountingForm({ ...accountingForm, debit_account: event.target.value })} required />
            </FormField>
            <FormField label="Gegenkonto" error={fieldError(accountingFormErrors, "credit_account")}>
              <input data-accounting-field="credit_account" list="accounting-credit-options" placeholder="z.B. Kreditor/Sammelkonto" value={accountingForm.credit_account} onChange={(event) => setAccountingForm({ ...accountingForm, credit_account: event.target.value })} required />
            </FormField>
            <FormField label="Steuerschlüssel" error={fieldError(accountingFormErrors, "tax_key")}>
              <input data-accounting-field="tax_key" placeholder="optional" value={accountingForm.tax_key} onChange={(event) => setAccountingForm({ ...accountingForm, tax_key: event.target.value })} />
            </FormField>
            <FormField label="Steuersatz" error={fieldError(accountingFormErrors, "tax_rate")}>
              <input data-accounting-field="tax_rate" placeholder="19.00" value={accountingForm.tax_rate} onChange={(event) => setAccountingForm({ ...accountingForm, tax_rate: event.target.value })} />
            </FormField>
            <FormField label="Skontokonto" error={fieldError(accountingFormErrors, "discount_account")}>
              <input data-accounting-field="discount_account" list="accounting-discount-options" placeholder="optional" value={accountingForm.discount_account} onChange={(event) => setAccountingForm({ ...accountingForm, discount_account: event.target.value })} />
            </FormField>
            <button className="secondary-button" type="button" onClick={() => setAccountingForm((current) => applyAccountingSuggestions(current, tenantProfile))}>
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
                      <InlineEditField error={fieldError(accountingEditErrors, "name")}>
                        <input
                          aria-label="Name"
                          value={accountingEditForm.name}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, name: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(accountingEditErrors, "supplier_match_text")}>
                        <input
                          aria-label="Lieferant enthält"
                          data-accounting-field="supplier_match_text"
                          placeholder="optional"
                          value={accountingEditForm.supplier_match_text}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, supplier_match_text: event.target.value })}
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(accountingEditErrors, "cost_category")}>
                        <CostCategorySelect
                          value={accountingEditForm.cost_category}
                          onChange={(value) => setAccountingEditForm({ ...accountingEditForm, cost_category: value })}
                          includeAll
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(accountingEditErrors, "debit_account")}>
                        <input
                          aria-label="Aufwandskonto"
                          data-accounting-field="debit_account"
                          list="accounting-edit-debit-options"
                          value={accountingEditForm.debit_account}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, debit_account: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(accountingEditErrors, "credit_account")}>
                        <input
                          aria-label="Gegenkonto"
                          list="accounting-edit-credit-options"
                          value={accountingEditForm.credit_account}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, credit_account: event.target.value })}
                          required
                        />
                      </InlineEditField>
                      <InlineEditField error={fieldError(accountingEditErrors, "tax_key", "tax_rate")}>
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
                      </InlineEditField>
                      <InlineEditField error={fieldError(accountingEditErrors, "discount_account")}>
                        <input
                          aria-label="Skontokonto"
                          data-accounting-field="discount_account"
                          list="accounting-edit-discount-options"
                          placeholder="optional"
                          value={accountingEditForm.discount_account}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, discount_account: event.target.value })}
                        />
                      </InlineEditField>
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={accountingEditForm.is_active}
                          onChange={(event) => setAccountingEditForm({ ...accountingEditForm, is_active: event.target.checked })}
                        />
                        <span>{accountingEditForm.is_active ? "aktiv" : "inaktiv"}</span>
                      </label>
                      <div className="row-actions">
                        <button className="secondary-button" type="button" onClick={() => setAccountingEditForm((current) => applyAccountingSuggestions(current, tenantProfile))}>
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

        <section className="admin-card admin-card-wide">
          <div className="card-header">
            <div>
              <p className="eyebrow">Lernquellen</p>
              <h3>BWA-Importe</h3>
            </div>
            <StatusPill value={`${bwaImports.length} Dateien`} tone={bwaImports.length ? "green" : "gray"} />
          </div>
          <form className="bwa-upload" onSubmit={uploadBwa}>
            <FormField label="BWA-Datei">
              <input name="bwa_file" type="file" accept=".pdf,.csv,.txt,.xlsx,application/pdf,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />
            </FormField>
            <button type="submit" disabled={isUploadingBwa}>
              {isUploadingBwa ? "Analysiere ..." : "BWA hochladen"}
            </button>
            <p className="form-hint">
              BWA-Daten dienen aktuell als sichtbarer Lernhinweis für Kostenarten, Konten und bisherige Buchungslogik. Sie werden nicht blind als Vorlage übernommen.
            </p>
          </form>
          <div className="data-table bwa-table">
            <div className="data-row data-head">
              <span>Datei</span>
              <span>Zeitraum</span>
              <span>Erkannt</span>
              <span>Wirkt als</span>
              <span>Größe</span>
              <span>Importiert</span>
            </div>
            {bwaImports.map((bwaImport) => (
              <div className="data-row" key={bwaImport.id}>
                <strong>{safeVisibleFilename(bwaImport.original_filename)}</strong>
                <span>{bwaImport.period || "-"}</span>
                <span>{bwaHintSummary(bwaImport.account_hints)}</span>
                <span>{bwaEffectSummary(bwaImport.account_hints)}</span>
                <span>{formatSize(bwaImport.size_bytes)}</span>
                <span>{formatDateTime(bwaImport.created_at)}</span>
                {bwaImport.account_hints?.length ? (
                  <div className="bwa-hints">
                    {bwaImport.account_hints.slice(0, 16).map((hint) => (
                      <span className={hint.kind === "bwa_summary" ? "bwa-hint summary" : "bwa-hint"} key={`${bwaImport.id}-${hint.kind || "hint"}-${hint.account || ""}-${hint.label}`}>
                        <strong>{hint.account || hint.label}</strong>
                        {hint.account ? ` ${hint.label}` : null}
                        <small>{[hint.source, hint.effect, formatHintAmounts(hint.amounts)].filter(Boolean).join(" · ")}</small>
                      </span>
                    ))}
                  </div>
                ) : null}
                {bwaImport.warnings?.length ? (
                  <p className="inline-note">{bwaImport.warnings.join(" ")}</p>
                ) : null}
              </div>
            ))}
            {!bwaImports.length ? (
              <div className="data-row empty-row">
                <span>Noch keine BWA-Dateien für diesen Mandanten.</span>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </section>
  );
}

function FormField({ label, children, error, className = "" }) {
  return (
    <div className={`form-field ${className}`.trim()}>
      <span>{label}</span>
      {children}
      {error ? <small className="field-error">{error}</small> : null}
    </div>
  );
}

function InlineEditField({ children, error }) {
  return (
    <div className="inline-edit-field">
      {children}
      {error ? <small className="field-error">{error}</small> : null}
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

function AssignmentLineSummary({ assignmentCode, assignmentKind, projectNumber, tenantProfile }) {
  const label = assignmentCode
    ? formatAssignmentCode(assignmentCode, assignmentKind, tenantProfile)
    : formatAssignmentKind(assignmentKind, tenantProfile);
  if (!label && !projectNumber) return <span>-</span>;

  return (
    <span className="assignment-line-summary">
      <strong>{label || "-"}</strong>
      <small>{projectNumber ? `Projektnr. ${projectNumber}` : "Projektnr. -"}</small>
    </span>
  );
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
    <div className="payment-terms" data-review-section="payment_terms">
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

function BookingSuggestions({ document, suggestions, tenantProfile, assignmentUnits = [], highlightedLineNo = "", onSave, savingIds = [] }) {
  const [drafts, setDrafts] = useState({});
  const assignmentOptions = useMemo(
    () => assignmentUnits
      .filter((assignment) => assignment.is_active !== false)
      .map((assignment) => ({
        ...assignment,
        review_code: reviewAssignmentCode(assignment),
      }))
      .filter((assignment) => assignment.review_code || assignment.project_number)
      .sort((left, right) => compareProjectValues(left.project_number || left.review_code, right.project_number || right.review_code)),
    [assignmentUnits],
  );

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

  function selectedAssignmentIdForDraft(draft) {
    const selected = findAssignmentOption(assignmentOptions, "project_number", draft.project_number)
      || findAssignmentOption(assignmentOptions, "assignment_code", draft.assignment_code);
    return selected?.id || "";
  }

  function applyAssignmentToDraft(suggestionId, assignmentId) {
    const assignment = assignmentOptions.find((option) => option.id === assignmentId);
    if (!assignment) return;
    updateDraft(suggestionId, {
      assignment_code: assignment.review_code || assignment.code || "",
      project_number: assignment.project_number || "",
      assignment_kind: assignment.kind || "",
    });
  }

  return (
    <div className="booking-suggestions" data-review-section="booking_lines">
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
          const isHighlighted = highlightedLineNo && String(suggestion.line_no) === String(highlightedLineNo);
          return (
            <div
              className={`booking-edit-row${isHighlighted ? " booking-edit-row-highlight" : ""}`}
              key={suggestion.id}
              data-booking-line={suggestion.line_no}
            >
              <strong>{suggestion.line_no}</strong>
              <input
                value={draft.description}
                onChange={(event) => updateDraft(suggestion.id, { description: event.target.value })}
                disabled={isLocked}
                aria-label={`Beschreibung Zeile ${suggestion.line_no}`}
              />
              <div className="assignment-edit">
                <select
                  className="assignment-pick-select"
                  value={selectedAssignmentIdForDraft(draft)}
                  onChange={(event) => applyAssignmentToDraft(suggestion.id, event.target.value)}
                  disabled={isLocked || assignmentOptions.length === 0}
                  aria-label={`Projekt aus Stammdaten Zeile ${suggestion.line_no}`}
                >
                  <option value="">{assignmentOptions.length ? "Projekt wählen" : "Keine Stammdaten"}</option>
                  {assignmentOptions.map((assignment) => (
                    <option key={`booking-assignment-${suggestion.id}-${assignment.id}`} value={assignment.id}>
                      {formatAssignmentPickerLabel(assignment)}
                    </option>
                  ))}
                </select>
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
                <small>Projektnr. {draft.project_number || suggestion.assignment_project_number || "-"}</small>
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
  const warningGroups = useMemo(() => groupedExportWarnings(rows, invalidDocuments, exportIssues), [rows, invalidDocuments, exportIssues]);

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

      {warningGroups.length ? (
        <div className="booking-preview-summary" aria-label="Hinweise nach Ursache">
          {warningGroups.map((group) => (
            <div key={group.key} className={group.severity === "blocker" ? "is-blocker" : ""}>
              <span>{group.label}</span>
              <strong>{group.count}</strong>
              <small>{group.help}</small>
            </div>
          ))}
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
        <PreviewField
          label="Projekt"
          value={(
            <AssignmentLineSummary
              assignmentCode={row.assignment_code}
              assignmentKind={row.assignment_kind}
              projectNumber={row.assignment_project_number}
              tenantProfile={defaultTenantProfile("construction")}
            />
          )}
        />
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
          <PreviewField label="Regelstatus" value={formatAccountingRuleStatus(row)} />
          {row.accounting_rule_matches ? <PreviewField label="Passende Regeln" value={row.accounting_rule_matches} /> : null}
          <PreviewField label="Aufwandskonto" value={row.debit_account || "-"} />
          <PreviewField label="Gegenkonto" value={row.credit_account || "-"} />
          <PreviewField label="Gegenkonto Quelle" value={row.credit_account_source || "-"} />
          <PreviewField label="Steuer Quelle" value={row.tax_source || "-"} />
          <PreviewField label="Skontokonto" value={row.discount_account || "-"} />
          <PreviewField label="Skonto Quelle" value={row.discount_account_source || "-"} />
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
  const isNodeValue = typeof value === "object" && value !== null;
  return (
    <div className={numeric ? "preview-field numeric" : "preview-field"}>
      <span>{label}</span>
      {isNodeValue ? <div className="preview-field-value">{value}</div> : <strong>{value || "-"}</strong>}
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
    project_number: suggestion.assignment_project_number || "",
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
    project_number: raw.project_number || "",
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
    project_number: values.project_number?.trim() || null,
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

function supplierRulePayloadFromExtractionForm(values) {
  const supplierName = values.supplier_name?.trim();
  if (!supplierName) return null;
  const costCategories = costCategoryList(values.cost_category);
  return {
    match_text: supplierName,
    supplier_name: supplierName,
    customer_number: values.customer_number?.trim() || null,
    default_cost_category: costCategories.length ? costCategories : null,
    default_assignment_code: null,
    is_active: true,
  };
}

function normalizeBookingSuggestion(values) {
  return {
    booking_type: values.booking_type || "incoming_invoice",
    cost_category: values.cost_category || null,
    assignment_code: values.assignment_code?.trim() || null,
    project_number: values.project_number?.trim() || null,
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

function formatReextractionSummaryNotice(summary) {
  if (!summary?.analyzed_count) return "";
  const before = summary.before || {};
  const after = summary.after || {};
  return ` Verbessert: ${summary.improved_count || 0}. Allgemeine Kosten: ${before.general_cost || 0} -> ${after.general_cost || 0}. Zuordnung ungeklärt: ${before.assignment_unresolved || 0} -> ${after.assignment_unresolved || 0}.`;
}

function formatAiExtractionSummaryNotice(summary) {
  if (!summary?.analyzed_count) return "";
  return ` KI übernommen: ${summary.ai_applied_count || 0}. Verbessert: ${summary.improved_count || 0}. Restprobleme: ${summary.remaining_problem_count || 0}.`;
}

function formatSummaryBuckets(rows) {
  if (!rows?.length) return "-";
  return rows.slice(0, 3).map((row) => `${row.value}: ${row.count}`).join(" · ");
}

function bwaHintSummary(hints = []) {
  const summaryCount = hints.filter((hint) => hint.kind === "bwa_summary").length;
  const accountCount = hints.length - summaryCount;
  return [
    summaryCount ? `${summaryCount} BWA-Zeilen` : null,
    accountCount ? `${accountCount} Konto-/Lieferantenzeilen` : null,
  ].filter(Boolean).join(", ") || "-";
}

function bwaEffectSummary(hints = []) {
  if (!hints.length) return "-";
  const effects = Array.from(new Set(hints.map((hint) => hint.effect).filter(Boolean)));
  return effects.join(", ") || "Lernhinweis";
}

function formatHintAmounts(amounts = []) {
  if (!amounts.length) return "";
  return amounts.slice(0, 3).map((amount) => formatMoney(amount)).join(" / ");
}

function formatApiError(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const details = detail
      .slice(0, 4)
      .map((entry) => {
        const field = apiErrorFieldLabel(entry.loc);
        const message = entry.msg || entry.message || "ungültiger Wert";
        return field ? `${field}: ${message}` : message;
      })
      .join("; ");
    return details ? `${fallback}: ${details}${detail.length > 4 ? " ..." : ""}` : fallback;
  }
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

async function readApiError(response, fallback) {
  const result = await response.json().catch(() => null);
  const detail = result?.detail ?? result;
  const message = formatApiError(detail, `${fallback}: ${response.status}`);
  return {
    message,
    fields: apiFieldErrors(detail),
  };
}

function apiFieldErrors(detail) {
  const errors = {};
  if (!Array.isArray(detail)) return errors;
  detail.forEach((entry) => {
    const field = apiErrorFieldName(entry.loc);
    if (!field) return;
    errors[field] = entry.msg || entry.message || "Ungültiger Wert";
  });
  return errors;
}

function apiErrorFieldName(loc) {
  if (typeof loc === "string") return loc;
  if (!Array.isArray(loc)) return "";
  const field = [...loc].reverse().find((part) => typeof part === "string" && part !== "body");
  return field || "";
}

function apiErrorFieldLabel(loc) {
  const field = apiErrorFieldName(loc);
  const labels = {
    match_text: "Erkennungstext",
    supplier_name: "Lieferant",
    invoice_number: "Rechnung",
    invoice_date: "Datum",
    customer_number: "Unsere Kunden-Nr.",
    document_type: "Belegart",
    net_amount: "Netto",
    tax_amount: "USt",
    gross_amount: "Brutto",
    currency: "Währung",
    due_date: "Zahlbar bis",
    discount_due_date: "Skonto bis",
    discount_base: "Skonto-Basis",
    discount_amount: "Skonto",
    discounted_payable_amount: "Zahlbetrag Skonto",
    item_summary: "Artikel / Leistung",
    default_cost_category: "Kostenart",
    default_assignment_code: "Zuordnung",
    name: "Name",
    supplier_match_text: "Lieferant enthält",
    cost_category: "Kostenart",
    debit_account: "Aufwandskonto",
    credit_account: "Gegenkonto",
    tax_key: "Steuerschlüssel",
    tax_rate: "Steuersatz",
    discount_account: "Skontokonto",
  };
  return labels[field] || field;
}

function fieldError(errors, ...fields) {
  return fields.map((field) => errors?.[field]).find(Boolean) || "";
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
    fuel_receipt: "Tankbeleg",
    incoming_invoice: "Eingangsrechnung",
    project_document: "Projektunterlage",
    reverse_charge_certificate: "§13b-Nachweis",
    tax_exemption_certificate: "Freistellungsbescheinigung",
  };
  return labels[value] ?? value ?? "-";
}

function formatCertificateExpiryStatus(document) {
  const days = document?.days_until_expiry;
  if (document?.expiry_status === "expired") return "abgelaufen";
  if (document?.expiry_status === "soon") return days === 0 ? "läuft heute ab" : `läuft in ${days} Tagen ab`;
  if (document?.expiry_status === "valid") return "gültig";
  return "Ablauf unklar";
}

function certificateExpiryTone(status) {
  if (status === "expired") return "red";
  if (status === "soon" || status === "unknown") return "orange";
  return "green";
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

function groupedExportWarnings(rows, invalidDocuments = [], exportIssues = []) {
  const groups = new Map([
    ["accounting", { key: "accounting", label: "Kontierung", count: 0, severity: "warning", help: "Kontierungsregel, Aufwandskonto, Gegenkonto oder Mandantenstandard prüfen." }],
    ["payment", { key: "payment", label: "Zahlung", count: 0, severity: "warning", help: "Zahlungsentscheidung, Skonto oder Zahlungsdifferenz prüfen." }],
    ["assignment", { key: "assignment", label: "Zuordnung", count: 0, severity: "warning", help: "Bauvorhaben, Standort, Kostenstelle oder sonstige Zuordnung ergänzen." }],
    ["tax", { key: "tax", label: "Steuer", count: 0, severity: "warning", help: "Steuerschlüssel, Steuersatz und Vorsteueraufteilung prüfen." }],
    ["export", { key: "export", label: "Export", count: 0, severity: "blocker", help: "CSV-Download ist blockiert, bis die Exportprüfung sauber ist." }],
  ]);

  rows.forEach((row) => {
    const categories = parseDelimitedList(row.export_warning_categories)
      .map(normalizeWarningCategory)
      .filter(Boolean);
    if (categories.length) {
      categories.forEach((category) => incrementWarningCategory(groups, category));
      return;
    }
    exportWarningList(row).forEach((warning) => incrementWarningGroup(groups, warning));
  });
  invalidDocuments.forEach((document) => {
    (document.errors || []).forEach((error) => incrementWarningGroup(groups, error, true));
  });
  exportIssues.forEach((issue) => {
    const categories = Array.isArray(issue.error_categories)
      ? issue.error_categories.map(normalizeWarningCategory).filter(Boolean)
      : parseDelimitedList(issue.error_categories).map(normalizeWarningCategory).filter(Boolean);
    if (categories.length) {
      categories.forEach((category) => incrementWarningCategory(groups, category, true));
      return;
    }
    (issue.errors || []).forEach((error) => incrementWarningGroup(groups, error, true));
  });

  return Array.from(groups.values()).filter((group) => group.count > 0);
}

function parseDelimitedList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map((entry) => String(entry).trim()).filter(Boolean);
  return String(value)
    .split(/[;,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function normalizeWarningCategory(category) {
  const key = String(category || "").trim().toLowerCase();
  return ["accounting", "payment", "assignment", "tax", "export"].includes(key) ? key : "";
}

function incrementWarningCategory(groups, category, isBlocker = false) {
  const group = groups.get(category) || groups.get("export");
  group.count += 1;
  if (isBlocker) group.severity = "blocker";
}

function incrementWarningGroup(groups, warning, isBlocker = false) {
  const lower = String(warning || "").toLowerCase();
  let key = "export";
  if (lower.includes("kontierung") || lower.includes("konto") || lower.includes("mandantenstandard")) {
    key = "accounting";
  } else if (lower.includes("zahlung") || lower.includes("skonto") || lower.includes("differenz")) {
    key = "payment";
  } else if (lower.includes("zuordnung") || lower.includes("bauvorhaben") || lower.includes("kostenstelle") || lower.includes("standort")) {
    key = "assignment";
  } else if (lower.includes("steuer") || lower.includes("ust") || lower.includes("vorsteuer")) {
    key = "tax";
  }
  const group = groups.get(key) || groups.get("export");
  group.count += 1;
  if (isBlocker) group.severity = "blocker";
}

function uniqueList(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function formatAccountPair(row) {
  if (row.row_type === "payment_adjustment") return row.discount_account || "-";
  return [row.debit_account, row.credit_account].filter(Boolean).join(" / ") || "-";
}

function formatAccountingRuleStatus(row) {
  const labels = {
    ambiguous: "Mehrdeutig",
    matched: "Eindeutig",
    missing: "Fehlt",
  };
  return labels[row.accounting_rule_status] || (row.accounting_rule ? "Eindeutig" : "Fehlt");
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

function formatProjectStatus(project) {
  const sourceStatus = String(project?.source_status || "").trim();
  if (sourceStatus) return sourceStatus;
  return project?.is_active ? "aktiv" : "inaktiv";
}

function formatAssignmentAddress(assignment) {
  const cityLine = [assignment?.postal_code, assignment?.city].filter(Boolean).join(" ");
  return [assignment?.address_line, cityLine].filter(Boolean).join(", ") || "-";
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

function reviewAssignmentCode(assignment) {
  if (!assignment) return "";
  const code = assignment.code || "";
  const label = assignment.label || "";
  if (looksLikeProjectNumber(code) && label && !looksLikeProjectNumber(label)) return label;
  return code || label;
}

function findAssignmentOption(assignments, field, value) {
  const normalizedValue = normalizeSearchText(value);
  if (!normalizedValue) return null;
  if (field === "project_number") {
    return assignments.find((assignment) => normalizeSearchText(assignment.project_number) === normalizedValue) || null;
  }
  return assignments.find((assignment) => (
    normalizeSearchText(assignment.review_code) === normalizedValue
    || normalizeSearchText(assignment.code) === normalizedValue
    || normalizeSearchText(assignment.label) === normalizedValue
  )) || null;
}

function looksLikeProjectNumber(value) {
  return /^\d{2,4}-\d{3,}$/.test(String(value || "").trim());
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

function formatPdfTextDiagnostic(rawResult) {
  const source = formatPdfTextSource(rawResult?.pdf_text_source);
  if (!source) return "";
  const length = Number(rawResult?.pdf_text_length);
  const lengthLabel = Number.isFinite(length) ? `, ${length} Zeichen` : "";
  return `PDF-Text: ${source}${lengthLabel}`;
}

function formatPdfTextSource(source) {
  switch (source) {
    case "pypdf":
      return "digital";
    case "pymupdf":
      return "PDF-Layout";
    case "pymupdf_ocr":
      return "OCR deutsch/englisch";
    case "pypdf_short":
      return "zu kurz";
    case "unknown":
      return "";
    default:
      return source || "";
  }
}

function problemExtractionReasons(document) {
  const extraction = document?.extraction;
  if (!extraction) return [];
  if (Array.isArray(extraction.problem_reasons) && extraction.problem_reasons.length) {
    return extraction.problem_reasons;
  }
  const reasons = [];
  const confidence = Number(extraction.confidence);
  const source = String(extraction.raw_result?.source || extraction.source || "").toLowerCase();
  const rawResult = extraction.raw_result || {};

  if (source === "mock") {
    reasons.push("Mock-Erkennung");
  }
  if (source === "pdf_unreadable") {
    reasons.push("PDF nicht lesbar");
  }
  if (supplierNeedsReview(extraction.supplier_name, extraction.invoice_number)) {
    reasons.push("Lieferant ungeklärt");
  }
  if (!Number.isNaN(confidence) && confidence < 0.8) {
    reasons.push(`Sicherheit ${Math.round(confidence * 100)} %`);
  }
  if (extraction.warnings?.length) {
    reasons.push(`${extraction.warnings.length} ${extraction.warnings.length === 1 ? "Hinweis" : "Hinweise"}`);
  }
  if (!extraction.invoice_number) {
    reasons.push("Rechnungsnummer fehlt");
  }
  if (!extraction.invoice_date) {
    reasons.push("Datum fehlt");
  }
  if (extraction.gross_amount === null || extraction.gross_amount === undefined || extraction.gross_amount === "") {
    reasons.push("Brutto fehlt");
  }
  if (
    rawResult.assignment_type === "assignment_unresolved"
    || (rawResult.delivery_address && !rawResult.assignment_code && !rawResult.project_number)
  ) {
    reasons.push("Zuordnung ungeklärt");
  }
  if (assignmentMatchNeedsReview(rawResult.assignment_match)) {
    reasons.push("Zuordnung prüfen");
  }

  return reasons;
}

function isProblemExtraction(document) {
  return problemExtractionReasons(document).length > 0;
}

function documentMatchesProblemSummary(document, summaryReason) {
  const reasons = problemExtractionReasons(document);
  if (!summaryReason) return reasons.length > 0;
  return reasons.some((reason) => problemExtractionSummaryKey(reason) === summaryReason);
}

function summarizeProblemExtractionReasons(documents) {
  const counts = new Map();
  documents.forEach((document) => {
    problemExtractionReasons(document).forEach((reason) => {
      const summaryKey = problemExtractionSummaryKey(reason);
      counts.set(summaryKey, (counts.get(summaryKey) || 0) + 1);
    });
  });
  return Array.from(counts, ([reason, count]) => ({ reason, count }))
    .sort((left, right) => right.count - left.count || left.reason.localeCompare(right.reason, "de"))
    .slice(0, 6);
}

function buildProblemWorkItems(documents) {
  const groups = new Map();
  documents.forEach((document) => {
    problemExtractionReasons(document).forEach((reason) => {
      const key = problemExtractionSummaryKey(reason);
      const existing = groups.get(key) || {
        reason: key,
        count: 0,
        documents: [],
      };
      existing.count += 1;
      existing.documents.push(document);
      groups.set(key, existing);
    });
  });
  return Array.from(groups.values())
    .map((group) => {
      const meta = problemWorkMeta(group.reason);
      return {
        ...group,
        ...meta,
        priority: problemReasonPriority(group.reason),
        examples: group.documents.slice(0, 3).map((document) => document.original_filename).filter(Boolean),
      };
    })
    .sort((left, right) => right.priority - left.priority || right.count - left.count || left.reason.localeCompare(right.reason, "de"))
    .slice(0, 5);
}

function problemWorkMeta(reason) {
  const normalized = problemExtractionSummaryKey(reason);
  if (normalized === "PDF nicht lesbar") {
    return {
      severity: "blocker",
      severityLabel: "Blocker",
      action: "Vorschau/Text prüfen",
      help: "Ohne lesbaren Text braucht der Beleg OCR, bessere Datei oder manuelle Prüfung.",
    };
  }
  if (normalized === "Lieferant ungeklärt") {
    return {
      severity: "blocker",
      severityLabel: "Blocker",
      action: "Lieferant korrigieren",
      help: "Lieferant bestätigen, Kunden-Nr. ergänzen und bei Bedarf bewusst als Regel merken.",
    };
  }
  if (normalized === "Zuordnung ungeklärt") {
    return {
      severity: "warning",
      severityLabel: "Prüfen",
      action: "Projekt zuweisen",
      help: "Projekt-Nr. oder Bauvorhaben aus den Stammdaten wählen; danach Vorschlag neu erstellen.",
    };
  }
  if (normalized === "Zuordnung prüfen") {
    return {
      severity: "warning",
      severityLabel: "Prüfen",
      action: "Treffer bestätigen",
      help: "Die App hat ein Projekt vorgeschlagen, aber der Treffer sollte fachlich bestätigt werden.",
    };
  }
  if (normalized === "Niedrige Sicherheit") {
    return {
      severity: "review",
      severityLabel: "Unsicher",
      action: "Kernwerte prüfen",
      help: "Lieferant, Datum, Beträge und Kostenart kurz gegen die Vorschau prüfen.",
    };
  }
  if (normalized === "Offene Hinweise") {
    return {
      severity: "review",
      severityLabel: "Hinweis",
      action: "Hinweise lesen",
      help: "Warnungen kontrollieren; oft reicht Speichern oder Vorschlag neu erstellen.",
    };
  }
  if (normalized === "Rechnungsnummer fehlt" || normalized === "Datum fehlt" || normalized === "Brutto fehlt") {
    return {
      severity: "blocker",
      severityLabel: "Pflichtfeld",
      action: "Feld ergänzen",
      help: "Fehlenden Kernwert aus PDF/Text übernehmen, sonst blockiert der Export später.",
    };
  }
  return {
    severity: "review",
    severityLabel: "Prüfen",
    action: "Belege prüfen",
    help: "Problemgruppe öffnen, betroffene Belege korrigieren und danach neu vorschlagen.",
  };
}

function problemCorrectionFocusTarget(reason, document, tenantProfile = defaultTenantProfile("general")) {
  const normalized = problemExtractionSummaryKey(reason);
  const assignmentLabel = tenantProfile.assignment_label_singular || "Zuordnung";
  const targets = {
    "PDF nicht lesbar": {
      target: "preview",
      field: "",
      message: "Prüfe zuerst die Vorschau oder öffne die Datei. Wenn kein Text lesbar ist, muss der Beleg manuell oder per OCR geprüft werden.",
    },
    "Lieferant ungeklärt": {
      target: "extraction",
      field: "supplier_name",
      message: "Korrigiere den Lieferanten und ergänze die Kunden-Nr. Danach speichern und bei Bedarf bewusst als Regel merken.",
    },
    "Zuordnung ungeklärt": {
      target: "extraction",
      field: "assignment_code",
      message: `${assignmentLabel} aus den Stammdaten wählen. Projekt-Nr. und Zuordnungsart werden dann automatisch mitgesetzt.`,
    },
    "Zuordnung prüfen": {
      target: "extraction",
      field: "assignment_code",
      message: `Vorgeschlagenes ${assignmentLabel} gegen Rechnung, Adresse und Bauherr prüfen. Wenn falsch, aus Stammdaten neu wählen.`,
    },
    "Rechnungsnummer fehlt": {
      target: "extraction",
      field: "invoice_number",
      message: "Rechnungsnummer aus dem Beleg übernehmen und speichern.",
    },
    "Datum fehlt": {
      target: "extraction",
      field: "invoice_date",
      message: "Rechnungsdatum aus dem Beleg übernehmen und speichern.",
    },
    "Brutto fehlt": {
      target: "extraction",
      field: "gross_amount",
      message: "Bruttobetrag aus dem Beleg übernehmen und speichern.",
    },
    "Niedrige Sicherheit": {
      target: "extraction",
      field: "supplier_name",
      message: "Kernwerte Lieferant, Datum, Beträge, Kostenart und Zuordnung gegen die Vorschau prüfen.",
    },
    "Offene Hinweise": {
      target: "warnings",
      field: "",
      message: "Hinweise lesen und die betroffenen Felder korrigieren. Danach speichern und Vorschlag neu erstellen.",
    },
    "Mock-Erkennung": {
      target: "extraction",
      field: "supplier_name",
      message: "Dieser Beleg wurde nur grob erkannt. Lieferant, Datum, Beträge, Kostenart und Zuordnung vollständig gegenprüfen.",
    },
  };

  const target = targets[normalized] || {
    target: "extraction",
    field: "",
    message: "Beleg prüfen, betroffene Felder korrigieren, speichern und anschließend Vorschlag neu erstellen.",
  };

  return {
    documentId: document?.id,
    reason: normalized,
    ...target,
  };
}

function problemExtractionSummaryKey(reason) {
  if (/^Sicherheit\s+\d+\s*%$/.test(reason)) return "Niedrige Sicherheit";
  if (/^\d+\s+Hinweise?$/.test(reason)) return "Offene Hinweise";
  return reason;
}

function supplierNeedsReview(supplierName, invoiceNumber) {
  const supplier = String(supplierName ?? "").trim().replace(/\s+/g, " ");
  if (!supplier || supplier.toLocaleLowerCase("de-DE") === "unbekannter lieferant") return true;
  if (invoiceNumber && supplier.toLocaleLowerCase("de-DE") === String(invoiceNumber).trim().toLocaleLowerCase("de-DE")) return true;
  return /^[0-9]{5,}(?:\s+[0-9]{2,})?$/.test(supplier);
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
    reextract: "Neu-Extraktion",
    ai_extract: "KI-Prüfung",
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

function groupedApprovalIssues(issues) {
  const groups = new Map([
    ["accounting", { key: "accounting", label: "Kontierung", count: 0, severity: "blocker", help: "Regeln, Konten oder Skonto-Konten prüfen." }],
    ["payment", { key: "payment", label: "Zahlung", count: 0, severity: "blocker", help: "Zahlungsentscheidung oder Skonto auswählen." }],
    ["booking", { key: "booking", label: "Buchungszeilen", count: 0, severity: "blocker", help: "Kostenart, Betrag oder Split prüfen." }],
    ["extraction", { key: "extraction", label: "Extraktion", count: 0, severity: "blocker", help: "Belegdaten und Warnungen prüfen." }],
    ["export", { key: "export", label: "Export", count: 0, severity: "blocker", help: "Blocker für den Buchungsentwurf lösen." }],
    ["status", { key: "status", label: "Status", count: 0, severity: "blocker", help: "Beleg zuerst in den passenden Review-Status bringen." }],
    ["review", { key: "review", label: "Prüfung", count: 0, severity: "blocker", help: "Freigabehinweise prüfen." }],
  ]);

  issues.forEach((issue) => {
    const key = groups.has(issue?.category) ? issue.category : "review";
    const group = groups.get(key);
    group.count += 1;
    if (issue?.severity === "warning" && group.severity !== "blocker") {
      group.severity = "warning";
    }
  });

  return Array.from(groups.values()).filter((group) => group.count > 0);
}

function dedupeReviewCorrectionIssues(issues) {
  const seen = new Set();
  return issues.filter((issue) => {
    const key = `${issue.target || issue.category || ""}|${issue.line_no || ""}|${issue.field || ""}|${issue.code || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function reviewCorrectionButtonLabel(issue) {
  if (issue?.target === "payment_terms" || issue?.category === "payment") return "Zahlung wählen";
  if (isAssignmentIssue(issue)) return issue?.code === "unknown_assignment" ? "Zuordnung anlegen" : "Zuordnung prüfen";
  if (issue?.target === "extraction" || issue?.category === "extraction") return issue?.field ? `Extraktion: ${apiErrorFieldLabel(issue.field)}` : "Extraktion prüfen";
  if (issue?.target === "booking_lines" || issue?.category === "booking") return issue?.line_no ? `Zeile ${issue.line_no} prüfen` : "Buchungszeilen prüfen";
  if (issue?.target === "booking_export" || issue?.category === "export") return "Exportblocker prüfen";
  return "Zur Korrektur";
}

function reviewCorrectionNotice(issue) {
  if (issue?.target === "payment_terms" || issue?.category === "payment") {
    return "Bitte Zahlungsoption wählen. Danach die Freigabe erneut starten.";
  }
  if (issue?.target === "extraction" || issue?.category === "extraction") {
    return "Bitte Extraktionsdaten prüfen und speichern. Danach die Freigabe erneut starten.";
  }
  if (isAssignmentIssue(issue)) {
    return "Bitte Zuordnung prüfen und speichern. Danach die Freigabe erneut starten.";
  }
  const lineNo = issue?.line_no ? String(issue.line_no) : "";
  if (lineNo) {
    return `Bitte Buchungszeile ${lineNo} prüfen und speichern. Danach die Freigabe erneut starten.`;
  }
  return "Bitte Buchungsvorschlag prüfen und speichern. Danach die Freigabe erneut starten.";
}

function isAssignmentIssue(issue) {
  const errorCodes = Array.isArray(issue?.error_codes) ? issue.error_codes : [];
  return issue?.code === "missing_assignment"
    || issue?.code === "unknown_assignment"
    || issue?.category === "assignment"
    || issue?.target === "assignment_units"
    || errorCodes.includes("missing_assignment")
    || errorCodes.includes("unknown_assignment");
}

function assignmentIssueContext(issue, tenantProfile) {
  const linePrefix = issue?.line_no ? `Zeile ${issue.line_no}: ` : "";
  const assignmentLabel = tenantProfile?.assignment_label_singular || "Zuordnung";
  if (issue?.assignment_code) {
    return `${linePrefix}${assignmentLabel} ${issue.assignment_code} fehlt in den Stammdaten.`;
  }
  if (issue?.assignment_hint) {
    return `${linePrefix}${assignmentLabel} zu "${issue.assignment_hint}" ist noch nicht eindeutig zugeordnet.`;
  }
  return `${linePrefix}${assignmentLabel} fehlt in der Buchungszeile.`;
}

function assignmentUnitFormFromApprovalIssue(issue, document, tenantProfile) {
  const rawResult = document?.extraction?.raw_result || {};
  const code = issue?.assignment_code || rawResult.assignment_code || rawResult.project_code || "";
  const label = issue?.assignment_hint || rawResult.customer_reference || rawResult.delivery_address || "";
  const kind = issue?.assignment_kind || rawResult.assignment_kind || tenantProfile?.default_assignment_kind || "cost_object";
  return {
    code,
    label: label && label !== code ? label : "",
    kind,
    project_number: "",
    revenue_relevant: false,
    aliases: "",
  };
}

function focusReviewDocumentCard(documentId, options = {}) {
  if (!documentId || typeof window === "undefined") return;
  const element = window.document.querySelector(`[data-document-id="${documentId}"]`);
  element?.scrollIntoView({ behavior: "smooth", block: "center" });
  if (options.focusAction === false) return;
  const actionButton = Array.from(element?.querySelectorAll("button:not([disabled])") || [])
    .find((button) => /final freigeben|details|ansehen/i.test(button.textContent || ""));
  actionButton?.focus?.({ preventScroll: true });
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
  if (issues.some((issue) => issue.code === "ambiguous_accounting_rule")) return "Kontierungsregel mehrdeutig";
  if (issues.some((issue) => issue.code === "missing_discount_account")) return "Skontokonto fehlt";
  if (issues.some((issue) => issue.code === "incomplete_accounting_rule")) return "Kontierungsregel unvollständig";
  return "Kontierungsregel fehlt";
}

function accountingRuleIssueContext(issue) {
  return [
    issue?.supplier_name ? `Lieferant: ${issue.supplier_name}` : null,
    issue?.cost_category ? `Kostenart: ${formatCostCategory(issue.cost_category)}` : null,
    issue?.message && !String(issue.message).includes("Mehrere Regeln") ? issue.message : null,
  ].filter(Boolean).join(" · ");
}

function accountingRuleMatchLabel(rule) {
  const ruleName = rule?.name || "Regel öffnen";
  const details = [
    rule?.supplier_match_text ? `Erkennung: ${rule.supplier_match_text}` : null,
    rule?.cost_category_label || (rule?.cost_category ? formatCostCategory(rule.cost_category) : null),
  ].filter(Boolean);
  return details.length ? `${ruleName} (${details.join(", ")})` : ruleName;
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

function accountingRuleFormFromApprovalIssue(issue, document) {
  const supplierName = issue?.supplier_name || document?.extraction?.supplier_name || "";
  const costCategory = issue?.cost_category ?? document?.booking_suggestions?.[0]?.cost_category ?? "";
  const suggestedName = issue?.suggested_name || defaultAccountingRuleName(supplierName, costCategory);
  return {
    name: suggestedName,
    supplier_match_text: supplierName,
    cost_category: costCategory,
    debit_account: issue?.suggested_debit_account || "",
    credit_account: "",
    tax_key: "",
    tax_rate: "19.00",
    discount_account: "",
  };
}

function validateAccountingRuleForm(form) {
  const errors = {};
  if (!String(form?.name || "").trim()) errors.name = "Regelname fehlt.";
  if (!String(form?.debit_account || "").trim()) errors.debit_account = "Aufwandskonto fehlt.";
  if (!String(form?.credit_account || "").trim()) errors.credit_account = "Gegenkonto fehlt.";
  if (!String(form?.tax_key || "").trim() && !String(form?.tax_rate || "").trim()) {
    errors.tax_key = "Steuerschlüssel oder Steuersatz fehlt.";
    errors.tax_rate = "Steuerschlüssel oder Steuersatz fehlt.";
  }
  return errors;
}

function bestBwaAccountHint(issue) {
  const hints = Array.isArray(issue?.bwa_account_hints) ? issue.bwa_account_hints : [];
  if (issue?.suggested_debit_account) {
    return (
      hints.find((hint) => hint?.account === issue.suggested_debit_account)
      || { account: issue.suggested_debit_account, label: issue.suggested_debit_account_label, period: null }
    );
  }
  return hints.find((hint) => hint?.account) || null;
}

function formatBwaAccountHint(hint) {
  const parts = [
    hint?.account,
    hint?.label,
    hint?.period ? `BWA ${hint.period}` : null,
  ].filter(Boolean);
  return parts.join(" · ");
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

function accountingSuggestionProfile(source) {
  if (typeof source === "string") {
    return { accounting_framework: source };
  }
  return source || {};
}

function applyAccountingSuggestions(form, source) {
  const profile = accountingSuggestionProfile(source);
  const framework = accountingFramework(profile.accounting_framework);
  return {
    ...form,
    debit_account: form.debit_account || firstAccountSuggestion(framework, "debit", form.cost_category),
    credit_account: form.credit_account || profile.default_credit_account || firstAccountSuggestion(framework, "credit", form.cost_category),
    tax_key: form.tax_key || profile.default_tax_key || "",
    tax_rate: form.tax_rate || profile.default_tax_rate || "19.00",
    discount_account: form.discount_account || profile.default_discount_account || firstAccountSuggestion(framework, "discount", form.cost_category),
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

function documentSearchText(document) {
  const extraction = document?.extraction || {};
  const rawResult = extraction.raw_result || {};
  return normalizeSearchText([
    document?.original_filename,
    document?.normalized_filename,
    document?.tenant_id,
    document?.status,
    extraction.supplier_name,
    extraction.invoice_number,
    extraction.invoice_date,
    extraction.gross_amount,
    rawResult.assignment_code,
    rawResult.project_number,
    rawResult.project_name,
    rawResult.customer_reference,
    rawResult.delivery_address,
    rawResult.product_name,
    ...(extraction.problem_reasons || []),
  ].filter(Boolean).join(" "));
}

function compareReviewDocuments(left, right, sortKey) {
  const direction = sortKey.endsWith("_asc") ? 1 : -1;
  const key = sortKey.replace(/_(asc|desc)$/, "");
  const leftValue = reviewSortValue(left, key);
  const rightValue = reviewSortValue(right, key);
  const comparison = compareReviewValues(leftValue, rightValue);
  if (comparison !== 0) return comparison * direction;
  return compareReviewValues(reviewSortValue(left, "created"), reviewSortValue(right, "created")) * -1;
}

function reviewSortValue(document, key) {
  const extraction = document?.extraction || {};
  if (key === "created") return document?.created_at || "";
  if (key === "problem") return problemPriorityScore(document);
  if (key === "date") return extraction.invoice_date || "";
  if (key === "amount") return Number.parseFloat(String(extraction.gross_amount ?? "").replace(",", ".")) || 0;
  if (key === "supplier") return extraction.supplier_name || "";
  if (key === "filename") return document?.original_filename || "";
  return "";
}

function problemPriorityScore(document) {
  return problemExtractionReasons(document).reduce((score, reason) => Math.max(score, problemReasonPriority(reason)), 0);
}

function problemReasonPriority(reason) {
  const normalized = problemExtractionSummaryKey(reason);
  const priorities = {
    "PDF nicht lesbar": 100,
    "Lieferant ungeklärt": 90,
    "Zuordnung ungeklärt": 80,
    "Zuordnung prüfen": 78,
    "Brutto fehlt": 75,
    "Rechnungsnummer fehlt": 70,
    "Datum fehlt": 65,
    "Niedrige Sicherheit": 50,
    "Mock-Erkennung": 45,
    "Offene Hinweise": 30,
  };
  return priorities[normalized] ?? 10;
}

function compareReviewValues(left, right) {
  if (typeof left === "number" || typeof right === "number") {
    return (left || 0) - (right || 0);
  }
  return String(left ?? "").localeCompare(String(right ?? ""), "de", { numeric: true, sensitivity: "base" });
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
      default_credit_account: "70000",
      default_tax_key: "",
      default_tax_rate: "19.00",
      default_discount_account: "3736",
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
      default_credit_account: "70000",
      default_tax_key: "",
      default_tax_rate: "19.00",
      default_discount_account: "3736",
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
      default_credit_account: "70000",
      default_tax_key: "",
      default_tax_rate: "19.00",
      default_discount_account: "3736",
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
      default_credit_account: "70000",
      default_tax_key: "",
      default_tax_rate: "19.00",
      default_discount_account: "3736",
    },
  };
  return templates[industry] ?? templates.general;
}

createRoot(document.getElementById("root")).render(<App />);
