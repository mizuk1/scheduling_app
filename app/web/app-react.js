import React, { useEffect, useMemo, useRef, useState } from "https://esm.sh/react@18.2.0";
import { createRoot } from "https://esm.sh/react-dom@18.2.0/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

const SHIFT_TYPES = ["LUNCH", "DINNER"];
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_KEYS = [
  "SUNDAY",
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
];

const fmtDate = (value) => new Date(value).toISOString().slice(0, 10);
const toDate = (value) => new Date(`${value}T00:00:00`);
const addDays = (value, amount) => {
  const date = new Date(value);
  date.setDate(date.getDate() + amount);
  return date;
};

const getWeekStart = (value) => {
  const date = toDate(value);
  const day = date.getDay();
  const offset = day === 0 ? -6 : 1 - day;
  return fmtDate(addDays(date, offset));
};

const getWeekDates = (weekStart) => {
  const start = toDate(weekStart);
  return Array.from({ length: 7 }, (_, index) => fmtDate(addDays(start, index)));
};

const getDayOfWeek = (value) => DAY_KEYS[toDate(value).getDay()];

const isIsoDate = (value) => /^\d{4}-\d{2}-\d{2}$/.test(value || "");

const normalizeIsoDate = (value, fallback) => {
  if (!isIsoDate(value)) return fallback;
  const parsed = toDate(value);
  return Number.isNaN(parsed.getTime()) ? fallback : value;
};

const shiftKey = (date, shiftType) => `${date}__${shiftType}`;

const buildShiftFingerprint = (shift) => {
  const assignments = [...(shift.assignments || [])]
    .map((item) => `${item.role_name}:${item.employee_name || "UNASSIGNED"}`)
    .sort();
  return assignments.join("|");
};

const buildDayMap = (shifts) => {
  const map = new Map();
  (shifts || []).forEach((shift) => {
    map.set(shift.shift_type, buildShiftFingerprint(shift));
  });
  return map;
};

const buildWeekMap = (shifts) => {
  const map = new Map();
  (shifts || []).forEach((shift) => {
    map.set(shiftKey(shift.date, shift.shift_type), buildShiftFingerprint(shift));
  });
  return map;
};

const diffMaps = (beforeMap, afterMap) => {
  const keys = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  const changed = new Set();
  keys.forEach((key) => {
    if ((beforeMap.get(key) || "") !== (afterMap.get(key) || "")) {
      changed.add(key);
    }
  });
  return changed;
};

const fetchJson = async (url, options = {}) => {
  const response = await fetch(url, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Request failed");
  }
  return response.json();
};

const summarizeResponse = (payload) => {
  if (!payload) return "Done.";
  if (payload.action_type === "AUTOFILL_DAY") {
    const results = payload.result?.results || [];
    return results.map((item) => `${item.shift_type}: ${item.created} filled`).join(" | ");
  }
  if (payload.action_type === "LIST_SCHEDULE") {
    return `Loaded ${payload.result?.length || 0} shifts.`;
  }
  if (payload.action_type === "SWAP_ASSIGNMENT") {
    return `Swap applied (old: ${payload.result?.old_employee_id}, new: ${payload.result?.new_employee_id}).`;
  }
  if (payload.action_type === "SET_RULE") {
    return "Rule updated.";
  }
  return "Done.";
};

const getChangedShiftLabels = (changedKeys) => {
  if (!changedKeys || changedKeys.size === 0) {
    return [];
  }

  return [...changedKeys]
    .sort()
    .map((key) => {
      const [date, shiftType] = key.split("__");
      return `${date} ${shiftType}`;
    });
};

const describeChangedShifts = (changedKeys) => {
  const labels = getChangedShiftLabels(changedKeys);
  if (labels.length === 0) {
    return "No schedule changes detected in this week.";
  }

  return `Updated shifts: ${labels.join(", ")}`;
};

const buildRuleRequirements = (rules) => {
  const map = new Map();
  (rules || []).forEach((rule) => {
    const key = `${(rule.day_of_week || "").toUpperCase()}__${(rule.shift_type || "").toUpperCase()}`;
    const prev = map.get(key) || 0;
    map.set(key, prev + (rule.required_count || 0));
  });
  return map;
};

