"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import type { User } from "@/types";

interface RuleInfo {
  rule_id: string;
  name: string;
  description: string;
  severity: string;
  is_active: boolean;
  is_custom: boolean;
}

interface ComplianceConfig {
  active_rule_ids: string[];
  default_action: string;
  updated_at: string;
}

interface CustomRuleResponse {
  id: string;
  rule_id: string;
  name: string;
  description: string;
  pattern: string;
  pattern_type: string;
  severity: string;
  action: string;
  created_by: string;
  created_at: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-blue-100 text-blue-700",
};

export default function CompliancePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [rules, setRules] = useState<RuleInfo[]>([]);
  const [config, setConfig] = useState<ComplianceConfig | null>(null);
  const [defaultAction, setDefaultAction] = useState("flag");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // Custom rule form
  const [showCreateRule, setShowCreateRule] = useState(false);
  const [newRuleId, setNewRuleId] = useState("");
  const [newRuleName, setNewRuleName] = useState("");
  const [newRuleDesc, setNewRuleDesc] = useState("");
  const [newRulePattern, setNewRulePattern] = useState("");
  const [newRuleType, setNewRuleType] = useState("regex");
  const [newRuleSeverity, setNewRuleSeverity] = useState("high");
  const [newRuleAction, setNewRuleAction] = useState("flag");
  const [creatingRule, setCreatingRule] = useState(false);
  const [ruleError, setRuleError] = useState("");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    load();
  }, [router]);

  async function load() {
    const [u, rs, cfg] = await Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<RuleInfo[]>("/api/v1/compliance/rules"),
      api.get<ComplianceConfig>("/api/v1/compliance/config"),
    ]);
    if (!u.roles.includes("admin")) { router.replace("/"); return; }
    setUser(u);
    setRules(rs);
    setConfig(cfg);
    setDefaultAction(cfg.default_action);
  }

  function toggleRule(rule_id: string) {
    setRules((prev) =>
      prev.map((r) => r.rule_id === rule_id ? { ...r, is_active: !r.is_active } : r)
    );
  }

  async function saveConfig() {
    setSaving(true);
    setSaveMsg("");
    try {
      const active = rules.filter((r) => r.is_active).map((r) => r.rule_id);
      const updated = await api.put<ComplianceConfig>("/api/v1/compliance/config", {
        active_rule_ids: active,
        default_action: defaultAction,
      });
      setConfig(updated);
      setSaveMsg("Saved.");
    } catch (e: unknown) {
      setSaveMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(""), 3000);
    }
  }

  async function handleCreateRule(e: FormEvent) {
    e.preventDefault();
    setCreatingRule(true);
    setRuleError("");
    try {
      const created = await api.post<CustomRuleResponse>("/api/v1/compliance/rules/custom", {
        rule_id: newRuleId,
        name: newRuleName,
        description: newRuleDesc,
        pattern: newRulePattern,
        pattern_type: newRuleType,
        severity: newRuleSeverity,
        action: newRuleAction,
      });
      setRules((prev) => [...prev, {
        rule_id: created.rule_id,
        name: created.name,
        description: created.description,
        severity: created.severity,
        is_active: false,
        is_custom: true,
      }]);
      setShowCreateRule(false);
      setNewRuleId(""); setNewRuleName(""); setNewRuleDesc("");
      setNewRulePattern(""); setNewRuleType("regex");
      setNewRuleSeverity("high"); setNewRuleAction("flag");
    } catch (e: unknown) {
      setRuleError(e instanceof Error ? e.message : "Failed to create rule");
    } finally {
      setCreatingRule(false);
    }
  }

  async function deleteCustomRule(rule_id: string) {
    if (!confirm(`Delete custom rule "${rule_id}"?`)) return;
    await api.delete(`/api/v1/compliance/rules/custom/${rule_id}`);
    setRules((prev) => prev.filter((r) => r.rule_id !== rule_id));
  }

  if (!user) return null;

  const builtinRules = rules.filter((r) => !r.is_custom);
  const customRules = rules.filter((r) => r.is_custom);

  return (
    <main className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
          <div>
            <h2 className="font-semibold text-slate-800">Compliance Configuration</h2>
            <p className="text-xs text-slate-400">Control which rules run during document ingestion</p>
          </div>
          <div className="flex items-center gap-3">
            {saveMsg && <span className="text-xs text-green-600">{saveMsg}</span>}
            <button
              onClick={saveConfig}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* Default action */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">Default Action on Violation</h3>
            <div className="flex gap-6">
              {[
                { value: "allow", label: "Allow", desc: "Log and continue" },
                { value: "flag", label: "Flag", desc: "Mark flagged, continue" },
                { value: "block", label: "Block", desc: "Reject upload (admin override)" },
              ].map((opt) => (
                <label key={opt.value} className="flex cursor-pointer items-start gap-2">
                  <input
                    type="radio"
                    name="defaultAction"
                    value={opt.value}
                    checked={defaultAction === opt.value}
                    onChange={() => setDefaultAction(opt.value)}
                    className="mt-0.5 accent-blue-600"
                  />
                  <div>
                    <p className="text-sm font-medium text-slate-700">{opt.label}</p>
                    <p className="text-xs text-slate-400">{opt.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Built-in rules */}
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-700">Built-in Rules</h3>
            </div>
            <ul className="divide-y divide-slate-100">
              {builtinRules.map((rule) => (
                <li key={rule.rule_id} className="flex items-center gap-4 px-5 py-3">
                  <label className="relative inline-flex cursor-pointer items-center">
                    <input
                      type="checkbox"
                      checked={rule.is_active}
                      onChange={() => toggleRule(rule.rule_id)}
                      className="sr-only peer"
                    />
                    <div className="h-5 w-9 rounded-full bg-slate-200 peer-checked:bg-blue-600 transition-colors after:absolute after:left-0.5 after:top-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4" />
                  </label>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-800">{rule.name}</span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${SEVERITY_COLORS[rule.severity] ?? ""}`}>
                        {rule.severity}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500">{rule.description}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* Custom rules */}
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-700">Custom Rules</h3>
              <button
                onClick={() => setShowCreateRule(true)}
                className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
              >
                + Add Rule
              </button>
            </div>
            {customRules.length === 0 ? (
              <p className="px-5 py-4 text-sm text-slate-400">No custom rules yet.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {customRules.map((rule) => (
                  <li key={rule.rule_id} className="flex items-center gap-4 px-5 py-3">
                    <label className="relative inline-flex cursor-pointer items-center">
                      <input
                        type="checkbox"
                        checked={rule.is_active}
                        onChange={() => toggleRule(rule.rule_id)}
                        className="sr-only peer"
                      />
                      <div className="h-5 w-9 rounded-full bg-slate-200 peer-checked:bg-blue-600 transition-colors after:absolute after:left-0.5 after:top-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4" />
                    </label>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-800">{rule.name}</span>
                        <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">custom</span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${SEVERITY_COLORS[rule.severity] ?? ""}`}>
                          {rule.severity}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500">{rule.description}</p>
                    </div>
                    <button
                      onClick={() => deleteCustomRule(rule.rule_id)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {config && (
            <p className="text-xs text-slate-400">
              Last updated: {new Date(config.updated_at).toLocaleString()}
            </p>
          )}
        </div>

      {/* Create custom rule dialog */}
      {showCreateRule && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="font-semibold">New Custom Rule</h3>
              <button onClick={() => setShowCreateRule(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreateRule} className="space-y-3 px-5 py-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Rule ID (slug)</label>
                  <input type="text" value={newRuleId} onChange={(e) => setNewRuleId(e.target.value)} required placeholder="my_rule"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Name</label>
                  <input type="text" value={newRuleName} onChange={(e) => setNewRuleName(e.target.value)} required
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Description</label>
                <input type="text" value={newRuleDesc} onChange={(e) => setNewRuleDesc(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Pattern</label>
                <input type="text" value={newRulePattern} onChange={(e) => setNewRulePattern(e.target.value)} required placeholder="Regex or keyword"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Type</label>
                  <select value={newRuleType} onChange={(e) => setNewRuleType(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm">
                    <option value="regex">Regex</option>
                    <option value="keyword">Keyword</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Severity</label>
                  <select value={newRuleSeverity} onChange={(e) => setNewRuleSeverity(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm">
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Action</label>
                  <select value={newRuleAction} onChange={(e) => setNewRuleAction(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-2 py-2 text-sm">
                    <option value="block">Block</option>
                    <option value="flag">Flag</option>
                    <option value="allow">Allow</option>
                  </select>
                </div>
              </div>
              {ruleError && <p className="text-sm text-red-600">{ruleError}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setShowCreateRule(false)}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Cancel</button>
                <button type="submit" disabled={creatingRule}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40">
                  {creatingRule ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
