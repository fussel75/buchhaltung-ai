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
  const [tenantProfile, setTenantProfile] = useState(defaultTenantProfile("construction"));

  const canUpload = useMemo(() => tenantId.trim().length > 0, [tenantId]);
  const activeTenantId = tenantId.trim();

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

  return (
    <main className="app">
      <section className="toolbar">
        <div>
          <p className="eyebrow">buchhaltung-ai</p>
          <h1>Beleg-Upload</h1>
        </div>
        <div className="session-tools">
          <span>{user?.display_name || user?.email}</span>
          <button type="button" onClick={logout}>Logout</button>
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

      <nav className="view-tabs">
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

      {notice ? <p className="notice">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {activeView === "review" ? (
        <>
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
          <h2>Review-Queue</h2>
          <span>{documents.length} Belege</span>
        </div>
        {documents.length === 0 ? (
          <p className="empty">Noch keine Belege für diesen Mandanten.</p>
        ) : (
          <div className="queue">
            {documents.map((document) => (
              <article key={document.id} className="document-card">
                <div className="document-head">
                  <div>
                    <strong>{document.original_filename}</strong>
                    <span>{document.normalized_filename || document.tenant_id}</span>
                  </div>
                  <div className="document-actions">
                    <span className="status">{formatStatus(document.status)}</span>
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
        </>
      ) : null}

      {activeView === "masterdata" && user?.role === "admin" ? (
        <MasterdataAdmin apiFetch={apiFetch} tenantId={activeTenantId} tenantProfile={tenantProfile} onProfileSaved={setTenantProfile} />
      ) : null}

      {activeView === "users" && user?.role === "admin" ? (
        <UserAdmin apiFetch={apiFetch} currentUser={user} />
      ) : null}
    </main>
  );
}

function UserAdmin({ apiFetch, currentUser }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ email: "", password: "", display_name: "", role: "user" });
  const [message, setMessage] = useState("");

  const loadUsers = useCallback(async () => {
    const response = await apiFetch("/users");
    if (!response.ok) throw new Error(`Benutzer konnten nicht geladen werden: ${response.status}`);
    const result = await response.json();
    setUsers(result.users ?? []);
  }, [apiFetch]);

  useEffect(() => {
    loadUsers().catch((error) => setMessage(error.message));
  }, [loadUsers]);

  async function createUser(event) {
    event.preventDefault();
    setMessage("");
    const response = await apiFetch("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      setMessage(result.detail || `Benutzer konnte nicht angelegt werden: ${response.status}`);
      return;
    }
    setForm({ email: "", password: "", display_name: "", role: "user" });
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
  const [profileForm, setProfileForm] = useState(tenantProfile);
  const [assignmentForm, setAssignmentForm] = useState({
    code: "",
    label: "",
    kind: "cost_object",
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
  const [message, setMessage] = useState("");

  useEffect(() => {
    setProfileForm(tenantProfile);
    setAssignmentForm((current) => ({
      ...current,
      kind: tenantProfile.default_assignment_kind || current.kind,
    }));
  }, [tenantProfile]);

  const loadMasterdata = useCallback(async () => {
    const [assignmentsResponse, suppliersResponse] = await Promise.all([
      apiFetch(`/masterdata/assignment-units?tenant_id=${encodeURIComponent(tenantId)}`),
      apiFetch(`/masterdata/supplier-rules?tenant_id=${encodeURIComponent(tenantId)}`),
    ]);
    if (!assignmentsResponse.ok || !suppliersResponse.ok) {
      throw new Error("Stammdaten konnten nicht geladen werden.");
    }
    const assignmentsResult = await assignmentsResponse.json();
    const suppliersResult = await suppliersResponse.json();
    setAssignmentUnits(assignmentsResult.assignment_units ?? []);
    setSupplierRules(suppliersResult.supplier_rules ?? []);
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
    setAssignmentForm({ code: "", label: "", kind: "cost_object", revenue_relevant: false, aliases: "" });
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
            <FormField label="Einzahl">
              <input placeholder="Bauvorhaben" value={profileForm.assignment_label_singular || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_label_singular: event.target.value })} required />
            </FormField>
            <FormField label="Mehrzahl">
              <input placeholder="Bauvorhaben" value={profileForm.assignment_label_plural || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_label_plural: event.target.value })} required />
            </FormField>
            <FormField label="Spaltenname">
              <input placeholder="Zuordnung" value={profileForm.assignment_code_label || ""} onChange={(event) => setProfileForm({ ...profileForm, assignment_code_label: event.target.value })} required />
            </FormField>
            <FormField label="Kürzel">
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
          <form className="form-grid" onSubmit={createAssignment}>
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
              <span>Name</span>
              <span>Art</span>
              <span>Status</span>
              <span>Aktiv</span>
            </div>
            {assignmentUnits.map((assignment) => (
              <div className="data-row" key={assignment.id}>
                <strong>{formatAssignmentCode(assignment.code, assignment.kind, tenantProfile)}</strong>
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

function formatSize(sizeBytes) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  return `${Math.round(sizeBytes / 1024)} KB`;
}

function formatStatus(status) {
  const labels = {
    review_pending: "Prüfen",
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

function projectSummaryLines(rawResult, tenantProfile = defaultTenantProfile("general")) {
  if (rawResult?.assignment_code) {
    return [formatAssignmentCode(rawResult.assignment_code, rawResult.assignment_kind, tenantProfile)];
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