const getShiftSemanticStatus = (shift, isChanged, requiredCount) => {
  if (isChanged) return "semantic-conflict";

  const assignments = shift.assignments || [];
  const assignedCount = assignments.filter((item) => item.employee_id != null).length;
  const hasUnassigned = assignments.some((item) => item.employee_id == null);

  if (requiredCount <= 0) {
    return hasUnassigned ? "semantic-risk" : "semantic-coverage";
  }

  if (assignedCount === 0 || hasUnassigned) return "semantic-risk";
  if (assignedCount < requiredCount) return "semantic-coverage";
  return "semantic-done";
};

function SemanticLegend() {
  return html`
    <div className="semantic-legend" aria-label="Semantic status legend">
      <span className="legend-item semantic-coverage">Coverage</span>
      <span className="legend-item semantic-risk">Risk</span>
      <span className="legend-item semantic-conflict">Conflict</span>
      <span className="legend-item semantic-done">Completed</span>
    </div>
  `;
}

function ChatWidget({
  messages,
  onSend,
  onClear,
  pendingPreview,
  onConfirmPreview,
  onCancelPreview,
}) {
  const [isOpen, setIsOpen] = useState(true);
  const [input, setInput] = useState("");
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  const submit = async (event) => {
    event.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    await onSend(text);
  };

  return html`
    <div className="chat-widget">
      ${isOpen
        ? html`
            <div className="chat-widget-panel">
              <div className="chat-widget-header">
                <div>
                  <strong>Assistant Chat</strong>
                  <p>OpenAI intent parser</p>
                </div>
                <button type="button" className="chat-mini-btn" onClick=${() => setIsOpen(false)}>
                  Close
                </button>
              </div>
              <div className="chat-log" ref=${logRef}>
                ${messages.length === 0
                  ? html`<div className="message system">No messages yet. Ask for a schedule update.</div>`
                  : messages.map(
                      (msg, index) =>
                        html`<div key=${index} className=${`message ${msg.role}`}>${msg.text}</div>`
                    )}
              </div>
              ${pendingPreview
                ? html`
                    <div className="preview-card">
                      <p className="preview-title">Impact preview</p>
                      <p className="preview-text">${pendingPreview.preview_message}</p>
                      <p className="preview-metrics">
                        ${pendingPreview.impact.assignments} assignments | ${pendingPreview.impact.shifts}
                        shifts | ${pendingPreview.impact.people} people
                      </p>
                      <div className="preview-actions">
                        <button type="button" className="primary" onClick=${onConfirmPreview}>
                          Confirm
                        </button>
                        <button type="button" onClick=${onCancelPreview}>Cancel</button>
                      </div>
                    </div>
                  `
                : null}
              <form className="chat-form" onSubmit=${submit}>
                <textarea
                  rows="3"
                  placeholder="Try: Fill 2026-03-19 with 2 cooks and 1 server for lunch"
                  value=${input}
                  onInput=${(event) => setInput(event.target.value)}
                ></textarea>
                <div className="chat-actions">
                  <button type="submit" className="primary">Send</button>
                  <button type="button" onClick=${onClear}>Clear</button>
                </div>
              </form>
            </div>
          `
        : null}

      <button type="button" className="chat-bubble" onClick=${() => setIsOpen((prev) => !prev)}>
        Chat
      </button>
    </div>
  `;
}

