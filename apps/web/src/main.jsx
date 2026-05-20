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
          {isSubmitting ? "Pruefe ..." : "Einloggen"}
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
            <span>PDFs, Bilder oder exportierte Rechnungen fuer den ausgewaehlten Mandanten.</span>
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
                    <Field label="Zuordnungs-Code" value={document.extraction.raw_result?.assignment_code || document.extraction.raw_result?.project_code} />
                    <Field label="Zuordnungsart" value={formatAssignmentKind(document.extraction.raw_result?.assignment_kind)} />
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
        </>
      ) : null}

      {activeView === "masterdata" && user?.role === "admin" ? (
        <MasterdataAdmin apiFetch={apiFetch} tenantId={activeTenantId} />
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

function MasterdataAdmin({ apiFetch, tenantId }) {
  const [assignmentUnits, setAssignmentUnits] = useState([]);
  const [supplierRules, setSupplierRules] = useState([]);
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

  return (
    <section className="admin-panel">
      <div className="section-header">
        <h2>Stammdaten</h2>
        <span>{tenantId}</span>
      </div>
      {message ? <p className="notice">{message}</p> : null}

      <h3>Zuordnungen</h3>
      <form className="compact-form" onSubmit={createAssignment}>
        <input placeholder="Code, z.B. Wewe20" value={assignmentForm.code} onChange={(event) => setAssignmentForm({ ...assignmentForm, code: event.target.value })} required />
        <input placeholder="Name" value={assignmentForm.label} onChange={(event) => setAssignmentForm({ ...assignmentForm, label: event.target.value })} required />
        <select value={assignmentForm.kind} onChange={(event) => setAssignmentForm({ ...assignmentForm, kind: event.target.value })}>
          <option value="construction_project">Bauvorhaben</option>
          <option value="cost_object">Kostenobjekt</option>
          <option value="vehicle">Fahrzeug</option>
          <option value="subscription">Abo/Vertrag</option>
          <option value="department">Bereich</option>
        </select>
        <input placeholder="Aliase, komma-getrennt" value={assignmentForm.aliases} onChange={(event) => setAssignmentForm({ ...assignmentForm, aliases: event.target.value })} />
        <label className="inline-check">
          <input type="checkbox" checked={assignmentForm.revenue_relevant} onChange={(event) => setAssignmentForm({ ...assignmentForm, revenue_relevant: event.target.checked })} />
          umsatzrelevant
        </label>
        <button type="submit">Zuordnung anlegen</button>
      </form>
      <div className="table-list">
        {assignmentUnits.map((assignment) => (
          <div className="table-row" key={assignment.id}>
            <strong>{assignment.code}</strong>
            <span>{assignment.label}</span>
            <span>{formatAssignmentKind(assignment.kind)}</span>
            <span>{assignment.revenue_relevant ? "umsatzrelevant" : "intern/allgemein"}</span>
          </div>
        ))}
      </div>

      <h3>Lieferantenregeln</h3>
      <form className="compact-form" onSubmit={createSupplierRule}>
        <input placeholder="Erkennungstext" value={supplierForm.match_text} onChange={(event) => setSupplierForm({ ...supplierForm, match_text: event.target.value })} required />
        <input placeholder="Lieferantenname" value={supplierForm.supplier_name} onChange={(event) => setSupplierForm({ ...supplierForm, supplier_name: event.target.value })} required />
        <input placeholder="Unsere Kunden-Nr." value={supplierForm.customer_number} onChange={(event) => setSupplierForm({ ...supplierForm, customer_number: event.target.value })} />
        <select value={supplierForm.default_cost_category} onChange={(event) => setSupplierForm({ ...supplierForm, default_cost_category: event.target.value })}>
          <option value="material">Material</option>
          <option value="subcontractor">Fremdleistung</option>
          <option value="fuel_vehicle">Fahrzeug/Tanken</option>
          <option value="software_subscription">Software/Abo</option>
          <option value="security_subscription">Ueberwachung/Abo</option>
          <option value="general_overhead">Sonstige Gemeinkosten</option>
        </select>
        <input placeholder="Zuordnungs-Code optional" value={supplierForm.default_assignment_code} onChange={(event) => setSupplierForm({ ...supplierForm, default_assignment_code: event.target.value })} />
        <button type="submit">Regel anlegen</button>
      </form>
      <div className="table-list">
        {supplierRules.map((rule) => (
          <div className="table-row" key={rule.id}>
            <strong>{rule.supplier_name}</strong>
            <span>{rule.match_text}</span>
            <span>{rule.customer_number || "-"}</span>
            <span>{formatCostCategory(rule.default_cost_category)}</span>
            <span>{rule.default_assignment_code || "-"}</span>
          </div>
        ))}
      </div>
    </section>
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
  if (rawResult?.assignment_code) return `${formatAssignmentKind(rawResult.assignment_kind)} ${rawResult.assignment_code}`;
  if (rawResult?.project_code) return `BV ${rawResult.project_code}`;
  const labels = {
    general_cost: "Allgemeine Kosten",
    assignment_unresolved: "Zuordnung ungeklaert",
    project_unresolved: "BV ungeklaert",
    assigned: "Zugeordnet",
  };
  return labels[rawResult?.assignment_type] ?? null;
}

function formatAssignmentKind(value) {
  const labels = {
    construction_project: "Bauvorhaben",
    cost_object: "Kostenobjekt",
    vehicle: "Fahrzeug",
    subscription: "Abo/Vertrag",
    department: "Bereich",
  };
  return labels[value] ?? value;
}

function formatCostCategory(value) {
  const labels = {
    fuel_vehicle: "Fahrzeug/Tanken",
    general_overhead: "Sonstige Gemeinkosten",
    material: "Material",
    security_subscription: "Ueberwachung/Abo",
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

createRoot(document.getElementById("root")).render(<App />);