function DailyView({
  actionDate,
  reoptimize,
  setReoptimize,
  shifts,
  changedTypes,
  onSelectDay,
  onPrevDay,
  onNextDay,
  onToday,
  onAutofill,
  ruleRequirements,
}) {
  const byType = useMemo(
    () => new Map((shifts || []).map((shift) => [shift.shift_type, shift])),
    [shifts]
  );

  return html`
    <div className="panel schedule-panel">
      <div className="daily-header-line">
        <div className="daily-title-block">
          <h2>Daily View</h2>
          <span className="daily-title-note">Date ${actionDate}</span>
        </div>
        <div className="buttons daily-main-actions">
          <button type="button" onClick=${onPrevDay}>Prev Day</button>
          <button type="button" onClick=${onToday}>Today</button>
          <button type="button" onClick=${onNextDay}>Next Day</button>
          <button type="button" className="primary" onClick=${onAutofill}>Autofill Day</button>
        </div>
        <div className="daily-side-controls">
          <label className="daily-date-input">
            <span>Action Date</span>
            <input
              type="date"
              value=${actionDate}
              onChange=${(event) => {
                const value = event.target.value;
                onSelectDay(normalizeIsoDate(value, actionDate));
              }}
            />
          </label>
          <label className="daily-reoptimize-toggle">
            <input
              type="checkbox"
              checked=${reoptimize}
              onChange=${(event) => setReoptimize(event.target.checked)}
            />
            <span>Reoptimize</span>
          </label>
        </div>
      </div>
      <${SemanticLegend} />
      <div className="schedule-grid-day">
        ${SHIFT_TYPES.map((type) => {
          const shift = byType.get(type) || { date: actionDate, shift_type: type, assignments: [] };
          const assignmentCount = shift.assignments.length;
          const assignedCount = (shift.assignments || []).filter((item) => item.employee_id != null).length;
          const isChanged = changedTypes.has(type);
          const dayKey = getDayOfWeek(shift.date || actionDate);
          const requiredCount = ruleRequirements.get(`${dayKey}__${type}`) || 0;
          const semanticStatus = getShiftSemanticStatus(shift, isChanged, requiredCount);
          return html`
            <div className=${`shift-card daily-shift-card ${semanticStatus} ${isChanged ? "changed" : ""}`} key=${type}>
              <div className="shift-header">
                <strong>${shift.date}</strong>
                <div className="shift-header-right">
                  <span className="requirement-chip">${assignedCount}/${requiredCount}</span>
                  <span className="count-chip">${assignmentCount}</span>
                  <span className="shift-tag">${shift.shift_type}</span>
                </div>
              </div>
              <div className="daily-assignment-list">
                ${shift.assignments.length === 0
                  ? html`<div className="assignment"><span className="role">No assignments</span><span className="employee">-</span></div>`
                  : shift.assignments.map(
                      (item, index) => html`
                        <div className="assignment" key=${`${type}-${index}`}>
                          <span className="role">${item.role_name}</span>
                          <span className="employee">${item.employee_name || "Unassigned"}</span>
                        </div>
                      `
                    )}
              </div>
            </div>
          `;
        })}
      </div>
    </div>
  `;
}

function WeeklyView({
  weekStart,
  shifts,
  changedKeys,
  onSelectWeek,
  onPrevWeek,
  onThisWeek,
  onNextWeek,
  onToday,
  onAutofillWeek,
  onOpenDay,
  onAutofillDay,
  ruleRequirements,
}) {
  const byKey = useMemo(
    () => new Map((shifts || []).map((shift) => [shiftKey(shift.date, shift.shift_type), shift])),
    [shifts]
  );

  const weekDates = useMemo(() => getWeekDates(weekStart), [weekStart]);

  return html`
    <div className="panel weekly-panel">
      <div className="weekly-header-line">
        <div className="weekly-title-block">
          <h2>Weekly View</h2>
          <span className="weekly-title-note">Week of ${weekStart}</span>
        </div>
        <div className="buttons weekly-main-actions">
          <button type="button" onClick=${onPrevWeek}>Prev Week</button>
          <button type="button" onClick=${onThisWeek}>This Week</button>
          <button type="button" onClick=${onNextWeek}>Next Week</button>
          <button type="button" onClick=${onToday}>Today</button>
          <button type="button" className="primary" onClick=${onAutofillWeek}>
            Autofill Week
          </button>
        </div>
        <label className="weekly-week-input">
          <span>Week Start</span>
          <input
            type="date"
            value=${weekStart}
            onChange=${(event) => {
              const value = normalizeIsoDate(event.target.value, weekStart);
              onSelectWeek(getWeekStart(value));
            }}
          />
        </label>
      </div>
      <div className="change-box">
        <p className="change-summary">${describeChangedShifts(changedKeys)}</p>
        ${getChangedShiftLabels(changedKeys).length > 0
          ? html`
              <div className="change-list">
                ${getChangedShiftLabels(changedKeys).map(
                  (label) => html`<span className="change-chip" key=${label}>${label}</span>`
                )}
              </div>
            `
          : null}
      </div>
      <${SemanticLegend} />
      <div className="schedule-grid-week">
        ${weekDates.map((date, dayIndex) => html`
          <div className="day-column" key=${date}>
            <div className="day-header">
              <div className="day-title-group">
                <div className="day-name">${DAY_LABELS[dayIndex]}</div>
                <div className="day-date">${date}</div>
              </div>
              <div className="day-actions-inline">
                <button type="button" className="mini-btn" onClick=${() => onOpenDay(date)}>
                  Open
                </button>
                <button
                  type="button"
                  className="mini-btn mini-btn-primary"
                  onClick=${() => onAutofillDay(date)}
                >
                  Fill
                </button>
              </div>
            </div>
            ${SHIFT_TYPES.map((type) => {
              const key = shiftKey(date, type);
              const shift = byKey.get(key) || { date, shift_type: type, assignments: [] };
              const assignmentCount = shift.assignments.length;
              const assignedCount = (shift.assignments || []).filter((item) => item.employee_id != null).length;
              const isChanged = changedKeys.has(key);
              const dayKey = getDayOfWeek(date);
              const requiredCount = ruleRequirements.get(`${dayKey}__${type}`) || 0;
              const semanticStatus = getShiftSemanticStatus(shift, isChanged, requiredCount);
              return html`
                <div
                  className=${`shift-card weekly-shift-card ${semanticStatus} ${isChanged ? "changed" : ""}`}
                  key=${key}
                >
                  <div className="shift-header">
                    <div className="shift-header-right">
                      <span className="requirement-chip">${assignedCount}/${requiredCount}</span>
                      <span className="count-chip">${assignmentCount}</span>
                      <span className="shift-tag">${type}</span>
                    </div>
                  </div>
                  <div className="weekly-assignment-list">
                    ${shift.assignments.length === 0
                      ? html`<div className="assignment"><span className="role">No assignments</span><span className="employee">-</span></div>`
                      : shift.assignments.map(
                          (item, index) => html`
                            <div className="assignment" key=${`${key}-${index}`}>
                              <span className="role">${item.role_name}</span>
                              <span className="employee">${item.employee_name || "Unassigned"}</span>
                            </div>
                          `
                        )}
                  </div>
                </div>
              `;
            })}
          </div>
        `)}
      </div>
    </div>
  `;
}

function TeamInsightsPanel({ weekStart, insights }) {
  return html`
    <section className="panel team-panel">
      <div className="panel-header">
        <h2>Team Weekly Snapshot</h2>
        <span className="pill">Week of ${weekStart}</span>
      </div>
      <div className="team-grid">
        ${(insights || []).map((employee) => {
          const restrictions = employee.restrictions || [];
          const visibleRestrictions = restrictions.slice(0, 3);
          const overflow = restrictions.length - visibleRestrictions.length;
          return html`
            <article className="member-card" key=${employee.id}>
              <div className="member-header">
                <h3>${employee.name}</h3>
                <span className="hours-badge">
                  ${employee.worked_hours_week}h / ${employee.max_weekly_hours}h
                </span>
              </div>
              <p className="member-subtitle">
                Remaining: ${employee.remaining_hours_week}h
              </p>
              <p className="member-meta">
                Roles: ${employee.roles.length > 0 ? employee.roles.join(", ") : "None"}
              </p>
              <div className="restrictions-block">
                <p className="member-subtitle">Restrictions</p>
                ${visibleRestrictions.length === 0
                  ? html`<p className="member-meta">No availability restrictions</p>`
                  : html`
                      <div className="restriction-list">
                        ${visibleRestrictions.map(
                          (item) => html`<span className="restriction-chip" key=${item}>${item}</span>`
                        )}
                        ${overflow > 0
                          ? html`<span className="restriction-chip">+${overflow} more</span>`
                          : null}
                      </div>
                    `}
              </div>
            </article>
          `;
        })}
      </div>
    </section>
  `;
}

function App() {
  const initialToday = fmtDate(new Date());
  const initialWeek = getWeekStart(initialToday);

  const [route, setRoute] = useState(window.location.pathname === "/weekly" ? "weekly" : "daily");
  const [health, setHealth] = useState("Checking API...");
  const [messages, setMessages] = useState([]);

  const [actionDate, setActionDate] = useState(initialToday);
  const [weekStart, setWeekStart] = useState(initialWeek);
  const [reoptimize, setReoptimize] = useState(false);

  const [dailyShifts, setDailyShifts] = useState([]);
  const [weeklyShifts, setWeeklyShifts] = useState([]);
  const [teamInsights, setTeamInsights] = useState([]);
  const [scheduleRules, setScheduleRules] = useState([]);
  const [changedDayTypes, setChangedDayTypes] = useState(new Set());
  const [changedWeekKeys, setChangedWeekKeys] = useState(new Set());
  const [pendingPreview, setPendingPreview] = useState(null);
  const ruleRequirements = useMemo(() => buildRuleRequirements(scheduleRules), [scheduleRules]);

  useEffect(() => {
    const onPopState = () => {
      setRoute(window.location.pathname === "/weekly" ? "weekly" : "daily");
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (targetRoute) => {
    const path = targetRoute === "weekly" ? "/weekly" : "/";
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setRoute(targetRoute);
  };

  const appendMessage = (role, text) => {
    setMessages((prev) => [...prev, { role, text }]);
  };

  const refreshDay = async (targetDate = actionDate) => {
    const data = await fetchJson(`/schedules?start_date=${targetDate}&end_date=${targetDate}`);
    setDailyShifts(data);
    return data;
  };

  const refreshWeek = async (targetWeekStart = weekStart) => {
    const weekDates = getWeekDates(targetWeekStart);
    const endDate = weekDates[weekDates.length - 1];
    const data = await fetchJson(`/schedules?start_date=${targetWeekStart}&end_date=${endDate}`);
    setWeeklyShifts(data);
    return data;
  };

  const refreshInsights = async (targetWeekStart = weekStart) => {
    const data = await fetchJson(`/employees/insights?week_start=${targetWeekStart}`);
    setTeamInsights(data);
    return data;
  };

  const refreshRules = async () => {
    const data = await fetchJson("/schedule-rules");
    setScheduleRules(data);
    return data;
  };

  const runChatCommand = async (message, action = null) => {
    const beforeDayMap = buildDayMap(dailyShifts);
    const beforeWeekMap = buildWeekMap(weeklyShifts);

    const payload = {};
    if (message) payload.message = message;
    if (action) payload.action = action;

    const response = await fetchJson("/chat/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    appendMessage("system", summarizeResponse(response));

    let nextActionDate = actionDate;
    let nextWeekStart = weekStart;

    if (response.action_type === "AUTOFILL_DAY") {
      const targetDate = action?.date || response.result?.date;
      if (targetDate) {
        nextActionDate = targetDate;
        nextWeekStart = getWeekStart(targetDate);
      }
    }

    if (response.action_type === "LIST_SCHEDULE") {
      const startDate = response.result?.[0]?.date;
      if (startDate) {
        nextActionDate = startDate;
        nextWeekStart = getWeekStart(startDate);
      }
    }

    setActionDate(nextActionDate);
    setWeekStart(nextWeekStart);

    if (response.action_type === "SET_RULE") {
      await refreshRules();
    }

    const dayData = await refreshDay(nextActionDate);
    const weekData = await refreshWeek(nextWeekStart);
    await refreshInsights(nextWeekStart);

    const afterDayMap = buildDayMap(dayData);
    const afterWeekMap = buildWeekMap(weekData);

    setChangedDayTypes(diffMaps(beforeDayMap, afterDayMap));
    setChangedWeekKeys(diffMaps(beforeWeekMap, afterWeekMap));
  };

  useEffect(() => {
    const bootstrap = async () => {
      try {
        await fetchJson("/health");
        setHealth("API online");
      } catch {
        setHealth("API offline");
      }

      await refreshDay(initialToday);
      await refreshWeek(initialWeek);
      await refreshInsights(initialWeek);
      await refreshRules();
    };

    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSendChat = async (text) => {
    appendMessage("user", text);
    try {
      const preview = await fetchJson("/chat/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      setPendingPreview({ ...preview, message: text });
      appendMessage("system", preview.preview_message);
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onConfirmPreview = async () => {
    if (!pendingPreview) return;

    try {
      await runChatCommand(pendingPreview.message || "", pendingPreview.action || null);
      setPendingPreview(null);
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onCancelPreview = () => {
    if (!pendingPreview) return;
    setPendingPreview(null);
    appendMessage("system", "Preview canceled.");
  };

  const onAutofill = async () => {
    appendMessage("user", `autofill ${actionDate}`);
    setPendingPreview(null);

    try {
      await runChatCommand(`autofill ${actionDate}`, {
        type: "AUTOFILL_DAY",
        date: actionDate,
        reoptimize,
      });
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onSelectDay = async (targetDate = actionDate) => {
    if (!targetDate) {
      return;
    }
    try {
      const beforeDayMap = buildDayMap(dailyShifts);
      const dayData = await refreshDay(targetDate);
      const normalizedWeek = getWeekStart(targetDate);
      setActionDate(targetDate);
      setWeekStart(normalizedWeek);
      await refreshWeek(normalizedWeek);
      await refreshInsights(normalizedWeek);
      setChangedDayTypes(diffMaps(beforeDayMap, buildDayMap(dayData)));
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onPrevDay = async () => {
    await onSelectDay(fmtDate(addDays(toDate(actionDate), -1)));
  };

  const onNextDay = async () => {
    await onSelectDay(fmtDate(addDays(toDate(actionDate), 1)));
  };

  const onSelectWeek = async (targetWeekStart = weekStart) => {
    try {
      const normalized = getWeekStart(targetWeekStart);
      setWeekStart(normalized);
      const beforeWeekMap = buildWeekMap(weeklyShifts);
      const weekData = await refreshWeek(normalized);
      await refreshInsights(normalized);
      setChangedWeekKeys(diffMaps(beforeWeekMap, buildWeekMap(weekData)));
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onPrevWeek = async () => {
    await onSelectWeek(fmtDate(addDays(toDate(weekStart), -7)));
  };

  const onNextWeek = async () => {
    await onSelectWeek(fmtDate(addDays(toDate(weekStart), 7)));
  };

  const onToday = async () => {
    const today = fmtDate(new Date());
    const todayWeek = getWeekStart(today);
    setActionDate(today);
    setWeekStart(todayWeek);
    try {
      await refreshDay(today);
      await refreshWeek(todayWeek);
      await refreshInsights(todayWeek);
      setChangedDayTypes(new Set());
      setChangedWeekKeys(new Set());
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onThisWeek = async () => {
    const now = fmtDate(new Date());
    const week = getWeekStart(now);
    setActionDate(now);
    setWeekStart(week);
    try {
      await refreshDay(now);
      await refreshWeek(week);
      await refreshInsights(week);
      setChangedDayTypes(new Set());
      setChangedWeekKeys(new Set());
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onAutofillWeek = async () => {
    setPendingPreview(null);
    const targetWeekStart = getWeekStart(weekStart);
    const dates = getWeekDates(targetWeekStart);

    setWeekStart(targetWeekStart);
    const beforeWeekMap = buildWeekMap(weeklyShifts);
    const beforeDayMap = buildDayMap(dailyShifts);
    const selectedDateBefore = actionDate;

    try {
      let totalFilled = 0;

      for (const date of dates) {
        const payload = {
          date,
          reoptimize: false,
        };
        const response = await fetchJson("/schedules/autofill", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        const dayFilled = (response.results || []).reduce(
          (sum, item) => sum + (item.created || 0),
          0
        );
        totalFilled += dayFilled;
      }

      appendMessage("system", `Weekly autofill completed: ${totalFilled} assignments created.`);

      const weekData = await refreshWeek(targetWeekStart);
      const dayData = await refreshDay(selectedDateBefore);
      await refreshInsights(targetWeekStart);

      setChangedWeekKeys(diffMaps(beforeWeekMap, buildWeekMap(weekData)));
      setChangedDayTypes(diffMaps(beforeDayMap, buildDayMap(dayData)));
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onOpenDayFromWeek = async (date) => {
    setActionDate(date);
    setWeekStart(getWeekStart(date));
    navigate("daily");

    try {
      await refreshDay(date);
      setChangedDayTypes(new Set());
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  const onAutofillDayFromWeek = async (date) => {
    setPendingPreview(null);
    const beforeWeekMap = buildWeekMap(weeklyShifts);
    const beforeDayMap = buildDayMap(dailyShifts);

    try {
      const response = await fetchJson("/schedules/autofill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, reoptimize: false }),
      });

      const filled = (response.results || []).reduce((sum, item) => sum + (item.created || 0), 0);
      appendMessage("system", `${date}: ${filled} assignments created.`);

      const normalizedWeek = getWeekStart(date);
      const weekData = await refreshWeek(normalizedWeek);
      const dayData = await refreshDay(actionDate);
      await refreshInsights(normalizedWeek);

      setChangedWeekKeys(diffMaps(beforeWeekMap, buildWeekMap(weekData)));
      setChangedDayTypes(diffMaps(beforeDayMap, buildDayMap(dayData)));
    } catch (error) {
      appendMessage("system", `Error: ${error.message}`);
    }
  };

  return html`
    <div className=${`app-shell ${route === "weekly" ? "weekly-page" : "daily-page"}`}>
      <div className="backdrop">
        <div className="orb orb-one"></div>
        <div className="orb orb-two"></div>
        <div className="orb orb-three"></div>
      </div>

      <main className="page">
        <header className="topbar">
          <div className="topbar-left">
            <p className="eyebrow">Restaurant Staffing OS</p>
            <p className="title-small">Schedule command center</p>
          </div>
          <div className="nav-switch topbar-nav">
            <button
              type="button"
              className=${`tab-btn ${route === "daily" ? "active" : ""}`}
              onClick=${() => navigate("daily")}
            >
              Main Page (Daily)
            </button>
            <button
              type="button"
              className=${`tab-btn ${route === "weekly" ? "active" : ""}`}
              onClick=${() => navigate("weekly")}
            >
              Weekly Page
            </button>
          </div>
          <div className="status-badge">
            <span className="status-dot"></span>
            ${health}
          </div>
        </header>

        ${route === "daily"
          ? html`
              <section className="layout">
                <${DailyView}
                  actionDate=${actionDate}
                  reoptimize=${reoptimize}
                  setReoptimize=${setReoptimize}
                  shifts=${dailyShifts}
                  changedTypes=${changedDayTypes}
                  onSelectDay=${onSelectDay}
                  onPrevDay=${onPrevDay}
                  onNextDay=${onNextDay}
                  onToday=${onToday}
                  onAutofill=${onAutofill}
                  ruleRequirements=${ruleRequirements}
                />
              </section>
              <${TeamInsightsPanel} weekStart=${weekStart} insights=${teamInsights} />
            `
          : html`
              <section className="weekly-layout">
                <${WeeklyView}
                  weekStart=${weekStart}
                  shifts=${weeklyShifts}
                  changedKeys=${changedWeekKeys}
                  onSelectWeek=${onSelectWeek}
                  onPrevWeek=${onPrevWeek}
                  onThisWeek=${onThisWeek}
                  onNextWeek=${onNextWeek}
                  onToday=${onToday}
                  onAutofillWeek=${onAutofillWeek}
                  onOpenDay=${onOpenDayFromWeek}
                  onAutofillDay=${onAutofillDayFromWeek}
                  ruleRequirements=${ruleRequirements}
                />
              </section>
              <${TeamInsightsPanel} weekStart=${weekStart} insights=${teamInsights} />
            `}
      </main>

      <${ChatWidget}
        messages=${messages}
        onSend=${onSendChat}
        onClear=${() => {
          setMessages([]);
          setPendingPreview(null);
        }}
        pendingPreview=${pendingPreview}
        onConfirmPreview=${onConfirmPreview}
        onCancelPreview=${onCancelPreview}
      />
    </div>
  `;
}

const root = createRoot(document.getElementById("root"));
root.render(html`<${App} />`);
